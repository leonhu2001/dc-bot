import json
import shutil
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, MutableMapping

_DB_FILE: Path | None = None
_INIT_DATABASE: Callable[[], None] | None = None
_BACKUP_DIR: Path | None = None
_BACKUP_KEEP_DAYS: int = 30

_ORDER_SELECTIONS: MutableMapping[int, dict] | None = None
_ORDER_CLAIMS: MutableMapping[int, dict] | None = None
_CUSTOMER_REWARDS: MutableMapping[int, dict] | None = None
_ORDER_COUNTERS: MutableMapping[str, int] | None = None
_ORDER_ID_PREFIX: str = "MO"
_SAVE_BOT_DATA: Callable[[], None] | None = None


def configure_data_access(
    order_selections: MutableMapping[int, dict],
    order_claims: MutableMapping[int, dict],
    customer_rewards: MutableMapping[int, dict],
    order_counters: MutableMapping[str, int],
    save_bot_data_func: Callable[[], None],
    *,
    order_id_prefix: str = "MO",
) -> None:
    """設定記憶體資料入口，供 remember_*、serialize helpers 與訂單編號 helper 使用。

    這裡只保存 reference，不複製資料；因此 bot.py 原本的全域 dict 仍是唯一資料來源。
    """
    global _ORDER_SELECTIONS, _ORDER_CLAIMS, _CUSTOMER_REWARDS, _ORDER_COUNTERS, _SAVE_BOT_DATA, _ORDER_ID_PREFIX
    _ORDER_SELECTIONS = order_selections
    _ORDER_CLAIMS = order_claims
    _CUSTOMER_REWARDS = customer_rewards
    _ORDER_COUNTERS = order_counters
    _SAVE_BOT_DATA = save_bot_data_func
    _ORDER_ID_PREFIX = str(order_id_prefix or "MO")

def _require_data_access() -> tuple[MutableMapping[int, dict], MutableMapping[int, dict], Callable[[], None]]:
    if _ORDER_SELECTIONS is None or _ORDER_CLAIMS is None or _SAVE_BOT_DATA is None:
        raise RuntimeError("database module 尚未設定資料入口，請先呼叫 configure_data_access()")
    return _ORDER_SELECTIONS, _ORDER_CLAIMS, _SAVE_BOT_DATA


def _require_order_counter_access() -> tuple[MutableMapping[str, int], Callable[[], None]]:
    if _ORDER_COUNTERS is None or _SAVE_BOT_DATA is None:
        raise RuntimeError("database module 尚未設定訂單編號資料入口，請先呼叫 configure_data_access()")
    return _ORDER_COUNTERS, _SAVE_BOT_DATA


def _require_all_data_access() -> tuple[
    MutableMapping[int, dict],
    MutableMapping[int, dict],
    MutableMapping[int, dict],
    MutableMapping[str, int],
]:
    if (
        _ORDER_SELECTIONS is None
        or _ORDER_CLAIMS is None
        or _CUSTOMER_REWARDS is None
        or _ORDER_COUNTERS is None
    ):
        raise RuntimeError("database module 尚未設定完整資料入口，請先呼叫 configure_data_access()")
    return _ORDER_SELECTIONS, _ORDER_CLAIMS, _CUSTOMER_REWARDS, _ORDER_COUNTERS


def _to_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _serialize_orders() -> dict:
    order_selections, _, _, _ = _require_all_data_access()
    return {
        str(channel_id): data
        for channel_id, data in order_selections.items()
    }


def _serialize_claims() -> dict:
    _, order_claims, _, _ = _require_all_data_access()
    result = {}

    for message_id, data in order_claims.items():
        result[str(message_id)] = {
            "companion": sorted(list(data.get("companion", set()))),
            "booster": sorted(list(data.get("booster", set()))),
            "locked": bool(data.get("locked", False)),
            "customer_id": data.get("customer_id"),
            "category_label": data.get("category_label"),
            "item": data.get("item"),
            "quantity": _to_int(data.get("quantity"), 1) or 1,
            "payment_method": data.get("payment_method"),
            "source_channel_id": data.get("source_channel_id"),
            "companion_preference": data.get("companion_preference"),
            "dispatch_channel_id": data.get("dispatch_channel_id"),
            "status": data.get("status", "active"),
            "stored_at": data.get("stored_at"),
            "stored_by": data.get("stored_by"),
            "stored_reason": data.get("stored_reason"),
            "stored_expected_time": data.get("stored_expected_time"),
            "stored_note": data.get("stored_note"),
        }

    return result


def _serialize_customer_rewards() -> dict:
    _, _, customer_rewards, _ = _require_all_data_access()
    return {
        str(user_id): data
        for user_id, data in customer_rewards.items()
    }


def _serialize_order_counters() -> dict:
    _, _, _, order_counters = _require_all_data_access()
    return {str(day): int(count) for day, count in order_counters.items()}


def _json_default(value: Any):
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def remember_order_data(channel_id: int, data: dict) -> None:
    """保存單筆訂單暫存資料並同步到資料庫。"""
    order_selections, _, save_bot_data = _require_data_access()
    order_selections[int(channel_id)] = data
    save_bot_data()


