import json
import shutil
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable

_DB_FILE: Path | None = None
_INIT_DATABASE: Callable[[], None] | None = None
_BACKUP_DIR: Path | None = None
_BACKUP_KEEP_DAYS: int = 30


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
