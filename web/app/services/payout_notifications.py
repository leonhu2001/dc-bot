from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping

from web.app.services.discord_service import send_direct_message


_WORKER_ROLE_NAMES = {
    "worker",
    "護航 / 陪玩",
    "worker_payout",
    "護航 / 陪玩分潤",
}

_CUSTOMER_SERVICE_ROLE_NAMES = {
    "customer_service",
    "customer-service",
    "cs",
    "客服",
    "魔丸♫客服分潤",
}


def _role_targets(person_role: str | None) -> tuple[bool, bool]:
    role = str(person_role or "").strip().lower()

    if role in _WORKER_ROLE_NAMES:
        return True, False

    if role in _CUSTOMER_SERVICE_ROLE_NAMES:
        return False, True

    # Mixed/legacy role labels are deliberately treated as both. This mirrors
    # the payout status updater's fallback behaviour.
    return True, True


def _status_count(
    snapshot: Mapping[str, Any] | None,
    bucket: str,
    status: str,
) -> int:
    try:
        return int(
            (((snapshot or {}).get(bucket) or {}).get(status) or {}).get("count")
            or 0
        )
    except Exception:
        return 0


def should_send_payout_paid_notification(
    *,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> bool:
    after_data = dict(after or {})
    if str(after_data.get("target_status") or "").strip() != "paid":
        return False

    update_worker, update_customer_service = _role_targets(
        str(after_data.get("person_role") or "")
    )

    changed_count = 0
    if update_worker:
        changed_count += _status_count(before, "worker_payouts", "unpaid")
        changed_count += _status_count(before, "worker_tips", "unpaid")

    if update_customer_service:
        changed_count += _status_count(
            before,
            "customer_service_payouts",
            "unpaid",
        )

    return changed_count > 0


def _period_label(month: str | None) -> str:
    value = str(month or "").strip()
    if not value:
        return "全部期間"

    try:
        year, month_number = value.split("-", 1)
        return f"{int(year)}年{int(month_number)}月"
    except Exception:
        return value


def _month_where(month: str | None) -> tuple[str, list[str]]:
    value = str(month or "").strip()
    if not value:
        return "", []

    return (
        " AND substr("
        "COALESCE(NULLIF(w.closed_at, ''), NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')),
"
        "1, 7) = ? ",
        [value],
    )


def _detail_chunks(lines: list[str], max_chars: int = 1800) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for line in lines:
        line = str(line)
        extra = len(line) + (1 if current else 0)

        if current and current_length + extra > max_chars:
            chunks.append("\n".join(current))
            current = [line]
            current_length = len(line)
        else:
            current.append(line)
            current_length += extra

    if current:
        chunks.append("\n".join(current))

    return chunks


def _service_label(category: Any, item: Any) -> str:
    return str(item or category or "未紀錄服務").strip() or "未紀錄服務"


def _fetch_salary_details(
    *,
    db_file: str | Path,
    person_id: str,
    month: str | None,
    person_role: str | None,
) -> dict:
    update_worker, update_customer_service = _role_targets(person_role)
    month_sql, month_params = _month_where(month)

    result = {
        "display_name": person_id,
        "worker_total": 0,
        "tip_total": 0,
        "customer_service_total": 0,
        "worker_lines": [],
        "tip_lines": [],
        "customer_service_lines": [],
    }

    conn = sqlite3.connect(str(db_file), timeout=15)
    conn.row_factory = sqlite3.Row

    try:
        if update_worker:
            worker_rows = conn.execute(
                f"""
                SELECT
                    COALESCE(NULLIF(p.worker_display_name, ''), p.worker_discord_id) AS display_name,
                    COALESCE(p.final_payout, 0) AS amount,
                    COALESCE(w.bot_order_no, 'WEB-' || w.id) AS order_no,
                    w.category,
                    w.item,
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

            for row in worker_rows:
                if result["display_name"] == person_id and row["display_name"]:
                    result["display_name"] = str(row["display_name"])

                amount = int(row["amount"] or 0)
                result["worker_total"] += amount
                date_text = str(row["closed_at"] or "")[:10] or "未紀錄"
                result["worker_lines"].append(
                    f"• {row['order_no']}｜{date_text}｜{_service_label(row['category'], row['item'])}｜{amount:,}T"
                )

            tip_rows = conn.execute(
                f"""
                SELECT
                    COALESCE(NULLIF(p.worker_display_name, ''), p.worker_discord_id) AS display_name,
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

            for row in tip_rows:
                if result["display_name"] == person_id and row["display_name"]:
                    result["display_name"] = str(row["display_name"])

                amount = int(row["amount"] or 0)
                result["tip_total"] += amount
                date_text = str(row["closed_at"] or "")[:10] or "未紀錄"
                result["tip_lines"].append(
                    f"• {row['order_no']}｜{date_text}｜🍗 雞腿｜{amount:,}T"
                )

        if update_customer_service:
            cs_rows = conn.execute(
                f"""
                SELECT
                    COALESCE(NULLIF(p.customer_service_display_name, ''), p.customer_service_discord_id) AS display_name,
                    COALESCE(p.payout_amount, 0) AS amount,
                    COALESCE(w.bot_order_no, 'WEB-' || w.id) AS order_no,
                    w.category,
                    w.item,
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

            for row in cs_rows:
                if result["display_name"] == person_id and row["display_name"]:
                    result["display_name"] = str(row["display_name"])

                amount = int(row["amount"] or 0)
                result["customer_service_total"] += amount
                date_text = str(row["closed_at"] or "")[:10] or "未紀錄"
                result["customer_service_lines"].append(
                    f"• {row['order_no']}｜{date_text}｜客服｜{_service_label(row['category'], row['item'])}｜{amount:,}T"
                )
    finally:
        conn.close()

    return result


def send_payout_paid_notification(
    *,
    db_file: str | Path,
    person_id: str | int,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any] | None,
) -> dict:
    person_id_text = str(person_id or "").strip()
    if not person_id_text:
        return {"sent": False, "reason": "missing_person_id"}

    if not should_send_payout_paid_notification(before=before, after=after):
        return {"sent": False, "reason": "no_new_paid_salary"}

    after_data = dict(after or {})
    month = str((before or {}).get("month") or "").strip()
    if month == "全部月份":
        month = ""

    details = _fetch_salary_details(
        db_file=db_file,
        person_id=person_id_text,
        month=month,
        person_role=str(after_data.get("person_role") or ""),
    )

    worker_total = int(details["worker_total"] or 0)
    tip_total = int(details["tip_total"] or 0)
    customer_service_total = int(details["customer_service_total"] or 0)
    total = worker_total + tip_total + customer_service_total

    if total <= 0:
        return {"sent": False, "reason": "empty_salary_details"}

    fields = [
        {
            "name": "本次發放",
            "value": f"**{total:,}T**",
            "inline": False,
        },
        {
            "name": "發放期間",
            "value": _period_label(month),
            "inline": True,
        },
    ]

    if worker_total:
        fields.append(
            {
                "name": "陪玩／打單收入",
                "value": f"{worker_total:,}T",
                "inline": True,
            }
        )

    if tip_total:
        fields.append(
            {
                "name": "🍗 雞腿",
                "value": f"{tip_total:,}T",
                "inline": True,
            }
        )

    if customer_service_total:
        fields.append(
            {
                "name": "客服分潤",
                "value": f"{customer_service_total:,}T",
                "inline": True,
            }
        )

    send_direct_message(
        person_id_text,
        embeds=[
            {
                "title": "💰 薪資已發放",
                "description": (
                    f"{details['display_name']}，你的 {_period_label(month)} 薪資已完成發放。"
                    "\n以下為本次薪資摘要，完整明細會接在後面。"
                ),
                "fields": fields,
                "footer": {
                    "text": "魔丸娛樂｜員工薪資通知",
                },
            }
        ],
    )

    detail_lines: list[str] = []
    if details["worker_lines"]:
        detail_lines.append("**陪玩／打單收入**")
        detail_lines.extend(details["worker_lines"])

    if details["tip_lines"]:
        if detail_lines:
            detail_lines.append("")
        detail_lines.append("**🍗 雞腿**")
        detail_lines.extend(details["tip_lines"])

    if details["customer_service_lines"]:
        if detail_lines:
            detail_lines.append("")
        detail_lines.append("**客服分潤**")
        detail_lines.extend(details["customer_service_lines"])

    chunks = _detail_chunks(detail_lines)
    for index, chunk in enumerate(chunks, start=1):
        heading = "**薪資明細**"
        if len(chunks) > 1:
            heading += f"（{index}/{len(chunks)}）"

        send_direct_message(
            person_id_text,
            content=f"{heading}\n{chunk}",
        )

    return {
        "sent": True,
        "total": total,
        "worker_total": worker_total,
        "tip_total": tip_total,
        "customer_service_total": customer_service_total,
        "detail_messages": len(chunks),
    }
