from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

TAIPEI_TZ = timezone(timedelta(hours=8))

BOT_SERVICE_NAME = "dc-bot.service"
WEB_SERVICE_NAME = "dc-bot-dashboard.service"

WEB_DB_CHECKS = (
    (
        "payment_pending",
        "SELECT COUNT(*) FROM payment_reviews WHERE status IN ('pending_review', 'approved_pending_apply')",
    ),
    (
        "payment_apply_error",
        "SELECT COUNT(*) FROM payment_reviews WHERE status = 'apply_error'",
    ),
    (
        "sync_failed",
        "SELECT COUNT(*) FROM sync_events WHERE status = 'failed'",
    ),
    (
        "sync_backlog",
        "SELECT COUNT(*) FROM sync_events WHERE status IN ('pending', 'processing')",
    ),
    (
        "open_orders",
        """
        SELECT COUNT(*)
        FROM web_orders
        WHERE status IN (
            'active',
            'stored',
            'pending_cs_dispatch',
            'waiting_acceptance',
            'accepted_pending_pay',
            'created',
            'paid'
        )
        """,
    ),
    (
        "order_state_drift",
        """
        SELECT COUNT(*)
        FROM web_orders o
        JOIN order_acceptance_meta m
          ON m.order_id = o.id
        WHERE LOWER(TRIM(COALESCE(o.status, '')))
           != LOWER(TRIM(COALESCE(m.status, '')))
        """,
    ),
)

BOT_DB_CHECKS = (
    (
        "topup_pending",
        "SELECT COUNT(*) FROM topup_orders WHERE status = 'pending_review'",
    ),
    (
        "negative_wallets",
        "SELECT COUNT(*) FROM customer_wallets WHERE balance < 0",
    ),
    (
        "wallet_duplicate_refs",
        """
        SELECT COUNT(*)
        FROM (
            SELECT customer_discord_id, order_no, type
            FROM wallet_transactions
            WHERE order_no IS NOT NULL
              AND TRIM(order_no) <> ''
            GROUP BY customer_discord_id, order_no, type
            HAVING COUNT(*) > 1
        )
        """,
    ),
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _format_duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "-"

    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    if days:
        return f"{days} 天 {hours} 小時"
    if hours:
        return f"{hours} 小時 {minutes} 分"
    return f"{minutes} 分"


def _format_bytes(size: int | None) -> str:
    if size is None:
        return "-"

    value = float(max(0, size))
    units = ("B", "KB", "MB", "GB", "TB")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024

    return f"{int(size)} B"


def _format_timestamp(timestamp: float | None) -> str:
    if timestamp is None:
        return "-"
    return datetime.fromtimestamp(timestamp, TAIPEI_TZ).strftime("%Y/%m/%d %H:%M:%S")


def _run_command(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 3.0,
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": "",
            "error": type(exc).__name__,
        }

    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": str(completed.stdout or "").strip(),
        "error": str(completed.stderr or "").strip()[:240],
    }


