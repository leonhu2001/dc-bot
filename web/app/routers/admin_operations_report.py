from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from core.time_utils import utc_now_naive
from web.app.routers.admin_payout_summary import current_user, db_path, require_admin


router = APIRouter(tags=["admin_operations_report"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)


def _shift_month_start(value: datetime, months: int) -> datetime:
    total_months = value.year * 12 + (value.month - 1) + months
    year, month_zero = divmod(total_months, 12)
    return value.replace(
        year=year,
        month=month_zero + 1,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def _report_period(
    period: str | None,
) -> tuple[str, str | None, str, str | None, str | None, str | None]:
    period = str(period or "quarter").strip().lower()
    now = utc_now_naive() + timedelta(hours=8)

    if period == "all":
        return "all", None, "全部期間", None, None, None

    if period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        previous_start = _shift_month_start(start, -1)
        previous_label = "上月同期"
        period_label = "本月"
    elif period == "year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        previous_start = start.replace(year=start.year - 1)
        previous_label = "去年同期"
        period_label = "本年度"
    else:
        period = "quarter"
        quarter_month = ((now.month - 1) // 3) * 3 + 1
        start = now.replace(
            month=quarter_month,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        previous_start = _shift_month_start(start, -3)
        previous_label = "上季同期"
        period_label = "本季度"

    current_day_end = (
        now.replace(hour=0, minute=0, second=0, microsecond=0)
        + timedelta(days=1)
    )
    elapsed_days = max(1, (current_day_end - start).days)
    previous_end = min(start, previous_start + timedelta(days=elapsed_days))
    return (
        period,
        start.strftime("%Y-%m-%d %H:%M:%S"),
        period_label,
        previous_start.strftime("%Y-%m-%d %H:%M:%S"),
        previous_end.strftime("%Y-%m-%d %H:%M:%S"),
        previous_label,
    )


def _report_change(current: int | float, previous: int | float) -> dict:
    current_value = float(current or 0)
    previous_value = float(previous or 0)
    delta = current_value - previous_value
    rate = round(delta * 100 / previous_value, 1) if previous_value else None
    return {
        "previous": round(previous_value, 1),
        "delta": round(delta, 1),
        "rate": rate,
    }


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        [table_name],
    ).fetchone()
    return row is not None


def _discount_parts(row: sqlite3.Row | dict) -> tuple[int, int, int]:
    percent_discount = max(0, int(row["percent_discount"] or 0))
    fixed_discount = max(0, int(row["fixed_discount"] or 0))
    store_absorbed = max(0, int(row["store_absorbed"] or 0))

    # Current checkout stores benefit-coupon absorption in BOTH
    # cash_coupon_amount and store_absorbed_amount. Count the coupon once,
    # then treat only the remainder as point / other store-funded benefits.
    point_discount = max(0, store_absorbed - fixed_discount)
    return percent_discount, fixed_discount, point_discount


def build_operations_report(period: str | None) -> dict:
    (
        period,
        start_at,
        period_label,
        previous_start_at,
        previous_end_at,
        previous_label,
    ) = _report_period(period)

    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    closed_expr = (
        "COALESCE("
        "NULLIF(w.closed_at,''), "
        "datetime(NULLIF(w.updated_at,''), '+8 hours'), "
        "datetime(w.created_at, '+8 hours')"
        ")"
    )
    has_overrides = _table_exists(conn, "worker_payout_overrides")

    def order_window(
        start_value: str | None,
        end_value: str | None = None,
    ) -> tuple[list[sqlite3.Row], str, list[str]]:
        where = "WHERE w.status = 'closed'"
        params: list[str] = []
        if start_value:
            where += f" AND {closed_expr} >= ?"
            params.append(start_value)
        if end_value:
            where += f" AND {closed_expr} < ?"
            params.append(end_value)

        if has_overrides:
            override_sql = """
                COALESCE((
                    SELECT COUNT(*)
                    FROM worker_payout_overrides o
                    WHERE o.order_id = w.id
                ), 0) AS manual_override_count,
                COALESCE((
                    SELECT SUM(o.manual_final_payout)
                    FROM worker_payout_overrides o
                    WHERE o.order_id = w.id
                ), 0) AS manual_override_total,
                COALESCE((
                    SELECT GROUP_CONCAT(NULLIF(TRIM(o.reason), ''), '；')
                    FROM worker_payout_overrides o
                    WHERE o.order_id = w.id
                ), '') AS manual_override_reasons,
            """
        else:
            override_sql = """
                0 AS manual_override_count,
                0 AS manual_override_total,
                '' AS manual_override_reasons,
            """

        rows = conn.execute(
            f"""
            SELECT
                w.id,
                w.bot_order_no,
                w.category,
                w.item,
                w.customer_discord_id,
                w.customer_display_name,
                COALESCE(
                    NULLIF(TRIM(w.customer_display_name), ''),
                    NULLIF(TRIM(w.customer_discord_id), ''),
                    '未紀錄'
                ) AS customer_name,
                COALESCE(w.customer_pay_amount, w.amount, 0) AS revenue,
                COALESCE(NULLIF(w.payout_base_amount, 0), w.amount, 0) AS payout_base,
                COALESCE(NULLIF(TRIM(w.payment_method), ''), '未紀錄') AS payment_method,
                COALESCE(w.manual_discount_amount, 0) AS percent_discount,
                COALESCE(w.cash_coupon_amount, 0) AS fixed_discount,
                COALESCE(w.store_absorbed_amount, 0) AS store_absorbed,
                {closed_expr} AS closed_at,
                COALESCE((
                    SELECT SUM(p.final_payout)
                    FROM worker_payouts p
                    WHERE p.order_id = w.id
                ), 0) AS worker_cost,
                COALESCE((
                    SELECT SUM(p.payout_amount)
                    FROM customer_service_payouts p
                    WHERE p.order_id = w.id
                ), 0) AS service_cost,
                COALESCE((
                    SELECT SUM(p.named_bonus_amount)
                    FROM worker_payouts p
                    WHERE p.order_id = w.id
                ), 0) AS named_bonus_amount,
                {override_sql}
                w.note AS order_note
            FROM web_orders w
            {where}
            ORDER BY closed_at ASC, w.id ASC
            """,
            params,
        ).fetchall()
        return rows, where, params

    def summarize(rows: list[sqlite3.Row]) -> dict:
        revenue = sum(int(row["revenue"] or 0) for row in rows)
        worker_cost = sum(int(row["worker_cost"] or 0) for row in rows)
        service_cost = sum(int(row["service_cost"] or 0) for row in rows)
        payroll = worker_cost + service_cost
        retained = revenue - payroll
        order_count = len(rows)
        avg_order = round(revenue / order_count) if order_count else 0

        percent_discount = 0
        fixed_discount = 0
        point_discount = 0
        for row in rows:
            row_percent, row_fixed, row_point = _discount_parts(row)
            percent_discount += row_percent
            fixed_discount += row_fixed
            point_discount += row_point

        discount_total = percent_discount + fixed_discount + point_discount
        retained_rate = round(retained * 100 / revenue, 1) if revenue else 0.0
        payroll_rate = round(payroll * 100 / revenue, 1) if revenue else 0.0

        customers: dict[str, int] = {}
        for row in rows:
            customer_id = str(row["customer_discord_id"] or "").strip()
            if customer_id:
                customers[customer_id] = customers.get(customer_id, 0) + 1
        repeat_customers = sum(1 for count in customers.values() if count >= 2)
        repeat_rate = (
            round(repeat_customers * 100 / len(customers), 1)
            if customers
            else 0.0
        )
        return {
            "revenue": revenue,
            "worker_cost": worker_cost,
            "service_cost": service_cost,
            "payroll": payroll,
            "retained": retained,
            "retained_rate": retained_rate,
            "payroll_rate": payroll_rate,
            "order_count": order_count,
            "avg_order": avg_order,
            "customer_count": len(customers),
            "repeat_customers": repeat_customers,
            "repeat_rate": repeat_rate,
            "percent_discount": percent_discount,
            "fixed_discount": fixed_discount,
            "point_discount": point_discount,
            "discount_total": discount_total,
        }

    try:
        orders, current_where, current_params = order_window(start_at)
        previous_orders: list[sqlite3.Row] = []
        comparison_history_exists = False
        if previous_start_at and previous_end_at:
            previous_orders, _, _ = order_window(previous_start_at, previous_end_at)
            history_row = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM web_orders w
                WHERE w.status = 'closed' AND {closed_expr} < ?
                """,
                [previous_end_at],
            ).fetchone()
            comparison_history_exists = bool(int(history_row["total"] or 0))

        worker_rows = conn.execute(
            f"""
            SELECT
                p.worker_discord_id,
                COALESCE(NULLIF(p.worker_display_name,''), p.worker_discord_id) AS name,
                SUM(COALESCE(p.final_payout,0)) AS amount,
                COUNT(*) AS jobs
            FROM worker_payouts p
            JOIN web_orders w ON w.id = p.order_id
            {current_where}
            GROUP BY p.worker_discord_id, name
            HAVING amount > 0
            ORDER BY amount DESC
            LIMIT 8
            """,
            current_params,
        ).fetchall()

        customer_history = conn.execute(
            f"""
            SELECT w.id, w.customer_discord_id, {closed_expr} AS closed_at
            FROM web_orders w
            WHERE w.status = 'closed'
              AND TRIM(COALESCE(w.customer_discord_id, '')) <> ''
            ORDER BY closed_at ASC, w.id ASC
            """
        ).fetchall()
        first_closed_order_ids: set[int] = set()
        seen_customer_ids: set[str] = set()
        for history_row in customer_history:
            customer_id = str(history_row["customer_discord_id"] or "").strip()
            if customer_id and customer_id not in seen_customer_ids:
                seen_customer_ids.add(customer_id)
                first_closed_order_ids.add(int(history_row["id"]))

        created_taipei_expr = "datetime(w.created_at, '+8 hours')"

        def cancellation_stats(
            start_value: str | None,
            end_value: str | None = None,
        ) -> dict:
            status_where = "WHERE 1 = 1"
            status_params: list[str] = []
            if start_value:
                status_where += f" AND {created_taipei_expr} >= ?"
                status_params.append(start_value)
            if end_value:
                status_where += f" AND {created_taipei_expr} < ?"
                status_params.append(end_value)
            row = conn.execute(
                f"""
                SELECT
                    COUNT(*) AS total_orders,
                    SUM(CASE WHEN LOWER(TRIM(COALESCE(w.status, '')))
                        IN ('cancelled', 'canceled') THEN 1 ELSE 0 END) AS cancelled_orders
                FROM web_orders w
                {status_where}
                """,
                status_params,
            ).fetchone()
            total_orders = int(row["total_orders"] or 0)
            cancelled_orders = int(row["cancelled_orders"] or 0)
            return {
                "created_orders": total_orders,
                "cancelled_orders": cancelled_orders,
                "cancellation_rate": (
                    round(cancelled_orders * 100 / total_orders, 1)
                    if total_orders
                    else 0.0
                ),
            }

        cancellation = cancellation_stats(start_at)
    finally:
        conn.close()

    current = summarize(orders)
    previous = summarize(previous_orders)
    daily: dict[str, int] = {}
    services: dict[str, dict] = {}
    payment_methods: dict[str, dict] = {}
    diagnostics: list[dict] = []
    new_customer_revenue = 0
    repeat_customer_revenue = 0
    unidentified_customer_revenue = 0
    new_customer_orders = 0
    repeat_customer_orders = 0
    unidentified_customer_orders = 0

    for row in orders:
        day = str(row["closed_at"] or "")[:10] or "未紀錄"
        daily[day] = daily.get(day, 0) + int(row["revenue"] or 0)
        service = str(row["item"] or row["category"] or "其他")
        bucket = services.setdefault(
            service,
            {
                "label": service,
                "revenue": 0,
                "orders": 0,
                "worker_cost": 0,
                "service_cost": 0,
                "payroll": 0,
                "retained": 0,
                "retained_rate": 0.0,
            },
        )
        row_revenue = int(row["revenue"] or 0)
        row_payout_base = int(row["payout_base"] or 0)
        row_worker_cost = int(row["worker_cost"] or 0)
        row_service_cost = int(row["service_cost"] or 0)
        row_payroll = row_worker_cost + row_service_cost
        row_retained = row_revenue - row_payroll
        row_retained_rate = (
            round(row_retained * 100 / row_revenue, 1)
            if row_revenue
            else None
        )
        customer_id = str(row["customer_discord_id"] or "").strip()
        if not customer_id:
            unidentified_customer_revenue += row_revenue
            unidentified_customer_orders += 1
        elif int(row["id"]) in first_closed_order_ids:
            new_customer_revenue += row_revenue
            new_customer_orders += 1
        else:
            repeat_customer_revenue += row_revenue
            repeat_customer_orders += 1

        payment_method = str(row["payment_method"] or "未紀錄").strip() or "未紀錄"
        payment_bucket = payment_methods.setdefault(
            payment_method,
            {"label": payment_method, "orders": 0, "revenue": 0, "share": 0.0},
        )
        payment_bucket["orders"] += 1
        payment_bucket["revenue"] += row_revenue
        bucket["revenue"] += row_revenue
        bucket["orders"] += 1
        bucket["worker_cost"] += row_worker_cost
        bucket["service_cost"] += row_service_cost
        bucket["payroll"] += row_payroll

        diagnostics.append(
            {
                "id": int(row["id"]),
                "order_no": str(row["bot_order_no"] or f"WEB-{row['id']}"),
                "service": service,
                "customer_name": str(row["customer_name"] or "未紀錄"),
                "closed_at": str(row["closed_at"] or ""),
                "revenue": row_revenue,
                "payout_base": row_payout_base,
                "payout_gap": max(0, row_payout_base - row_revenue),
                "store_absorbed": max(0, int(row["store_absorbed"] or 0)),
                "worker_cost": row_worker_cost,
                "service_cost": row_service_cost,
                "payroll": row_payroll,
                "named_bonus_amount": int(row["named_bonus_amount"] or 0),
                "manual_override_count": int(row["manual_override_count"] or 0),
                "manual_override_total": int(row["manual_override_total"] or 0),
                "manual_override_reasons": str(row["manual_override_reasons"] or ""),
                "retained": row_retained,
                "retained_rate": row_retained_rate,
                "payment_method": payment_method,
            }
        )

    for bucket in services.values():
        bucket["retained"] = bucket["revenue"] - bucket["payroll"]
        bucket["retained_rate"] = (
            round(bucket["retained"] * 100 / bucket["revenue"], 1)
            if bucket["revenue"]
            else 0.0
        )

    service_rows = sorted(
        services.values(),
        key=lambda item: (-item["revenue"], item["label"]),
    )
    diagnostics.sort(
        key=lambda item: (
            item["retained_rate"] is not None,
            item["retained_rate"] if item["retained_rate"] is not None else -10**9,
            item["retained"],
            item["revenue"],
        )
    )

    tracked_customer_revenue = new_customer_revenue + repeat_customer_revenue
    new_customer_revenue_share = (
        round(new_customer_revenue * 100 / tracked_customer_revenue, 1)
        if tracked_customer_revenue
        else 0.0
    )
    repeat_customer_revenue_share = (
        round(repeat_customer_revenue * 100 / tracked_customer_revenue, 1)
        if tracked_customer_revenue
        else 0.0
    )

    payment_rows = sorted(
        payment_methods.values(),
        key=lambda item: (-item["revenue"], item["label"]),
    )
    for payment_row in payment_rows:
        payment_row["share"] = (
            round(payment_row["revenue"] * 100 / current["revenue"], 1)
            if current["revenue"]
            else 0.0
        )

    comparison = {}
    if previous_start_at and previous_end_at:
        comparison = {
            "revenue": _report_change(current["revenue"], previous["revenue"]),
            "payroll": _report_change(current["payroll"], previous["payroll"]),
            "retained": _report_change(current["retained"], previous["retained"]),
            "avg_order": _report_change(current["avg_order"], previous["avg_order"]),
            "order_count": _report_change(current["order_count"], previous["order_count"]),
            "customer_count": _report_change(current["customer_count"], previous["customer_count"]),
        }

    return {
        "period": period,
        "period_label": period_label,
        "previous_label": previous_label,
        "comparison": comparison,
        "comparison_history_exists": comparison_history_exists,
        **current,
        "daily_labels": list(daily.keys()),
        "daily_values": list(daily.values()),
        # Keep every service in the efficiency table; only the pie chart stays top-8.
        "service_rows": service_rows,
        "service_labels": [row["label"] for row in service_rows[:8]],
        "service_values": [row["revenue"] for row in service_rows[:8]],
        "worker_rows": [dict(row) for row in worker_rows],
        "order_diagnostics": diagnostics,
        "negative_order_count": sum(1 for row in diagnostics if row["retained"] < 0),
        "negative_order_loss": sum(
            -row["retained"] for row in diagnostics if row["retained"] < 0
        ),
        "payout_gap_order_count": sum(
            1 for row in diagnostics if row["payout_gap"] > 0
        ),
        "manual_override_order_count": sum(
            1 for row in diagnostics if row["manual_override_count"] > 0
        ),
        "new_customer_revenue": new_customer_revenue,
        "new_customer_orders": new_customer_orders,
        "new_customer_revenue_share": new_customer_revenue_share,
        "repeat_customer_revenue": repeat_customer_revenue,
        "repeat_customer_orders": repeat_customer_orders,
        "repeat_customer_revenue_share": repeat_customer_revenue_share,
        "unidentified_customer_revenue": unidentified_customer_revenue,
        "unidentified_customer_orders": unidentified_customer_orders,
        "payment_rows": payment_rows,
        **cancellation,
    }


@router.get("/admin/payouts/report")
async def admin_operations_report(
    request: Request,
    period: str | None = "quarter",
):
    user = require_admin(request)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有客服後台權限。",
                "user": current_user(request),
            },
            status_code=403,
        )

    report = build_operations_report(period)
    return templates.TemplateResponse(
        request=request,
        name="admin_operations_report_v2.html",
        context={
            "title": "營運財務報表",
            "user": user,
            "report": report,
        },
    )
