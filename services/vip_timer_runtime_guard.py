from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, text

from services.order_rules import (
    ORDER_RULES,
    PROTECTOR_ROLES,
    ROLE_IDS,
    get_allowed_role_ids,
    get_required_game_role_ids,
    role_ids_match_requirements,
)
from services.vip_timer import SessionLocal, ensure_vip_timer_tables, strip_vip_timer_rule_key, utc_iso


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


def _validated_pricing_snapshot(
    *,
    bot_instance,
    guild_id: int,
    rule_key: str,
    staff_ids,
) -> dict:
    from services import vip_timer_catalog_guard as catalog_guard

    key = strip_vip_timer_rule_key(rule_key)
    rule = ORDER_RULES.get(key)
    if rule is None or str(getattr(rule, "pricing_type", "")) != "hourly":
        raise ValueError("VIP 自由計時只能切換到小時計價方案。")
    if not catalog_guard.is_public_timer_rule(key):
        raise ValueError("這個玩法目前不能用於 VIP 自由計時，請改選其他玩法。")

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
        required_staff_count = staff_count
    else:
        required_staff_count = int(required_mode or 1)
        if staff_count != required_staff_count:
            raise ValueError(
                f"這個玩法需要 {required_staff_count} 位接單人員，"
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

    effective_rate = base_rate * staff_count if bool(getattr(rule, "price_multiply_player_count", False)) else base_rate
    return {
        "rule_key": key,
        "hourly_rate": int(effective_rate),
        "player_count": int(staff_count),
        "required_staff_count": int(required_staff_count),
        "staff_ids": staff,
    }


def _rule_rate_and_validate(
    *,
    bot_instance,
    guild_id: int,
    rule_key: str,
    staff_ids,
) -> int:
    """Compatibility helper used by focused tests and callers that only need the rate."""
    return int(
        _validated_pricing_snapshot(
            bot_instance=bot_instance,
            guild_id=guild_id,
            rule_key=rule_key,
            staff_ids=staff_ids,
        )["hourly_rate"]
    )


def _ensure_segment_snapshot_columns() -> None:
    db = SessionLocal()
    try:
        ensure_vip_timer_tables(db)
        bind = db.get_bind()
        existing = {str(column.get("name") or "") for column in inspect(bind).get_columns("vip_timer_segments")}
        if "player_count" not in existing:
            db.execute(text("ALTER TABLE vip_timer_segments ADD COLUMN player_count INTEGER"))
        if "required_staff_count" not in existing:
            db.execute(text("ALTER TABLE vip_timer_segments ADD COLUMN required_staff_count INTEGER"))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _write_effective_snapshot(order_id: int, snapshot: dict, *, update_segment: bool) -> None:
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
            {
                "rate": int(snapshot.get("hourly_rate") or 0),
                "now": now,
                "order_id": int(order_id),
            },
        )
        if update_segment:
            db.execute(
                text(
                    """
                    UPDATE vip_timer_segments
                    SET hourly_rate = :rate,
                        player_count = :player_count,
                        required_staff_count = :required_staff_count,
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
                {
                    "rate": int(snapshot.get("hourly_rate") or 0),
                    "player_count": int(snapshot.get("player_count") or 0),
                    "required_staff_count": int(snapshot.get("required_staff_count") or 0),
                    "now": now,
                    "order_id": int(order_id),
                },
            )
        db.commit()
    finally:
        db.close()


def install_vip_timer_runtime_guard(*, bot_instance, guild_id: int) -> None:
    """Validate the accepted roster and lock each timer segment at action time.

    Price-multiplied products use the actual accepted roster count. The first
    segment is deliberately not priced when the ticket panel is created; its
    authoritative price is resolved when somebody presses Start. Every new
    segment also stores the roster size and required staff count used for that
    price snapshot.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    _ensure_segment_snapshot_columns()

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
            # Validate eligibility when the panel opens, but do not persist the
            # price yet. Start is the authoritative first price-lock moment.
            _validated_pricing_snapshot(
                bot_instance=bot_instance,
                guild_id=guild_id,
                rule_key=str(session.get("current_rule_key") or ""),
                staff_ids=staff_ids,
            )
        return await original_panel(*args, **kwargs)

    def guarded_start(order_id: int, actor_id: Any, staff_ids=None):
        snapshot = _validated_pricing_snapshot(
            bot_instance=bot_instance,
            guild_id=guild_id,
            rule_key=str((runtime.get_session(int(order_id)) or {}).get("current_rule_key") or ""),
            staff_ids=staff_ids,
        )
        # original_start snapshots session.current_hourly_rate into the new
        # segment, so update the session immediately before creating it.
        _write_effective_snapshot(int(order_id), snapshot, update_segment=False)
        result = original_start(order_id, actor_id, staff_ids)
        _write_effective_snapshot(int(order_id), snapshot, update_segment=True)
        return runtime.get_session(int(order_id)) or result

    def guarded_switch(order_id: int, new_rule_key: str, actor_id: Any, staff_ids=None):
        snapshot = _validated_pricing_snapshot(
            bot_instance=bot_instance,
            guild_id=guild_id,
            rule_key=str(new_rule_key),
            staff_ids=staff_ids,
        )
        result = original_switch(order_id, new_rule_key, actor_id, staff_ids)
        _write_effective_snapshot(int(order_id), snapshot, update_segment=True)
        return runtime.get_session(int(order_id)) or result

    runtime.ensure_vip_timer_panel = guarded_panel
    runtime.start_timer = guarded_start
    runtime.switch_rule = guarded_switch
    _INSTALLED = True


__all__ = [
    "install_vip_timer_runtime_guard",
]