def _parse_key_value_lines(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in str(value or "").splitlines():
        if "=" not in line:
            continue
        key, item = line.split("=", 1)
        result[key.strip()] = item.strip()
    return result


def inspect_service(service_name: str) -> dict[str, Any]:
    result = _run_command(
        [
            "systemctl",
            "show",
            service_name,
            "--no-page",
            "--property=ActiveState,SubState,MainPID,ActiveEnterTimestampMonotonic,NRestarts,Result",
        ],
        timeout=2.5,
    )

    if not result["ok"]:
        return {
            "name": service_name,
            "available": False,
            "ok": False,
            "status_text": "無法取得",
            "active_state": "unknown",
            "sub_state": "unknown",
            "main_pid": "-",
            "restarts": "-",
            "uptime_text": "-",
            "result": "-",
        }

    fields = _parse_key_value_lines(result["stdout"])
    active_state = fields.get("ActiveState", "unknown")
    sub_state = fields.get("SubState", "unknown")

    uptime_seconds: float | None = None
    try:
        entered_us = int(fields.get("ActiveEnterTimestampMonotonic") or 0)
        if entered_us > 0:
            uptime_seconds = max(0.0, time.monotonic() - (entered_us / 1_000_000))
    except (TypeError, ValueError):
        uptime_seconds = None

    service_ok = active_state == "active"

    return {
        "name": service_name,
        "available": True,
        "ok": service_ok,
        "status_text": "正常" if service_ok else "異常",
        "active_state": active_state,
        "sub_state": sub_state,
        "main_pid": fields.get("MainPID") or "-",
        "restarts": fields.get("NRestarts") or "0",
        "uptime_text": _format_duration(uptime_seconds),
        "result": fields.get("Result") or "-",
    }


def _read_deployment_marker(root: Path) -> dict[str, Any] | None:
    marker_path = root / "data" / "deployed_version.json"

    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None

    if not isinstance(payload, dict):
        return None

    commit = str(payload.get("commit") or "").strip()
    if not commit:
        return None

    return {
        "available": True,
        "commit": commit[:12],
        "branch": str(payload.get("branch") or "main"),
        "commit_time": str(payload.get("deployed_at") or "-"),
        "subject": str(payload.get("subject") or "-"),
        "dirty": None,
        "source": "deployment_marker",
    }


def inspect_git(root: Path | None = None) -> dict[str, Any]:
    root = root or repository_root()

    commit = _run_command(
        ["git", "rev-parse", "--short=12", "HEAD"],
        cwd=root,
        timeout=2.0,
    )
    if not commit["ok"]:
        marker = _read_deployment_marker(root)
        if marker is not None:
            return marker

        return {
            "available": False,
            "commit": "-",
            "branch": "-",
            "commit_time": "-",
            "subject": "無法取得版本資訊",
            "dirty": None,
            "source": "unavailable",
        }

    branch = _run_command(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=root,
        timeout=2.0,
    )
    log = _run_command(
        ["git", "log", "-1", "--format=%cI%x1f%s"],
        cwd=root,
        timeout=2.0,
    )
    dirty = _run_command(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        timeout=2.0,
    )

    commit_time = "-"
    subject = "-"
    if log["ok"] and log["stdout"]:
        parts = log["stdout"].split("\x1f", 1)
        commit_time = parts[0] if parts else "-"
        subject = parts[1] if len(parts) > 1 else "-"

    return {
        "available": True,
        "commit": commit["stdout"],
        "branch": branch["stdout"] if branch["ok"] else "-",
        "commit_time": commit_time,
        "subject": subject,
        "dirty": bool(dirty["stdout"]) if dirty["ok"] else None,
        "source": "git",
    }


def _query_count(conn: sqlite3.Connection, sql: str) -> int | None:
    try:
        row = conn.execute(sql).fetchone()
    except sqlite3.Error:
        return None

    if not row:
        return 0

    try:
        return int(row[0] or 0)
    except (TypeError, ValueError):
        return None


def inspect_database(
    path: Path,
    checks: Iterable[tuple[str, str]],
    *,
    label: str,
) -> dict[str, Any]:
    path = Path(path)

    snapshot: dict[str, Any] = {
        "label": label,
        "path": str(path),
        "exists": path.exists(),
        "ok": False,
        "integrity": "無法檢查",
        "size_text": "-",
        "modified_at": "-",
        "is_symlink": path.is_symlink(),
        "metrics": {},
    }

    if not path.exists():
        return snapshot

    try:
        stat_result = path.stat()
        snapshot["size_text"] = _format_bytes(stat_result.st_size)
        snapshot["modified_at"] = _format_timestamp(stat_result.st_mtime)
    except OSError:
        pass

    try:
        conn = sqlite3.connect(
            f"file:{path}?mode=ro",
            uri=True,
            timeout=2.0,
        )
    except sqlite3.Error:
        return snapshot

    try:
        quick_check = conn.execute("PRAGMA quick_check").fetchone()
        integrity = str(quick_check[0] if quick_check else "").strip().lower()
        snapshot["integrity"] = "正常" if integrity == "ok" else (integrity or "異常")
        snapshot["ok"] = integrity == "ok"

        for key, sql in checks:
            snapshot["metrics"][key] = _query_count(conn, sql)
    except sqlite3.Error:
        snapshot["ok"] = False
    finally:
        conn.close()

    return snapshot


def _recent_archive_directories(archive_dir: Path, limit: int = 80) -> list[Path]:
    if not archive_dir.is_dir():
        return []

    candidates: list[tuple[float, Path]] = []
    try:
        children = list(archive_dir.iterdir())
    except OSError:
        return []

    for child in children:
        if not child.is_dir():
            continue
        try:
            candidates.append((child.stat().st_mtime, child))
        except OSError:
            continue

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in candidates[:limit]]


