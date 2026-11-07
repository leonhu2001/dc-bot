from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Shared by the isolated market worker and the web dashboard.
DEFAULT_STATE_FILE = Path(__file__).resolve().parents[2] / "data" / "market_poll_state.json"


def _state_file() -> Path:
    value = str(os.getenv("MARKET_POLL_STATE_FILE") or "").strip()
    return Path(value) if value else DEFAULT_STATE_FILE


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def record_market_poll(
    *,
    game_key: str,
    status: str,
    provider: str,
    item_count: int = 0,
    inserted_price_count: int = 0,
    checked_at: datetime | None = None,
) -> None:
    """Persist fetch outcome even when a source timestamp has not changed.

    Never persist exception messages, credentials, or user data.
    A failed telemetry write must not stop the market worker.
    """
    at = _utc(checked_at or datetime.now(timezone.utc))
    payload = {
        "checked_at": at.isoformat(),
        "game_key": str(game_key)[:64],
        "provider": str(provider)[:128],
        "status": str(status)[:64],
        "item_count": int(item_count),
        "inserted_price_count": int(inserted_price_count),
    }
    path = _state_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)
    except OSError:
        return


def load_market_poll(*, game_key: str = "delta_force") -> dict[str, Any] | None:
    try:
        payload = json.loads(_state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    if not isinstance(payload, dict) or payload.get("game_key") != game_key:
        return None
    if str(payload.get("status") or "") not in {
        "stored", "duplicate", "source_unavailable", "error"
    }:
        return None
    try:
        checked_at = datetime.fromisoformat(str(payload["checked_at"]))
    except (KeyError, ValueError, TypeError):
        return None
    return {
        "checked_at": _utc(checked_at),
        "status": str(payload["status"]),
        "provider": str(payload.get("provider") or ""),
        "item_count": int(payload.get("item_count") or 0),
        "inserted_price_count": int(payload.get("inserted_price_count") or 0),
    }


def market_delay_diagnosis(
    *,
    source_updated_at: datetime,
    now: datetime | None = None,
    poll: dict[str, Any] | None = None,
    expected_poll_seconds: int | None = None,
) -> dict[str, Any]:
    """Separate stale upstream data from a stopped or failing worker."""
    current = _utc(now or datetime.now(timezone.utc))
    source_age = max(0, int((current - _utc(source_updated_at)).total_seconds()))
    expected = max(180, int(expected_poll_seconds or os.getenv("MARKET_POLL_SECONDS", "900")))
    if poll is None:
        return {
            "reason": "no_poll_record",
            "message": "尚無最近一次抓取紀錄，無法確認外部來源是否更新；請檢查行情抓取服務。",
            "last_poll_at": None,
            "poll_age_seconds": None,
            "source_age_seconds": source_age,
        }
    last_poll_at = _utc(poll["checked_at"])
    poll_age = max(0, int((current - last_poll_at).total_seconds()))
    result = str(poll["status"])
    if poll_age > max(expected * 2 + 120, 1200):
        reason = "worker_not_polling"
        message = "行情抓取服務沒有在預期時間內回報；請檢查 dc-bot-market 服務。"
    elif result == "source_unavailable":
        reason = "upstream_fetch_failed"
        message = "最近一次抓取外部行情失敗；已保留最後成功價格，停止舊資料通知。"
    elif result == "error":
        reason = "worker_processing_error"
        message = "抓取或儲存行情時發生錯誤；請檢查 dc-bot-market 服務日誌。"
    elif result == "duplicate":
        reason = "source_timestamp_unchanged"
        message = "最近抓取成功，但來源提供的行情時間沒有前進；可能是上游快照或時間欄位未更新。"
    else:
        reason = "stored_snapshot_stale"
        message = "最近一批行情已寫入，但來源時間仍過舊；請檢查來源時間欄位。"
    return {
        "reason": reason,
        "message": message,
        "last_poll_at": last_poll_at,
        "poll_age_seconds": poll_age,
        "source_age_seconds": source_age,
    }
