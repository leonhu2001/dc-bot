from __future__ import annotations

from typing import Any

from sqlalchemy import text

from services.order_rules import (
    ORDER_RULES,
    PROTECTOR_ROLES,
    ROLE_IDS,
    get_allowed_role_ids,
    get_required_game_role_ids,
    role_ids_match_requirements,
)
from services.vip_timer import SessionLocal, strip_vip_timer_rule_key, utc_iso


_INSTALLED = False


def _unique_staff_ids(values) -> list[str]:
    result: list[str] = []
    for value in values or ():
        staff_id = str(value or "").strip()
        if staff_id and staff_id not in result:
            result.append(staff_id)
    return result


def _guild(bot_instance, guild_id: int):
    getter = getattr(bot_instance, "get_guild", None)
    return getter(int(guild_id)) if callable(getter) else None


def _rule_rate_and_validate(
    *,
    bot_instance,
    guild_id: int,
    rule_key: str,
    staff_ids,
) -> int:
    key = strip_vip_timer_rule_key(rule_key)
    rule = ORDER_RULES.get(key)
    if rule is None or str(getattr(rule, "pricing_type", "")) != "hourly":
        raise ValueError("VIP 自由計時只能切換到小時計價方案。")

    staff = _unique_staff_ids(staff_ids)
    staff_count = len(staff)
    if staff_count <= 0:
        raise ValueError("目前沒有已接單人員，無法開始或切換計時。")

    required_mode = getattr(rule, "required_staff_count", 1)
    if required_mode == "player_count":
        minimum = int(getattr(rule, "min_player_count", 1) or 1)
        maximum_raw = getattr(rule, "max_player_count", None)
        maximum = int(maximum_raw) if maximum_raw is not None else None
        if staff_count < minimum or (maximum is not None and staff_count > maximum):
            limit_text = f"{minimum}～{maximum} 位" if maximum is not None else f"至少 {minimum} 位"
            raise ValueError(f"這個玩法需要 {limit_text}接單人員，目前為 {staff_count} 位。")
    elif staff_count != int(required_mode or 1):
        raise ValueError(
            f"這個玩法需要 {int(required_mode or 1)} 位接單人員，"
            f"目前為 {staff_count} 位；自由計時第一版不支援中途增減人員。"
        )

    guild = _guild(bot_instance, guild_id)
    if guild is None:
        raise ValueError("目前無法驗證接單人員資格，請稍後再試。")

    allowed_role_ids = get_allowed_role_ids(rule)
    required_game_role_ids = get_required_game_role_ids(rule)
    protector_role_ids = {
        str(ROLE_IDS[key])
        for key in PROTECTOR_ROLES
        if key in ROLE_IDS
    }
    protector_count = 0

    for staff_id in staff:
        try:
            member = guild.get_member(int(staff_id))
        except (TypeError, ValueError):
            member = None
        if member is None:
            raise ValueError("有接單人員的 Discord 身分資料尚未載入，請稍後再試。")

        member_role_ids = [
            str(getattr(role, "id", "") or "")
            for role in getattr(member, "roles", ())
            if getattr(role, "id", None) is not None
        ]
        if not role_ids_match_requirements(
            member_role_ids,
            allowed_role_ids,
            required_game_role_ids,
        ):
            display_name = str(
                getattr(member, "display_name", None)
                or getattr(member, "name", None)
                or staff_id
            )
            raise ValueError(f"{display_name} 不符合這個玩法的接單資格，請改選其他玩法。")

        if set(member_role_ids) & protector_role_ids:
            protector_count += 1

    minimum_protectors = int(getattr(rule, "min_protector_count", 0) or 0)
    if protector_count < minimum_protectors:
        raise ValueError(
            f"這個玩法至少需要 {minimum_protectors} 位護航，"
            f"目前接單組合只有 {protector_count} 位。"
        )

    base_rate = int(getattr(rule, "price", 0) or 0)
    if base_rate <= 0:
        raise ValueError("這個玩法目前沒有有效的小時價格。")

    if bool(getattr(rule, "price_multiply_player_count", False)):
        return base_rate * staff_count
    return base_rate


def _write_effective_rate(order_id: int, rate: int) -> None:
    db = SessionLocal()
    try:
        now = utc_iso()
        db.execute(
            text(
                """
                UPDATE vip_timer_sessions
                SET current_hourly_rate = :rate,
                    updated_at = :now
                WHERE order_id = :order_id
                """
            ),
            {"rate": int(rate), "now": now, "order_id": int(order_id)},
        )
        db.execute(
            text(
                """
                UPDATE vip_timer_segments
                SET hourly_rate = :rate,
                    updated_at = :now
                WHERE id = (
                    SELECT id
                    FROM vip_timer_segments
                    WHERE order_id = :order_id
                      AND ended_at IS NULL
                    ORDER BY seq DESC
                    LIMIT 1
                )
                """
            ),
            {"rate": int(rate), "now": now, "order_id": int(order_id)},
        )
        db.commit()
    finally:
        db.close()


def install_vip_timer_runtime_guard(*, bot_instance, guild_id: int) -> None:
    """Make timer pricing and mode switches follow the accepted staff roster.

    Some hourly products are priced per person. The timer's hourly snapshot must
    therefore use the already accepted staff count instead of blindly persisting
    the one-person catalog price. Switching also re-validates the same staff
    against the target product's staff-count and Discord role requirements.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from services import vip_timer_runtime as runtime

    original_panel = runtime.ensure_vip_timer_panel
    original_start = runtime.start_timer
    original_switch = runtime.switch_rule

    async def guarded_panel(*args, **kwargs):
        state = kwargs.get("state")
        data = kwargs.get("data") or {}
        order_id = int(
            getattr(state, "order_id", 0)
            or data.get("web_order_id")
            or 0
        )
        if order_id > 0:
            session = runtime.get_session(order_id) or {}
            staff_ids = [
                str(getattr(claim, "staff_discord_id", "") or "").strip()
                for claim in (getattr(state, "claims", ()) or ())
            ]
            rate = _rule_rate_and_validate(
                bot_instance=bot_instance,
                guild_id=guild_id,
                rule_key=str(session.get("current_rule_key") or ""),
                staff_ids=staff_ids,
            )
            _write_effective_rate(order_id, rate)
        return await original_panel(*args, **kwargs)

    def guarded_start(order_id: int, actor_id: Any, staff_ids=None):
        session = runtime.get_session(int(order_id)) or {}
        rate = _rule_rate_and_validate(
            bot_instance=bot_instance,
            guild_id=guild_id,
            rule_key=str(session.get("current_rule_key") or ""),
            staff_ids=staff_ids,
        )
        _write_effective_rate(int(order_id), rate)
        return original_start(order_id, actor_id, staff_ids)

    def guarded_switch(order_id: int, new_rule_key: str, actor_id: Any, staff_ids=None):
        rate = _rule_rate_and_validate(
            bot_instance=bot_instance,
            guild_id=guild_id,
            rule_key=str(new_rule_key),
            staff_ids=staff_ids,
        )
        result = original_switch(order_id, new_rule_key, actor_id, staff_ids)
        _write_effective_rate(int(order_id), rate)
        return runtime.get_session(int(order_id)) or result

    runtime.ensure_vip_timer_panel = guarded_panel
    runtime.start_timer = guarded_start
    runtime.switch_rule = guarded_switch


__all__ = ["install_vip_timer_runtime_guard"]