def inspect_backups(root: Path | None = None) -> dict[str, Any]:
    root = root or repository_root()
    candidates: list[Path] = []

    backups_dir = root / "backups"
    if backups_dir.is_dir():
        try:
            candidates.extend(
                path
                for path in backups_dir.iterdir()
                if path.is_file() and path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
            )
        except OSError:
            pass

    archive_dir = root / "_archive"
    for directory in _recent_archive_directories(archive_dir):
        try:
            candidates.extend(
                path
                for path in directory.iterdir()
                if path.is_file() and path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}
            )
        except OSError:
            continue

    newest: dict[str, tuple[float, Path]] = {}
    for path in candidates:
        lowered = path.name.lower()
        if "web_dashboard" in lowered:
            key = "web_dashboard"
        elif "bot" in lowered:
            key = "bot"
        else:
            continue

        try:
            modified = path.stat().st_mtime
        except OSError:
            continue

        previous = newest.get(key)
        if previous is None or modified > previous[0]:
            newest[key] = (modified, path)

    now = time.time()
    result: dict[str, Any] = {}

    for key, label in (
        ("bot", "Bot 資料庫"),
        ("web_dashboard", "Web 資料庫"),
    ):
        item = newest.get(key)
        if item is None:
            result[key] = {
                "label": label,
                "found": False,
                "path": "-",
                "modified_at": "-",
                "age_text": "-",
                "fresh": False,
            }
            continue

        modified, path = item
        try:
            display_path = str(path.relative_to(root))
        except ValueError:
            display_path = str(path)

        age_seconds = max(0, now - modified)
        result[key] = {
            "label": label,
            "found": True,
            "path": display_path,
            "modified_at": _format_timestamp(modified),
            "age_text": _format_duration(age_seconds),
            "fresh": age_seconds <= 72 * 3600,
        }

    return result


def build_system_health_snapshot(root: Path | None = None) -> dict[str, Any]:
    root = root or repository_root()

    services = {
        "bot": inspect_service(BOT_SERVICE_NAME),
        "web": inspect_service(WEB_SERVICE_NAME),
    }

    databases = {
        "bot": inspect_database(
            root / "bot.db",
            BOT_DB_CHECKS,
            label="Bot 資料庫",
        ),
        "web": inspect_database(
            root / "web_dashboard.db",
            WEB_DB_CHECKS,
            label="Web 資料庫",
        ),
    }

    metrics = {
        "payment_pending": databases["web"]["metrics"].get("payment_pending"),
        "payment_apply_error": databases["web"]["metrics"].get("payment_apply_error"),
        "sync_failed": databases["web"]["metrics"].get("sync_failed"),
        "sync_backlog": databases["web"]["metrics"].get("sync_backlog"),
        "open_orders": databases["web"]["metrics"].get("open_orders"),
        "order_state_drift": databases["web"]["metrics"].get("order_state_drift"),
        "topup_pending": databases["bot"]["metrics"].get("topup_pending"),
        "negative_wallets": databases["bot"]["metrics"].get("negative_wallets"),
        "wallet_duplicate_refs": databases["bot"]["metrics"].get("wallet_duplicate_refs"),
    }

    backups = inspect_backups(root)
    alerts: list[dict[str, str]] = []

    for service in services.values():
        if not service["available"]:
            alerts.append(
                {
                    "severity": "warning",
                    "message": f"{service['name']} 無法讀取 systemd 狀態。",
                }
            )
        elif not service["ok"]:
            alerts.append(
                {
                    "severity": "critical",
                    "message": f"{service['name']} 目前不是 active 狀態。",
                }
            )

    for database in databases.values():
        if not database["exists"]:
            alerts.append(
                {
                    "severity": "critical",
                    "message": f"{database['label']} 檔案不存在。",
                }
            )
        elif not database["ok"]:
            alerts.append(
                {
                    "severity": "critical",
                    "message": f"{database['label']} quick_check 未通過。",
                }
            )

    alert_metric_labels = {
        "payment_apply_error": "付款套用錯誤",
        "sync_failed": "同步失敗",
        "negative_wallets": "負數錢包",
        "wallet_duplicate_refs": "重複錢包交易識別碼",
        "order_state_drift": "訂單狀態不同步",
    }
    for key, label in alert_metric_labels.items():
        value = metrics.get(key)
        if isinstance(value, int) and value > 0:
            alerts.append(
                {
                    "severity": "critical" if key == "negative_wallets" else "warning",
                    "message": f"{label}：{value} 筆。",
                }
            )

    for backup in backups.values():
        if not backup["found"]:
            alerts.append(
                {
                    "severity": "warning",
                    "message": f"{backup['label']} 尚未找到可辨識的備份。",
                }
            )
        elif not backup["fresh"]:
            alerts.append(
                {
                    "severity": "warning",
                    "message": f"{backup['label']} 最近備份已超過 72 小時。",
                }
            )

    severities = {alert["severity"] for alert in alerts}
    if "critical" in severities:
        overall = "critical"
        overall_text = "需要處理"
    elif "warning" in severities:
        overall = "warning"
        overall_text = "有注意事項"
    else:
        overall = "ok"
        overall_text = "系統正常"

    return {
        "checked_at": datetime.now(TAIPEI_TZ).strftime("%Y/%m/%d %H:%M:%S"),
        "overall": overall,
        "overall_text": overall_text,
        "services": services,
        "databases": databases,
        "metrics": metrics,
        "backups": backups,
        "git": inspect_git(root),
        "alerts": alerts,
        "root": str(root),
        "process_pid": os.getpid(),
    }
