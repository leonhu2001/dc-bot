from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_ONLINE_TIMEOUT_SECONDS = 90
MIN_TOUCH_INTERVAL_SECONDS = 20
_ENSURED_DB_PATHS: set[str] = set()


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[1] / "web_dashboard.db"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def ensure_dispatch_presence_table(
    db_file: str | Path | None = None,
) -> None:
    path = _db_path(db_file)
    cache_key = str(path.resolve())
    if cache_key in _ENSURED_DB_PATHS:
        return

    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS dispatch_presence (
                worker_discord_id TEXT PRIMARY KEY,
                display_name TEXT,
                last_seen_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_dispatch_presence_last_seen
                ON dispatch_presence(last_seen_at);

            CREATE TABLE IF NOT EXISTS dispatch_support_presence (
                staff_discord_id TEXT PRIMARY KEY,
                display_name TEXT,
                last_seen_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_dispatch_support_presence_last_seen
                ON dispatch_support_presence(last_seen_at);
            """
        )
        conn.commit()

    _ENSURED_DB_PATHS.add(cache_key)


def touch_dispatch_presence(
    worker_discord_id: str | int,
    *,
    display_name: str | None = None,
    db_file: str | Path | None = None,
    now: datetime | None = None,
) -> None:
    worker_id = str(worker_discord_id or "").strip()
    if not worker_id:
        return

    ensure_dispatch_presence_table(db_file)
    current = now or _now_utc()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    seen_at = _iso_utc(current)

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        existing = conn.execute(
            """
            SELECT last_seen_at
            FROM dispatch_presence
            WHERE worker_discord_id = ?
            LIMIT 1
            """,
            (worker_id,),
        ).fetchone()

        if existing is not None:
            try:
                previous = datetime.fromisoformat(
                    str(existing[0] or "").replace("Z", "+00:00")
                )
            except ValueError:
                previous = None

            if previous is not None:
                if previous.tzinfo is None:
                    previous = previous.replace(tzinfo=timezone.utc)
                elapsed = (
                    current - previous.astimezone(timezone.utc)
                ).total_seconds()
                if elapsed < MIN_TOUCH_INTERVAL_SECONDS:
                    return

        conn.execute(
            """
            INSERT INTO dispatch_presence (
                worker_discord_id,
                display_name,
                last_seen_at
            )
            VALUES (?, ?, ?)
            ON CONFLICT(worker_discord_id) DO UPDATE SET
                display_name = excluded.display_name,
                last_seen_at = excluded.last_seen_at
            """,
            (
                worker_id,
                str(display_name or "").strip() or None,
                seen_at,
            ),
        )
        conn.commit()


def get_online_dispatch_worker_ids(
    *,
    timeout_seconds: int = DEFAULT_ONLINE_TIMEOUT_SECONDS,
    candidate_ids: Iterable[str | int] | None = None,
    db_file: str | Path | None = None,
    now: datetime | None = None,
) -> list[str]:
    path = _db_path(db_file)
    if not path.exists():
        return []

    ensure_dispatch_presence_table(db_file)

    current = now or _now_utc()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    cutoff = current.astimezone(timezone.utc) - timedelta(
        seconds=max(1, int(timeout_seconds or DEFAULT_ONLINE_TIMEOUT_SECONDS))
    )

    requested = None
    if candidate_ids is not None:
        requested = {
            str(item)
            for item in candidate_ids
            if str(item).strip()
        }
        if not requested:
            return []

    with sqlite3.connect(path, timeout=15) as conn:
        rows = conn.execute(
            """
            SELECT worker_discord_id, last_seen_at
            FROM dispatch_presence
            """
        ).fetchall()

    result: list[str] = []
    for worker_id, last_seen_text in rows:
        worker_key = str(worker_id)
        if requested is not None and worker_key not in requested:
            continue

        try:
            last_seen = datetime.fromisoformat(
                str(last_seen_text or "").replace("Z", "+00:00")
            )
        except ValueError:
            continue

        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)

        if last_seen.astimezone(timezone.utc) >= cutoff:
            result.append(worker_key)

    return result


def count_online_dispatch_workers(
    *,
    timeout_seconds: int = DEFAULT_ONLINE_TIMEOUT_SECONDS,
    candidate_ids: Iterable[str | int] | None = None,
    db_file: str | Path | None = None,
    now: datetime | None = None,
) -> int:
    return len(
        get_online_dispatch_worker_ids(
            timeout_seconds=timeout_seconds,
            candidate_ids=candidate_ids,
            db_file=db_file,
            now=now,
        )
    )


def touch_dispatch_support_presence(
    staff_discord_id: str | int,
    *,
    display_name: str | None = None,
    db_file: str | Path | None = None,
    now: datetime | None = None,
) -> None:
    staff_id = str(staff_discord_id or "").strip()
    if not staff_id:
        return

    ensure_dispatch_presence_table(db_file)
    current = now or _now_utc()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    seen_at = _iso_utc(current)

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        existing = conn.execute(
            """
            SELECT last_seen_at
            FROM dispatch_support_presence
            WHERE staff_discord_id = ?
            LIMIT 1
            """,
            (staff_id,),
        ).fetchone()

        if existing is not None:
            try:
                previous = datetime.fromisoformat(
                    str(existing[0] or "").replace("Z", "+00:00")
                )
            except ValueError:
                previous = None

            if previous is not None:
                if previous.tzinfo is None:
                    previous = previous.replace(tzinfo=timezone.utc)
                elapsed = (
                    current - previous.astimezone(timezone.utc)
                ).total_seconds()
                if elapsed < MIN_TOUCH_INTERVAL_SECONDS:
                    return

        conn.execute(
            """
            INSERT INTO dispatch_support_presence (
                staff_discord_id,
                display_name,
                last_seen_at
            )
            VALUES (?, ?, ?)
            ON CONFLICT(staff_discord_id) DO UPDATE SET
                display_name = excluded.display_name,
                last_seen_at = excluded.last_seen_at
            """,
            (
                staff_id,
                str(display_name or "").strip() or None,
                seen_at,
            ),
        )
        conn.commit()


def get_online_dispatch_support_ids(
    *,
    timeout_seconds: int = DEFAULT_ONLINE_TIMEOUT_SECONDS,
    db_file: str | Path | None = None,
    now: datetime | None = None,
) -> list[str]:
    path = _db_path(db_file)
    if not path.exists():
        return []

    ensure_dispatch_presence_table(db_file)

    current = now or _now_utc()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    cutoff = current.astimezone(timezone.utc) - timedelta(
        seconds=max(1, int(timeout_seconds or DEFAULT_ONLINE_TIMEOUT_SECONDS))
    )

    with sqlite3.connect(path, timeout=15) as conn:
        rows = conn.execute(
            """
            SELECT staff_discord_id, last_seen_at
            FROM dispatch_support_presence
            """
        ).fetchall()

    result: list[str] = []
    for staff_id, last_seen_text in rows:
        try:
            last_seen = datetime.fromisoformat(
                str(last_seen_text or "").replace("Z", "+00:00")
            )
        except ValueError:
            continue

        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)

        if last_seen.astimezone(timezone.utc) >= cutoff:
            result.append(str(staff_id))

    return result


def has_online_dispatch_support(
    *,
    timeout_seconds: int = DEFAULT_ONLINE_TIMEOUT_SECONDS,
    db_file: str | Path | None = None,
    now: datetime | None = None,
) -> bool:
    return bool(
        get_online_dispatch_support_ids(
            timeout_seconds=timeout_seconds,
            db_file=db_file,
            now=now,
        )
    )
