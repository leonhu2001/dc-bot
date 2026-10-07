from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping

from web.app.services.discord_service import send_direct_message


_WORKER_ROLES = {"worker", "護航 / 陪玩", "worker_payout", "護航 / 陪玩分潤"}
_CS_ROLES = {"customer_service", "customer-service", "cs", "客服", "魔丸♫客服分潤"}


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


def _chunks(lines: list[str], limit: int = 1800) -> list[str]:
    result: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        extra = len(line) + (1 if current else 0)
        if current and size + extra > limit:
            result.append("\n".join(current))
            current = [line]
            size = len(line)
        else:
            current.append(line)
            size += extra
    if current:
        result.append("\n".join(current))
    return result


def _fetch_details(*, db_file: str | Path, person_id: str, month: str, role: str) -> dict:
    worker_enabled, cs_enabled = _role_targets(role)
    month_sql, month_params = _month_filter(month)
    data = {
        "display_name": person_id,
        "worker_total": 0,
        "tip_total": 0,
        "cs_total": 0,
        "worker_lines": [],
        "tip_lines": [],
        "cs_lines": [],
    }

    conn = sqlite3.connect(str(db_file), timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        if worker_enabled:
            rows = conn.execute(
                f"""
                SELECT COALESCE(NULLIF(p.worker_display_name, ''), p.worker_discord_id) AS display_name,
                       COALESCE(p.final_payout, 0) AS amount,
                       COALESCE(w.bot_order_no, 'WEB-' || w.id) AS order_no,
                       w.category, w.item,
                       COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')) AS closed_at
                FROM worker_payouts p
                JOIN web_orders w ON w.id = p.order_id
                WHERE w.status = 'closed'
                  AND CAST(p.worker_discord_id AS TEXT) = ?
                  AND p.payout_status = 'paid'
                  AND COALESCE(p.final_payout, 0) > 0
                  {month_sql}
                ORDER BY closed_at ASC, p.id ASC
                """,
                [person_id, *month_params],
            ).fetchall()
            for row in rows:
                data["display_name"] = data["display_name"] if data["display_name"] != person_id else str(row["display_name"] or person_id)
                amount = int(row["amount"] or 0)
                data["worker_total"] += amount
                date = str(row["closed_at"] or "")[:10] or "未紀錄"
                service = str(row["item"] or row["category"] or "未紀錄服務")
                data["worker_lines"].append(f"• {row['order_no']}｜{date}｜{service}｜{amount:,}T")

            rows = conn.execute(
                f"""
                SELECT COALESCE(NULLIF(p.worker_display_name, ''), p.worker_discord_id) AS display_name,
                       COALESCE(p.amount, 0) AS amount,
                       COALESCE(w.bot_order_no, 'WEB-' || w.id) AS order_no,
                       COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')) AS closed_at
                FROM worker_tips p
                JOIN web_orders w ON w.id = p.order_id
                WHERE w.status = 'closed'
                  AND p.payment_status = 'paid'
                  AND CAST(p.worker_discord_id AS TEXT) = ?
                  AND p.payout_status = 'paid'
                  AND COALESCE(p.amount, 0) > 0
                  {month_sql}
                ORDER BY closed_at ASC, p.id ASC
                """,
                [person_id, *month_params],
            ).fetchall()
            for row in rows:
                data["display_name"] = data["display_name"] if data["display_name"] != person_id else str(row["display_name"] or person_id)
                amount = int(row["amount"] or 0)
                data["tip_total"] += amount
                date = str(row["closed_at"] or "")[:10] or "未紀錄"
                data["tip_lines"].append(f"• {row['order_no']}｜{date}｜🍗 雞腿｜{amount:,}T")

        if cs_enabled:
            rows = conn.execute(
                f"""
                SELECT COALESCE(NULLIF(p.customer_service_display_name, ''), p.customer_service_discord_id) AS display_name,
                       COALESCE(p.payout_amount, 0) AS amount,
                       COALESCE(w.bot_order_no, 'WEB-' || w.id) AS order_no,
                       w.category, w.item,
                       COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')) AS closed_at
                FROM customer_service_payouts p
                JOIN web_orders w ON w.id = p.order_id
                WHERE w.status = 'closed'
                  AND CAST(p.customer_service_discord_id AS TEXT) = ?
                  AND p.payout_status = 'paid'
                  AND COALESCE(p.payout_amount, 0) > 0
                  {month_sql}
                ORDER BY closed_at ASC, p.id ASC
                """,
                [person_id, *month_params],
            ).fetchall()
            for row in rows:
                data["display_name"] = data["display_name"] if data["display_name"] != person_id else str(row["display_name"] or person_id)
                amount = int(row["amount"] or 0)
                data["cs_total"] += amount
                date = str(row["closed_at"] or "")[:10] or "未紀錄"
                service = str(row["item"] or row["category"] or "未紀錄服務")
                data["cs_lines"].append(f"• {row['order_no']}｜{date}｜客服｜{service}｜{amount:,}T")
    finally:
        conn.close()

    return data


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
    tip_total = int(details["tip_total"])
    cs_total = int(details["cs_total"])
    total = worker_total + tip_total + cs_total
    if total <= 0:
        return {"sent": False, "reason": "empty_salary_details"}

    fields = [
        {"name": "本次發放", "value": f"**{total:,}T**", "inline": False},
        {"name": "發放期間", "value": _period_label(month), "inline": True},
    ]
    if worker_total:
        fields.append({"name": "陪玩／打單收入", "value": f"{worker_total:,}T", "inline": True})
    if tip_total:
        fields.append({"name": "🍗 雞腿", "value": f"{tip_total:,}T", "inline": True})
    if cs_total:
        fields.append({"name": "客服分潤", "value": f"{cs_total:,}T", "inline": True})

    send_direct_message(
        person_id,
        embeds=[{
            "title": "💰 薪資已發放",
            "description": f"{details['display_name']}，你的 {_period_label(month)} 薪資已完成發放。\n以下為本次薪資摘要，完整明細會接在後面。",
            "fields": fields,
            "footer": {"text": "魔丸娛樂｜員工薪資通知"},
        }],
    )

    lines: list[str] = []
    for title, key in (
        ("**陪玩／打單收入**", "worker_lines"),
        ("**🍗 雞腿**", "tip_lines"),
        ("**客服分潤**", "cs_lines"),
    ):
        values = details[key]
        if not values:
            continue
        if lines:
            lines.append("")
        lines.append(title)
        lines.extend(values)

    chunks = _chunks(lines)
    for index, chunk in enumerate(chunks, start=1):
        heading = "**薪資明細**" if len(chunks) == 1 else f"**薪資明細（{index}/{len(chunks)}）**"
        send_direct_message(person_id, content=f"{heading}\n{chunk}")

    return {
        "sent": True,
        "total": total,
        "worker_total": worker_total,
        "tip_total": tip_total,
        "customer_service_total": cs_total,
        "detail_messages": len(chunks),
    }
