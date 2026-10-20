from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any

from sqlalchemy import text

from shared.db import SessionLocal


_INSTALLED = False
_BOT = None
_SWITCH_ORDER_ID: ContextVar[int | None] = ContextVar(
    "vip_timer_switch_order_id",
    default=None,
)

_ORIGINAL_IS_TIMER_RULE = None
_ORIGINAL_PUBLIC_HOURLY_RULES = None
_ORIGINAL_RULE_SNAPSHOT = None
_ORIGINAL_ATTACH_TICKET = None
_ORIGINAL_SWITCH_RULE = None
_ORIGINAL_START_TIMER = None
_ORIGINAL_PAUSE_TIMER = None
_ORIGINAL_RESUME_TIMER = None
_ORIGINAL_END_TIMER = None
_ORIGINAL_RECONCILE = None


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    text_value = str(value or "").strip()
    if not text_value:
        return {}
    try:
        parsed = json.loads(text_value)
    except Exception:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _order_context(order_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT
                    o.status AS order_status,
                    o.price_snapshot_json AS price_snapshot_json,
                    a.required_staff_count AS required_staff_count
                FROM web_orders o
                LEFT JOIN order_acceptance_meta a
                  ON a.order_id = o.id
                WHERE o.id = :order_id
                LIMIT 1
                """
            ),
            {"order_id": int(order_id)},
        ).mappings().first()
    except Exception:
        row = None
    finally:
        db.close()

    if row is None:
        return {
            "order_status": "",
            "staff_count": 1,
            "player_count": 1,
        }

    snapshot = _json_dict(row.get("price_snapshot_json"))
    player_count = max(1, int(snapshot.get("player_count") or 1))
    staff_count = row.get("required_staff_count")
    try:
        staff_count = max(1, int(staff_count or player_count))
    except (TypeError, ValueError):
        staff_count = player_count

    return {
        "order_status": str(row.get("order_status") or "").strip().lower(),
        "staff_count": staff_count,
        "player_count": player_count,
    }


def _visible_catalog_rule_keys() -> set[str]:
    visible: set[str] = set()

    try:
        from services.orders import (
            CATALOG_HIDDEN_RULE_KEYS,
            SELF_SERVICE_ORDER_CATALOG,
        )

        hidden = {
            str(value)
            for value in CATALOG_HIDDEN_RULE_KEYS
        }
        for groups in SELF_SERVICE_ORDER_CATALOG.values():
            for group in groups or []:
                for detail in group.get("details", []) or []:
                    key = str(detail.get("rule_key") or "").strip()
                    if key and key not in hidden:
                        visible.add(key)
    except Exception:
        pass

    return visible


def is_timer_rule_eligible(
    rule_key: str,
    *,
    require_public: bool = True,
) -> bool:
    from services import vip_timer as timer

    key = str(rule_key or "").strip()
    rule = timer.ORDER_RULES.get(key)
    if rule is None:
        return False
    if str(getattr(rule, "pricing_type", "") or "") != "hourly":
        return False
    if int(getattr(rule, "price", 0) or 0) <= 0:
        return False
    if int(getattr(rule, "min_quantity", 1) or 1) > 1:
        # 自由計時不能拿來繞過原商品明確設定的最低時數門檻。
        return False
    if not timer.is_order_product_active(key):
        return False

    if not require_public:
        return True

    visible = _visible_catalog_rule_keys()
    if key in visible:
        return True

    is_custom = getattr(timer.ORDER_RULES, "is_custom", None)
    if callable(is_custom):
        try:
            return bool(is_custom(key))
        except Exception:
            return False

    return False


def effective_hourly_rate(
    rule_key: str,
    *,
    staff_count: int,
) -> int:
    from services import vip_timer as timer

    key = str(rule_key or "").strip()
    rule = timer.ORDER_RULES.get(key)
    if rule is None:
        raise ValueError("找不到這個玩法。")

    count = max(1, int(staff_count or 1))
    if bool(getattr(rule, "player_count_enabled", False)):
        minimum = max(1, int(getattr(rule, "min_player_count", 1) or 1))
        maximum = getattr(rule, "max_player_count", None)
        if count < minimum:
            raise ValueError(f"這個玩法最少需要 {minimum} 位接單人。")
        if maximum is not None and count > int(maximum):
            raise ValueError(f"這個玩法最多只能有 {int(maximum)} 位接單人。")

    amount = int(getattr(rule, "price", 0) or 0)
    if bool(getattr(rule, "price_multiply_player_count", False)):
        amount *= count
    return max(0, amount)


def _target_required_staff_count(rule, fixed_staff_count: int) -> int:
    count = max(1, int(fixed_staff_count or 1))
    required = getattr(rule, "required_staff_count", 1)
    if required == "player_count":
        minimum = max(1, int(getattr(rule, "min_player_count", 1) or 1))
        maximum = getattr(rule, "max_player_count", None)
        if count < minimum:
            raise ValueError(f"這個玩法最少需要 {minimum} 位接單人。")
        if maximum is not None and count > int(maximum):
            raise ValueError(f"這個玩法最多只能有 {int(maximum)} 位接單人。")
        return count
    return max(1, int(required or 1))


def _resolve_guild_members(staff_ids: list[str]):
    if _BOT is None:
        return None, []

    numeric_ids: list[int] = []
    for value in staff_ids:
        try:
            numeric_ids.append(int(value))
        except (TypeError, ValueError):
            return None, []

    for guild in getattr(_BOT, "guilds", ()) or ():
        members = [guild.get_member(user_id) for user_id in numeric_ids]
        if all(member is not None for member in members):
            return guild, members

    return None, []


def _validate_switch_staff(
    order_id: int,
    rule_key: str,
    staff_ids: list[str] | None,
) -> None:
    from services import vip_timer as timer
    from services.order_rules import (
        PROTECTOR_ROLES,
        ROLE_IDS,
        get_allowed_role_ids,
        get_required_game_role_ids,
        role_ids_match_requirements,
    )

    key = str(rule_key or "").strip()
    if not is_timer_rule_eligible(key, require_public=True):
        raise ValueError("這個玩法不能用於 VIP 自由計時，請改選其他玩法。")

    rule = timer.ORDER_RULES.get(key)
    if rule is None:
        raise ValueError("找不到這個玩法。")

    context = _order_context(int(order_id))
    fixed_staff_count = max(1, int(context.get("staff_count") or 1))
    required_count = _target_required_staff_count(rule, fixed_staff_count)
    if required_count != fixed_staff_count:
        raise ValueError(
            f"這個玩法需要 {required_count} 位接單人，"
            f"目前這張計時單固定為 {fixed_staff_count} 位；"
            "請結束後重新下單。"
        )

    unique_staff = []
    for value in staff_ids or []:
        text_value = str(value or "").strip()
        if text_value and text_value not in unique_staff:
            unique_staff.append(text_value)

    if unique_staff and len(unique_staff) != fixed_staff_count:
        raise ValueError(
            f"目前已接單人數為 {len(unique_staff)} 位，"
            f"但本單固定需要 {fixed_staff_count} 位，暫時不能切換玩法。"
        )

    if not unique_staff or _BOT is None:
        return

    guild, members = _resolve_guild_members(unique_staff)
    if guild is None or len(members) != len(unique_staff):
        raise ValueError("目前無法確認接單人的遊戲資格，請稍後再切換玩法。")

    allowed_role_ids = get_allowed_role_ids(rule)
    required_game_role_ids = get_required_game_role_ids(rule)
    ineligible = []

    for member in members:
        member_role_ids = [
            str(role.id)
            for role in getattr(member, "roles", ()) or ()
            if getattr(role, "id", None) is not None
        ]
        if not role_ids_match_requirements(
            member_role_ids,
            allowed_role_ids,
            required_game_role_ids,
        ):
            ineligible.append(
                str(
                    getattr(member, "display_name", None)
                    or getattr(member, "name", None)
                    or getattr(member, "id", "未知接單人")
                )
            )

    min_protectors = max(0, int(getattr(rule, "min_protector_count", 0) or 0))
    if min_protectors:
        protector_ids = {
            str(ROLE_IDS[key])
            for key in PROTECTOR_ROLES
            if key in ROLE_IDS
        }
        protector_count = 0
        for member in members:
            member_role_ids = {
                str(role.id)
                for role in getattr(member, "roles", ()) or ()
                if getattr(role, "id", None) is not None
            }
            if member_role_ids & protector_ids:
                protector_count += 1
        if protector_count < min_protectors:
            raise ValueError(
                f"這個玩法至少需要 {min_protectors} 位護航，"
                "目前接單陣容不符合資格。"
            )

    if ineligible:
        names = "、".join(ineligible[:4])
        raise ValueError(
            f"目前接單陣容無法切到這個玩法：{names} 缺少對應身分／遊戲資格。"
        )


def _sync_session_rate(order_id: int) -> None:
    from services import vip_timer as timer

    session = timer.get_session(int(order_id))
    if not session:
        return

    context = _order_context(int(order_id))
    rate = effective_hourly_rate(
        str(session.get("current_rule_key") or ""),
        staff_count=max(1, int(context.get("staff_count") or 1)),
    )

    db = SessionLocal()
    try:
        db.execute(
            text(
                """
                UPDATE vip_timer_sessions
                SET current_hourly_rate = :rate,
                    updated_at = :updated_at
                WHERE order_id = :order_id
                """
            ),
            {
                "rate": int(rate),
                "updated_at": timer.utc_iso(),
                "order_id": int(order_id),
            },
        )
        db.commit()
    finally:
        db.close()


def _mark_terminal_session(order_id: int, status: str) -> None:
    from services import vip_timer as timer

    if status in {"cancelled", "canceled"}:
        timer_status = "cancelled"
    elif status in {"active", "closed"}:
        timer_status = "paid"
    else:
        return

    db = SessionLocal()
    try:
        timer.ensure_vip_timer_tables(db)
        db.execute(
            text(
                """
                UPDATE vip_timer_sessions
                SET status = :status,
                    updated_at = :updated_at
                WHERE order_id = :order_id
                  AND status IN (
                      'waiting_staff', 'ready', 'running', 'paused', 'pending_payment'
                  )
                """
            ),
            {
                "status": timer_status,
                "updated_at": timer.utc_iso(),
                "order_id": int(order_id),
            },
        )
        db.commit()
    finally:
        db.close()


def _assert_order_not_terminal(order_id: int) -> None:
    status = str(_order_context(int(order_id)).get("order_status") or "")
    if status in {"cancelled", "canceled"}:
        _mark_terminal_session(order_id, status)
        raise ValueError("這張 VIP 自由計時單已取消，不能再操作計時。")
    if status in {"active", "closed"}:
        _mark_terminal_session(order_id, status)
        raise ValueError("這張 VIP 自由計時單已完成付款，不能再操作計時。")


def _patched_reconcile(db, customer_id: str) -> None:
    from services import vip_timer as timer

    if _ORIGINAL_RECONCILE is not None:
        _ORIGINAL_RECONCILE(db, customer_id)

    try:
        rows = db.execute(
            text(
                """
                SELECT s.order_id, o.status AS order_status
                FROM vip_timer_sessions s
                JOIN web_orders o ON o.id = s.order_id
                WHERE s.customer_discord_id = :customer_id
                  AND s.status IN (
                      'waiting_staff', 'ready', 'running', 'paused', 'pending_payment'
                  )
                """
            ),
            {"customer_id": str(customer_id)},
        ).mappings().all()
    except Exception:
        return

    now = timer.utc_iso()
    for row in rows:
        order_status = str(row.get("order_status") or "").strip().lower()
        if order_status in {"active", "closed"}:
            next_status = "paid"
        elif order_status in {"cancelled", "canceled"}:
            next_status = "cancelled"
        else:
            continue
        db.execute(
            text(
                """
                UPDATE vip_timer_sessions
                SET status = :status,
                    updated_at = :updated_at
                WHERE order_id = :order_id
                """
            ),
            {
                "status": next_status,
                "updated_at": now,
                "order_id": int(row["order_id"]),
            },
        )


def install_vip_timer_policy(bot_instance=None) -> None:
    """Install business guards shared by the Web-created VIP timer and Discord runtime."""
    global _INSTALLED, _BOT
    global _ORIGINAL_IS_TIMER_RULE, _ORIGINAL_PUBLIC_HOURLY_RULES
    global _ORIGINAL_RULE_SNAPSHOT, _ORIGINAL_ATTACH_TICKET, _ORIGINAL_SWITCH_RULE
    global _ORIGINAL_START_TIMER, _ORIGINAL_PAUSE_TIMER, _ORIGINAL_RESUME_TIMER
    global _ORIGINAL_END_TIMER, _ORIGINAL_RECONCILE

    if bot_instance is not None:
        _BOT = bot_instance

    if _INSTALLED:
        return

    from services import vip_timer as timer

    _ORIGINAL_IS_TIMER_RULE = timer.is_vip_timer_rule_key
    _ORIGINAL_PUBLIC_HOURLY_RULES = timer.public_hourly_rules
    _ORIGINAL_RULE_SNAPSHOT = timer.rule_snapshot
    _ORIGINAL_ATTACH_TICKET = timer.attach_ticket
    _ORIGINAL_SWITCH_RULE = timer.switch_rule
    _ORIGINAL_START_TIMER = timer.start_timer
    _ORIGINAL_PAUSE_TIMER = timer.pause_timer
    _ORIGINAL_RESUME_TIMER = timer.resume_timer
    _ORIGINAL_END_TIMER = timer.end_timer
    _ORIGINAL_RECONCILE = timer.reconcile_customer_sessions

    def guarded_is_timer_rule(rule_key: Any) -> bool:
        if not _ORIGINAL_IS_TIMER_RULE(rule_key):
            return False
        real_key = timer.strip_vip_timer_rule_key(rule_key)
        return is_timer_rule_eligible(real_key, require_public=True)

    def guarded_public_hourly_rules():
        rows = []
        for source in _ORIGINAL_PUBLIC_HOURLY_RULES():
            key = str(source.get("rule_key") or "").strip()
            if not is_timer_rule_eligible(key, require_public=True):
                continue
            item = dict(source)
            rule = timer.ORDER_RULES.get(key)
            if rule is not None and bool(
                getattr(rule, "price_multiply_player_count", False)
            ):
                item["label"] = f"{item.get('label') or key}｜每人計價"
            rows.append(item)
        return rows

    def guarded_rule_snapshot(rule_key: str):
        snap = dict(_ORIGINAL_RULE_SNAPSHOT(rule_key))
        order_id = _SWITCH_ORDER_ID.get()
        if order_id is not None:
            context = _order_context(int(order_id))
            snap["hourly_rate"] = effective_hourly_rate(
                str(snap.get("rule_key") or rule_key),
                staff_count=max(1, int(context.get("staff_count") or 1)),
            )
        return snap

    def guarded_attach_ticket(order_id: int, **kwargs):
        result = _ORIGINAL_ATTACH_TICKET(order_id, **kwargs)
        _sync_session_rate(int(order_id))
        return result

    def guarded_start(order_id: int, *args, **kwargs):
        _assert_order_not_terminal(int(order_id))
        _sync_session_rate(int(order_id))
        return _ORIGINAL_START_TIMER(order_id, *args, **kwargs)

    def guarded_pause(order_id: int, *args, **kwargs):
        _assert_order_not_terminal(int(order_id))
        return _ORIGINAL_PAUSE_TIMER(order_id, *args, **kwargs)

    def guarded_resume(order_id: int, *args, **kwargs):
        _assert_order_not_terminal(int(order_id))
        return _ORIGINAL_RESUME_TIMER(order_id, *args, **kwargs)

    def guarded_switch(
        order_id: int,
        new_rule_key: str,
        actor_id: Any,
        staff_ids: list[str] | None = None,
    ):
        _assert_order_not_terminal(int(order_id))
        _validate_switch_staff(
            int(order_id),
            str(new_rule_key),
            staff_ids,
        )
        token = _SWITCH_ORDER_ID.set(int(order_id))
        try:
            return _ORIGINAL_SWITCH_RULE(
                int(order_id),
                str(new_rule_key),
                actor_id,
                staff_ids,
            )
        finally:
            _SWITCH_ORDER_ID.reset(token)

    def guarded_end(order_id: int, *args, **kwargs):
        _assert_order_not_terminal(int(order_id))
        return _ORIGINAL_END_TIMER(order_id, *args, **kwargs)

    timer.is_vip_timer_rule_key = guarded_is_timer_rule
    timer.public_hourly_rules = guarded_public_hourly_rules
    timer.rule_snapshot = guarded_rule_snapshot
    timer.attach_ticket = guarded_attach_ticket
    timer.start_timer = guarded_start
    timer.pause_timer = guarded_pause
    timer.resume_timer = guarded_resume
    timer.switch_rule = guarded_switch
    timer.end_timer = guarded_end
    timer.reconcile_customer_sessions = _patched_reconcile

    _INSTALLED = True


def install_web_vip_timer_policy(router_module) -> None:
    """Filter the synthetic storefront group with the same server-side timer policy."""
    if getattr(router_module, "_vip_timer_policy_installed", False):
        return

    original_group = router_module._vip_group

    def guarded_group(original_catalog):
        group = dict(original_group(original_catalog))
        variants = []
        for source in group.get("variants") or []:
            item = dict(source)
            real_key = str(item.get("rule_key") or "")
            if real_key.startswith("vip_timer__"):
                real_key = real_key[len("vip_timer__"):]
            if not is_timer_rule_eligible(real_key, require_public=True):
                continue
            variants.append(item)
        group["variants"] = variants
        return group

    router_module._vip_group = guarded_group
    router_module._vip_timer_policy_installed = True


__all__ = [
    "effective_hourly_rate",
    "install_vip_timer_policy",
    "install_web_vip_timer_policy",
    "is_timer_rule_eligible",
]
