from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo


PAUSE_WARNING_SECONDS = 60 * 60
PAUSE_MAX_SECONDS = 2 * 60 * 60
_TAIPEI = ZoneInfo("Asia/Taipei")
_INSTALLED = False


def pause_state(session: dict | None, *, now=None) -> dict[str, Any]:
    """Return the current pause policy state for one timer session.

    A pause is intended for a short break, not for carrying one post-pay order
    across a long gap. Resume is therefore blocked after two hours or after the
    Taiwan calendar day changes, whichever comes first.
    """

    from services import vip_timer as timer

    session = dict(session or {})
    if str(session.get("status") or "") != "paused":
        return {
            "paused": False,
            "age_seconds": 0,
            "warning": False,
            "expired": False,
            "crossed_day": False,
            "reason": "not_paused",
            "remaining_seconds": PAUSE_MAX_SECONDS,
        }

    paused_at = timer.parse_dt(session.get("paused_at"))
    current = now or timer.utc_now()
    if paused_at is None:
        # Missing pause timestamps should fail closed instead of allowing an
        # indefinitely resumable legacy/corrupt session.
        return {
            "paused": True,
            "age_seconds": PAUSE_MAX_SECONDS,
            "warning": True,
            "expired": True,
            "crossed_day": False,
            "reason": "missing_timestamp",
            "remaining_seconds": 0,
        }

    age_seconds = max(0, int((current - paused_at).total_seconds()))
    crossed_day = paused_at.astimezone(_TAIPEI).date() != current.astimezone(_TAIPEI).date()
    expired = crossed_day or age_seconds >= PAUSE_MAX_SECONDS
    warning = expired or age_seconds >= PAUSE_WARNING_SECONDS
    if crossed_day:
        reason = "cross_day"
    elif age_seconds >= PAUSE_MAX_SECONDS:
        reason = "timeout"
    else:
        reason = "active"

    return {
        "paused": True,
        "age_seconds": age_seconds,
        "warning": warning,
        "expired": expired,
        "crossed_day": crossed_day,
        "reason": reason,
        "remaining_seconds": max(0, PAUSE_MAX_SECONDS - age_seconds),
    }


def assert_resume_allowed(order_id: int) -> dict[str, Any]:
    from services import vip_timer as timer

    session = timer.get_session(int(order_id)) or {}
    state = pause_state(session)
    if not state.get("expired"):
        return state

    reason = str(state.get("reason") or "")
    if reason == "cross_day":
        raise ValueError(
            "這張 VIP 自由計時已跨日暫停，不能再繼續計時。請由老闆與陪玩雙方確認結束並完成結算；如有特殊狀況請聯繫客服處理。"
        )
    if reason == "missing_timestamp":
        raise ValueError(
            "這張 VIP 自由計時的暫停時間紀錄異常，已禁止直接繼續。請聯繫客服確認後結束／修正。"
        )
    raise ValueError(
        "這張 VIP 自由計時已暫停超過 2 小時，不能再繼續計時。請由老闆與陪玩雙方確認結束並完成結算；如有特殊狀況請聯繫客服處理。"
    )


def _duration_text(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    minutes = seconds // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} 小時 {minutes} 分鐘"
    return f"{minutes} 分鐘"


def install_vip_timer_pause_expiry() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer_runtime as runtime

    original_resume = runtime.resume_timer
    original_embed = runtime.build_vip_timer_embed

    def guarded_resume(order_id: int, actor_id: Any):
        assert_resume_allowed(int(order_id))
        return original_resume(int(order_id), actor_id)

    def build_embed(order_id: int):
        embed = original_embed(int(order_id))
        session = runtime.get_session(int(order_id)) or {}
        state = pause_state(session)
        if not state.get("paused"):
            return embed

        if state.get("expired"):
            if state.get("reason") == "cross_day":
                detail = "本次暫停已跨日，依規則不可再繼續這張計時單。"
            elif state.get("reason") == "missing_timestamp":
                detail = "暫停時間紀錄異常，已禁止直接繼續。"
            else:
                detail = "本次暫停已超過 2 小時，已鎖定繼續計時。"
            value = (
                f"🔒 {detail}\n"
                "請由老闆與陪玩雙方使用「結束計時」完成結算；特殊狀況請聯繫客服。"
            )
        elif state.get("warning"):
            value = (
                f"⚠️ 已暫停約 {_duration_text(int(state.get('age_seconds') or 0))}。\n"
                "暫停最長 2 小時且不可跨日；超過後將鎖定「繼續」，必須結束結算。"
            )
        else:
            value = (
                "暫停僅供短暫休息，最長 2 小時且不可跨日。\n"
                "超過限制後不能再繼續這張計時單，需完成結束結算。"
            )
        embed.add_field(name="⏸️ 暫停期限", value=value, inline=False)
        return embed

    runtime.resume_timer = guarded_resume
    runtime.build_vip_timer_embed = build_embed
    _INSTALLED = True


__all__ = [
    "PAUSE_MAX_SECONDS",
    "PAUSE_WARNING_SECONDS",
    "assert_resume_allowed",
    "install_vip_timer_pause_expiry",
    "pause_state",
]