def remember_claim_data(message_id: int, data: dict) -> None:
    """保存派單接單資料並同步到資料庫。"""
    _, order_claims, save_bot_data = _require_data_access()
    order_claims[int(message_id)] = data
    save_bot_data()


def generate_order_receipt_id() -> str:
    """自動產生訂單編號，例如 MO20260519001。"""
    order_counters, save_bot_data = _require_order_counter_access()
    taipei_tz = timezone(timedelta(hours=8))
    day_key = datetime.now(taipei_tz).strftime("%Y%m%d")
    next_number = int(order_counters.get(day_key, 0) or 0) + 1
    order_counters[day_key] = next_number
    save_bot_data()
    return f"{_ORDER_ID_PREFIX}{day_key}{next_number:03d}"



def configure_database(
    db_file: str | Path,
    init_database_func: Callable[[], None] | None = None,
    *,
    backup_dir: str | Path | None = None,
    backup_keep_days: int = 30,
) -> None:
    """設定資料庫模組使用的 DB 路徑、初始化函式與備份資料夾。"""
    global _DB_FILE, _INIT_DATABASE, _BACKUP_DIR, _BACKUP_KEEP_DAYS
    _DB_FILE = Path(db_file)
    _INIT_DATABASE = init_database_func
    _BACKUP_DIR = Path(backup_dir) if backup_dir is not None else _DB_FILE.parent / "backups"
    _BACKUP_KEEP_DAYS = int(backup_keep_days or 30)


def _require_db_file() -> Path:
    if _DB_FILE is None:
        raise RuntimeError("database module 尚未設定 DB_FILE，請先呼叫 configure_database()")
    return _DB_FILE


def _require_backup_dir() -> Path:
    if _BACKUP_DIR is None:
        db_file = _require_db_file()
        return db_file.parent / "backups"
    return _BACKUP_DIR


def _ensure_database_ready() -> None:
    if _INIT_DATABASE is not None:
        _INIT_DATABASE()


def _db_table_exists(cur: sqlite3.Cursor, table_name: str) -> bool:
    row = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _db_columns(cur: sqlite3.Cursor, table_name: str) -> set[str]:
    try:
        return {row[1] for row in cur.execute(f"PRAGMA table_info({table_name})").fetchall()}
    except sqlite3.Error:
        return set()


def _db_add_column_if_missing(cur: sqlite3.Cursor, table_name: str, column_name: str, column_type: str) -> None:
    cols = _db_columns(cur, table_name)
    if column_name not in cols:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def _json_load_maybe(value, default):
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def delete_order_row_from_db(channel_id: int) -> None:
    """明確刪除單筆 orders；避免 save_bot_data 不整表重寫後留下取消單殘影。"""
    _ensure_database_ready()
    try:
        with sqlite3.connect(_require_db_file()) as conn:
            conn.execute("DELETE FROM orders WHERE channel_id=?", (int(channel_id),))
            conn.commit()
    except sqlite3.Error as e:
        print(f"刪除 orders 資料失敗：{e}")


def delete_claim_row_from_db(message_id: int | None = None, source_channel_id: int | None = None) -> None:
    """明確刪除 claims。可用派單訊息 ID 或來源票口 ID。

    兼容舊版 JSON blob schema 的 message_id 欄位，以及新版 relational schema 的
    dispatch_message_id 欄位，避免刪除存單 / 取消訂單時因缺欄位噴錯。
    """
    _ensure_database_ready()
    try:
        with sqlite3.connect(_require_db_file()) as conn:
            cur = conn.cursor()
            cols = _db_columns(cur, "claims")
            if message_id is not None:
                if "dispatch_message_id" in cols:
                    conn.execute("DELETE FROM claims WHERE dispatch_message_id=?", (int(message_id),))
                if "message_id" in cols:
                    conn.execute("DELETE FROM claims WHERE message_id=?", (int(message_id),))
            if source_channel_id is not None and "source_channel_id" in cols:
                conn.execute("DELETE FROM claims WHERE source_channel_id=?", (int(source_channel_id),))
            conn.commit()
    except sqlite3.Error as e:
        print(f"刪除 claims 資料失敗：{e}")


def run_daily_backup_once() -> str | None:
    """若今天還沒有備份，複製 bot.db 到 backups/，並清掉過舊備份。"""
    db_file = _require_db_file()
    if not db_file.exists():
        return None

    backup_dir = _require_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)

    taipei_tz = timezone(timedelta(hours=8))
    now = datetime.now(taipei_tz)
    day_key = now.strftime("%Y%m%d")
    backup_path = backup_dir / f"bot_{day_key}.db"

    if not backup_path.exists():
        shutil.copy2(db_file, backup_path)

    cutoff = now - timedelta(days=_BACKUP_KEEP_DAYS)
    for old_file in backup_dir.glob("bot_*.db"):
        try:
            date_part = old_file.stem.replace("bot_", "")
            file_date = datetime.strptime(date_part, "%Y%m%d").replace(tzinfo=taipei_tz)
        except ValueError:
            continue

        if file_date < cutoff:
            try:
                old_file.unlink()
            except OSError:
                pass

    return str(backup_path)
