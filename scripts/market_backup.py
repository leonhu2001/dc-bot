from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url


APP_DIR = Path(os.getenv("APP_DIR", "/opt/dc-bot"))
ENV_FILE = Path(os.getenv("MARKET_ENV_FILE", str(APP_DIR / "web" / ".env")))
DEFAULT_BACKUP_DIR = APP_DIR / "_archive" / "market_db"


def _positive_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _cleanup_old_backups(directory: Path, *, retention_days: int, now: datetime) -> int:
    cutoff = now - timedelta(days=retention_days)
    removed = 0
    for path in directory.glob("market_*.dump"):
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if modified < cutoff:
            try:
                path.unlink()
            except OSError:
                continue
            removed += 1
    return removed


def main() -> int:
    load_dotenv(ENV_FILE, override=False)
    raw_url = str(os.getenv("MARKET_DATABASE_URL") or "").strip()
    if not raw_url:
        print("ERROR: MARKET_DATABASE_URL is not configured", file=sys.stderr)
        return 2

    try:
        url = make_url(raw_url)
    except Exception:
        print("ERROR: MARKET_DATABASE_URL is invalid", file=sys.stderr)
        return 2

    if not url.drivername.startswith("postgresql") or not url.database:
        print("ERROR: market backup only supports PostgreSQL", file=sys.stderr)
        return 2

    pg_dump = shutil.which("pg_dump")
    pg_restore = shutil.which("pg_restore")
    if not pg_dump or not pg_restore:
        print("ERROR: pg_dump and pg_restore are required", file=sys.stderr)
        return 2

    backup_dir = Path(os.getenv("MARKET_BACKUP_DIR", str(DEFAULT_BACKUP_DIR)))
    backup_dir.mkdir(parents=True, exist_ok=True)
    retention_days = _positive_int("MARKET_BACKUP_RETENTION_DAYS", 14)

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    final_path = backup_dir / f"market_{stamp}.dump"
    temp_path = backup_dir / f".market_{stamp}.dump.tmp"

    env = os.environ.copy()
    env.update(
        {
            "PGHOST": str(url.host or "127.0.0.1"),
            "PGPORT": str(url.port or 5432),
            "PGUSER": str(url.username or ""),
            "PGDATABASE": str(url.database),
        }
    )
    if url.password:
        env["PGPASSWORD"] = str(url.password)

    dump_command = [
        pg_dump,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--file",
        str(temp_path),
    ]

    try:
        subprocess.run(
            dump_command,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )
        if not temp_path.exists() or temp_path.stat().st_size <= 0:
            raise RuntimeError("pg_dump produced an empty backup")
        subprocess.run(
            [pg_restore, "--list", str(temp_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )
        temp_path.replace(final_path)
    except subprocess.CalledProcessError:
        temp_path.unlink(missing_ok=True)
        print("ERROR: market backup command failed", file=sys.stderr)
        return 1
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        print(f"ERROR: market backup failed: {type(exc).__name__}", file=sys.stderr)
        return 1

    removed = _cleanup_old_backups(
        backup_dir,
        retention_days=retention_days,
        now=now,
    )
    print(
        "PASS: market backup created and verified",
        f"file={final_path.name}",
        f"bytes={final_path.stat().st_size}",
        f"retention_days={retention_days}",
        f"expired_removed={removed}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
