from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping

from web.app.services.discord_service import send_direct_message


_WORKER_ROLES = {"worker", "護航 / 陪玩", "worker_payout", "護航 / 陪玩分潤"}
_CS_ROLES = {"customer_service", "customer-service", "cs", "客服", "魔丸♫客服分潤"}
_EMPLOYEE_CENTER_URL = "https://mowanentertainment.com/employee"


def _role_targets(role: str | None) -> tuple[bool, bool]:
    value = str(role or "").strip().lower()
    if value in _WORKER_ROLES:
        return True, False
    if value in _CS_ROLES:
        return False, True
    return True, True


def _count(snapshot: Mapping[str, Any] | None, bucket: str) -> int:
    try:
        return int((((snapshot or {}).get(bucket) or {}).get("unpaid") or {}).get("count") or 0)
    except Exception:
        return 0


def should_send_payout_paid_notification(*, before, after) -> bool:
    after_data = dict(after or {})
    if str(after_data.get("target_status") or "").strip() != "paid":
        return False

    worker, cs = _role_targets(after_data.get("person_role"))
    changed = 0
    if worker:
        changed += _count(before, "worker_payouts")
        changed += _count(before, "worker_tips")
    if cs:
        changed += _count(before, "customer_service_payouts")
    return changed > 0


def _period_label(month: str) -> str:
    if not month:
        return "全部期間"
    try:
        year, month_no = month.split("-", 1)
        return f"{int(year)}年{int(month_no)}月"
    except Exception:
        return month


def _month_filter(month: str) -> tuple[str, list[str]]:
    if not month:
        return "", []
    return (
        " AND substr(COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')), 1, 7) = ? ",
        [month],
    )


def _fetch_details(*, db_file: str | Path, person_id: str, month: str, role: str) -> dict:
    worker_enabled, cs_enabled = _role_targets(role)
    month_sql, month_params = _month_filter(month)
    data = {
        "display_name": person_id,
        "worker_total": 0,
        "worker_count": 0,
        "tip_total": 0,
        "tip_count": 0,
        "cs_total": 0,
        "cs_count": 0,
    }

    conn = sqlite3.connect(str(db_file), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        if worker_enabled:
            rows = conn.execute(
                f"""
                SELECT COALESCE(NULLIF(p.worker_display_name, ''), p.worker_discord_id) AS display_name,
                       COALESCE(p.final_payout, 0) AS amount
                FROM worker_payouts p
                JOIN web_orders w ON w.id = p.order_id
                WHERE w.status = 'closed'
                  AND CAST(p.worker_discord_id AS TEXT) = ?
                  AND p.payout_status = 'paid'
                  AND COALESCE(p.final_payout, 0) > 0
                  {month_sql}
                ORDER BY p.id ASC
                """,
                [person_id, *month_params],
            ).fetchall()
            for row in rows:
                if data["display_name"] == person_id:
                    data["display_name"] = str(row["display_name"] or person_id)
                data["worker_total"] += int(row["amount"] or 0)
                data["worker_count"] += 1

            rows = conn.execute(
                f"""
                SELECT COALESCE(NULLIF(p.worker_display_name, ''), p.worker_discord_id) AS display_name,
                       COALESCE(p.amount, 0) AS amount
                FROM worker_tips p
                JOIN web_orders w ON w.id = p.order_id
                WHERE w.status = 'closed'
                  AND p.payment_status = 'paid'
                  AND CAST(p.worker_discord_id AS TEXT) = ?
                  AND p.payout_status = 'paid'
                  AND COALESCE(p.amount, 0) > 0
                  {month_sql}
                ORDER BY p.id ASC
                """,
                [person_id, *month_params],
            ).fetchall()
            for row in rows:
                if data["display_name"] == person_id:
                    data["display_name"] = str(row["display_name"] or person_id)
                data["tip_total"] += int(row["amount"] or 0)
                data["tip_count"] += 1

        if cs_enabled:
            rows = conn.execute(
                f"""
                SELECT COALESCE(NULLIF(p.customer_service_display_name, ''), p.customer_service_discord_id) AS display_name,
                       COALESCE(p.payout_amount, 0) AS amount
                FROM customer_service_payouts p
                JOIN web_orders w ON w.id = p.order_id
                WHERE w.status = 'closed'
                  AND CAST(p.customer_service_discord_id AS TEXT) = ?
                  AND p.payout_status = 'paid'
                  AND COALESCE(p.payout_amount, 0) > 0
                  {month_sql}
                ORDER BY p.id ASC
                """,
                [person_id, *month_params],
            ).fetchall()
            for row in rows:
                if data["display_name"] == person_id:
                    data["display_name"] = str(row["display_name"] or person_id)
                data["cs_total"] += int(row["amount"] or 0)
                data["cs_count"] += 1
    finally:
        conn.close()

    return data


def _category_line(label: str, total: int, count: int) -> str:
    return f"• **{label}**　{total:,}T・{count}筆"


def send_payout_paid_notification(*, db_file, person_id, before, after) -> dict:
    person_id = str(person_id or "").strip()
    if not person_id:
        return {"sent": False, "reason": "missing_person_id"}
    if not should_send_payout_paid_notification(before=before, after=after):
        return {"sent": False, "reason": "no_new_paid_salary"}

    after_data = dict(after or {})
    month = str((before or {}).get("month") or "").strip()
    if month == "全部月份":
        month = ""

    details = _fetch_details(
        db_file=db_file,
        person_id=person_id,
        month=month,
        role=str(after_data.get("person_role") or ""),
    )
    worker_total = int(details["worker_total"])
    worker_count = int(details["worker_count"])
    tip_total = int(details["tip_total"])
    tip_count = int(details["tip_count"])
    cs_total = int(details["cs_total"])
    cs_count = int(details["cs_count"])
    total = worker_total + tip_total + cs_total
    if total <= 0:
        return {"sent": False, "reason": "empty_salary_details"}

    category_lines: list[str] = []
    if worker_total:
        category_lines.append(_category_line("陪玩／打單收入", worker_total, worker_count))
    if tip_total:
        category_lines.append(_category_line("🍗 雞腿", tip_total, tip_count))
    if cs_total:
        category_lines.append(_category_line("客服分潤", cs_total, cs_count))

    period = _period_label(month)
    send_direct_message(
        person_id,
        embeds=[{
            "title": "💰 薪資已發放",
            "description": (
                f"{details['display_name']}，你的 **{period}** 薪資已完成發放。\n"
                f"完整薪資明細請至 [員工中心]({_EMPLOYEE_CENTER_URL}) 查看。"
            ),
            "fields": [
                {"name": "本次發放", "value": f"**{total:,}T**", "inline": True},
                {"name": "發放期間", "value": period, "inline": True},
                {"name": "薪資分類", "value": "\n".join(category_lines), "inline": False},
            ],
            "footer": {"text": "魔丸娛樂｜員工薪資通知"},
        }],
    )

    return {
        "sent": True,
        "total": total,
        "worker_total": worker_total,
        "worker_count": worker_count,
        "tip_total": tip_total,
        "tip_count": tip_count,
        "customer_service_total": cs_total,
        "customer_service_count": cs_count,
        "detail_messages": 0,
        "employee_center_url": _EMPLOYEE_CENTER_URL,
    }
