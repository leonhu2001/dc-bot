from __future__ import annotations

from pathlib import Path


def replace_between(path: str, start_marker: str, end_marker: str, replacement: str) -> None:
    target = Path(path)
    source = target.read_text(encoding="utf-8")
    start = source.find(start_marker)
    if start < 0:
        raise SystemExit(f"{path}: missing start marker: {start_marker!r}")
    end = source.find(end_marker, start)
    if end < 0:
        raise SystemExit(f"{path}: missing end marker: {end_marker!r}")
    target.write_text(source[:start] + replacement.rstrip() + "\n\n" + source[end:], encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    source = target.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}: {old[:180]!r}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")


# Canonical domain rule: order salary is payable only after report approval.
Path("web/app/services/payout_report_gate.py").write_text(
    '''from __future__ import annotations

REPORT_STATUS_MISSING = "missing"
REPORT_STATUS_PENDING = "pending"
REPORT_STATUS_CHANGES_REQUESTED = "changes_requested"
REPORT_STATUS_APPROVED = "approved"

LOCKED_REPORT_LABELS = {
    REPORT_STATUS_MISSING: "未填寫報單",
    REPORT_STATUS_PENDING: "報單待審核",
    REPORT_STATUS_CHANGES_REQUESTED: "報單需修改",
}


def normalize_report_status(value) -> str:
    status = str(value or "").strip().lower()
    if status in {
        REPORT_STATUS_MISSING,
        REPORT_STATUS_PENDING,
        REPORT_STATUS_CHANGES_REQUESTED,
        REPORT_STATUS_APPROVED,
    }:
        return status
    return REPORT_STATUS_MISSING


def payout_financial_state(*, payout_status, report_status=None, report_required: bool = False) -> str:
    """Return paid/unpaid/locked without mutating the stored payout status."""
    if str(payout_status or "").strip().lower() == "paid":
        return "paid"
    if report_required and normalize_report_status(report_status) != REPORT_STATUS_APPROVED:
        return "locked"
    return "unpaid"


def payout_status_label(*, payout_status, report_status=None, report_required: bool = False) -> str:
    state = payout_financial_state(
        payout_status=payout_status,
        report_status=report_status,
        report_required=report_required,
    )
    if state == "paid":
        return "已發放"
    if state == "unpaid":
        return "待發放"
    return LOCKED_REPORT_LABELS.get(normalize_report_status(report_status), "未填寫報單")
''',
    encoding="utf-8",
)

router = "web/app/routers/admin_payout_summary.py"
replace_once(
    router,
    "from web.app.services.payout_notifications import send_payout_paid_notification\n",
    "from web.app.services.payout_notifications import send_payout_paid_notification\n"
    "from web.app.services.payout_report_gate import payout_financial_state, payout_status_label\n",
)

replace_between(
    router,
    "def normalize_payout_status(",
    "def payout_order_date_expr(",
    '''def normalize_payout_status(status: str | None) -> str:
    status = str(status or "unpaid").strip()
    if status in {"paid", "已發放", "已支付"}:
        return "paid"
    if status in {"locked", "報單鎖定", "未填寫報單"}:
        return "locked"
    if status in {"all", "全部", "全部狀態"}:
        return "all"
    return "unpaid"''',
)

replace_between(
    router,
    "def add_person(",
    "def finalize_people(",
    '''def add_person(
    people: dict[str, dict],
    *,
    discord_id,
    display_name,
    role,
    amount,
    order_no,
    category,
    item,
    payout_status,
    customer_name=None,
    closed_at=None,
    item_role_label=None,
    report_status=None,
    report_required: bool = False,
    filter_status: str = "all",
) -> None:
    discord_id = str(discord_id or "").strip()
    if not discord_id:
        return

    stored_status = "paid" if str(payout_status or "") == "paid" else "unpaid"
    financial_state = payout_financial_state(
        payout_status=stored_status,
        report_status=report_status,
        report_required=report_required,
    )
    filter_status = normalize_payout_status(filter_status)
    if filter_status != "all" and financial_state != filter_status:
        return

    if discord_id not in people:
        people[discord_id] = {
            "discord_id": discord_id,
            "display_name": display_name or discord_id,
            "roles": set(),
            "role_label": "人員",
            "unpaid_total": 0,
            "unpaid_count": 0,
            "locked_total": 0,
            "locked_count": 0,
            "paid_total": 0,
            "paid_count": 0,
            "items": [],
        }

    person = people[discord_id]
    if display_name and person["display_name"] == discord_id:
        person["display_name"] = display_name

    person["roles"].add(role)
    amount = int(amount or 0)
    if financial_state == "paid":
        person["paid_total"] += amount
        person["paid_count"] += 1
    elif financial_state == "locked":
        person["locked_total"] += amount
        person["locked_count"] += 1
    else:
        person["unpaid_total"] += amount
        person["unpaid_count"] += 1

    closed_text = str(closed_at or "").strip()
    person["items"].append(
        {
            "order_no": order_no,
            "category": category or "",
            "item": item or "",
            "customer_name": str(customer_name or "").strip() or "未紀錄",
            "closed_date": closed_text[:10] if closed_text else "未紀錄",
            "role": item_role_label or ("護航 / 陪玩" if role == "worker" else "客服"),
            "amount": amount,
            "payout_status": stored_status,
            "financial_state": financial_state,
            "report_status": str(report_status or ""),
            "status_label": payout_status_label(
                payout_status=stored_status,
                report_status=report_status,
                report_required=report_required,
            ),
        }
    )''',
)

replace_between(
    router,
    "def finalize_people(",
    "def _adjustment_role_sql(",
    '''def finalize_people(
    people: dict[str, dict],
    q: str | None,
    status: str | None = "unpaid",
) -> list[dict]:
    keyword = str(q or "").strip().lower()
    status = normalize_payout_status(status)
    rows: list[dict] = []

    for person in people.values():
        roles = person.pop("roles", set())
        if roles == {"worker"}:
            person["role_label"] = "護航 / 陪玩"
            person["role"] = "worker"
        elif roles == {"customer_service"}:
            person["role_label"] = "客服"
            person["role"] = "customer_service"
        elif roles:
            person["role_label"] = "混合"
            person["role"] = "all"
        else:
            person["role"] = "all"

        if status == "paid":
            if int(person.get("paid_count") or 0) <= 0:
                continue
            person["display_total"] = person["paid_total"]
            person["display_count"] = person["paid_count"]
            person["display_status"] = "已發放"
        elif status == "locked":
            if int(person.get("locked_count") or 0) <= 0:
                continue
            person["display_total"] = person["locked_total"]
            person["display_count"] = person["locked_count"]
            person["display_status"] = "報單鎖定"
        elif status == "all":
            total = (
                int(person.get("paid_total") or 0)
                + int(person.get("unpaid_total") or 0)
                + int(person.get("locked_total") or 0)
            )
            count = (
                int(person.get("paid_count") or 0)
                + int(person.get("unpaid_count") or 0)
                + int(person.get("locked_count") or 0)
            )
            if total <= 0 and count <= 0:
                continue
            person["display_total"] = total
            person["display_count"] = count
            person["display_status"] = "全部"
        else:
            if int(person.get("unpaid_count") or 0) <= 0:
                continue
            person["display_total"] = person["unpaid_total"]
            person["display_count"] = person["unpaid_count"]
            person["display_status"] = "待發放"

        person["items"].sort(
            key=lambda item: (str(item.get("closed_date") or ""), str(item.get("order_no") or "")),
            reverse=True,
        )

        if keyword:
            haystack = f'{person["display_name"]} {person["discord_id"]}'.lower()
            if keyword not in haystack:
                continue
        rows.append(person)

    return sorted(
        rows,
        key=lambda row: (-int(row.get("display_total") or 0), str(row.get("display_name") or "")),
    )''',
)

replace_between(
    router,
    "def fetch_rows(",
    "def _audit_payout_state(",
    '''def fetch_rows(
    month: str | None,
    role: str | None,
    q: str | None,
    status: str | None = "unpaid",
):
    ensure_worker_tip_table()
    ensure_internal_transfer_tables(db_path())
    role = normalize_role(role)
    status = normalize_payout_status(status)
    people: dict[str, dict] = {}

    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row

    db_payout_status = None
    if status == "paid":
        db_payout_status = "paid"
    elif status in {"unpaid", "locked"}:
        db_payout_status = "unpaid"

    payout_status_sql = ""
    payout_status_params: list[str] = []
    if db_payout_status:
        payout_status_sql = " AND p.payout_status = ? "
        payout_status_params.append(db_payout_status)

    try:
        if role in {"all", "worker"}:
            month_sql, params = month_filter_sql(month, "w")
            rows = conn.execute(
                f"""
                SELECT
                    p.worker_discord_id AS discord_id,
                    p.worker_display_name AS display_name,
                    p.final_payout AS amount,
                    p.payout_status AS payout_status,
                    COALESCE(r.status, 'missing') AS report_status,
                    w.bot_order_no,
                    w.id AS web_order_id,
                    w.category,
                    w.item,
                    COALESCE(NULLIF(w.customer_display_name, ''), NULLIF(w.customer_discord_id, ''), '未紀錄') AS customer_name,
                    {payout_order_date_expr('w')} AS closed_at
                FROM worker_payouts p
                JOIN web_orders w ON w.id = p.order_id
                LEFT JOIN order_reports r ON r.order_id = w.id
                WHERE w.status = 'closed'
                  AND COALESCE(p.final_payout, 0) > 0
                  {payout_status_sql}
                  {month_sql}
                ORDER BY p.id DESC
                """,
                [*payout_status_params, *params],
            ).fetchall()
            for row in rows:
                add_person(
                    people,
                    discord_id=row["discord_id"],
                    display_name=row["display_name"],
                    role="worker",
                    amount=row["amount"],
                    payout_status=row["payout_status"],
                    report_status=row["report_status"],
                    report_required=True,
                    filter_status=status,
                    customer_name=row["customer_name"],
                    closed_at=row["closed_at"],
                    order_no=row["bot_order_no"] or f"WEB-{row['web_order_id']}",
                    category=row["category"],
                    item=row["item"],
                )

            tip_rows = conn.execute(
                f"""
                SELECT
                    p.worker_discord_id AS discord_id,
                    p.worker_display_name AS display_name,
                    p.amount AS amount,
                    p.payout_status AS payout_status,
                    w.bot_order_no,
                    w.id AS web_order_id,
                    w.category,
                    w.item,
                    COALESCE(NULLIF(w.customer_display_name, ''), NULLIF(w.customer_discord_id, ''), '未紀錄') AS customer_name,
                    {payout_order_date_expr('w')} AS closed_at
                FROM worker_tips p
                JOIN web_orders w ON w.id = p.order_id
                WHERE w.status = 'closed'
                  AND p.payment_status = 'paid'
                  AND COALESCE(p.amount, 0) > 0
                  {payout_status_sql}
                  {month_sql}
                ORDER BY p.id DESC
                """,
                [*payout_status_params, *params],
            ).fetchall()
            for row in tip_rows:
                add_person(
                    people,
                    discord_id=row["discord_id"],
                    display_name=row["display_name"],
                    role="worker",
                    amount=row["amount"],
                    payout_status=row["payout_status"],
                    filter_status=status,
                    customer_name=row["customer_name"],
                    closed_at=row["closed_at"],
                    order_no=row["bot_order_no"] or f"WEB-{row['web_order_id']}",
                    category=row["category"],
                    item=row["item"],
                    item_role_label="🍗 雞腿",
                )

        if role in {"all", "customer_service"}:
            month_sql, params = month_filter_sql(month, "w")
            rows = conn.execute(
                f"""
                SELECT
                    p.customer_service_discord_id AS discord_id,
                    p.customer_service_display_name AS display_name,
                    p.payout_amount AS amount,
                    p.payout_status AS payout_status,
                    COALESCE(r.status, 'missing') AS report_status,
                    w.bot_order_no,
                    w.id AS web_order_id,
                    w.category,
                    w.item,
                    COALESCE(NULLIF(w.customer_display_name, ''), NULLIF(w.customer_discord_id, ''), '未紀錄') AS customer_name,
                    {payout_order_date_expr('w')} AS closed_at
                FROM customer_service_payouts p
                JOIN web_orders w ON w.id = p.order_id
                LEFT JOIN order_reports r ON r.order_id = w.id
                WHERE w.status = 'closed'
                  AND COALESCE(p.customer_service_discord_id, '') <> ''
                  AND COALESCE(p.customer_service_discord_id, '') <> 'demo_customer_service'
                  AND COALESCE(p.customer_service_display_name, '') <> '測試客服'
                  AND COALESCE(p.payout_amount, 0) > 0
                  {payout_status_sql}
                  {month_sql}
                ORDER BY p.id DESC
                """,
                [*payout_status_params, *params],
            ).fetchall()
            for row in rows:
                add_person(
                    people,
                    discord_id=row["discord_id"],
                    display_name=row["display_name"],
                    role="customer_service",
                    amount=row["amount"],
                    payout_status=row["payout_status"],
                    report_status=row["report_status"],
                    report_required=True,
                    filter_status=status,
                    customer_name=row["customer_name"],
                    closed_at=row["closed_at"],
                    order_no=row["bot_order_no"] or f"WEB-{row['web_order_id']}",
                    category=row["category"],
                    item=row["item"],
                )

        adjustment_status_sql = ""
        adjustment_status_params: list[str] = []
        if db_payout_status:
            adjustment_status_sql = " AND a.payout_status = ? "
            adjustment_status_params.append(db_payout_status)

        adjustment_month_sql = ""
        adjustment_month_params: list[str] = []
        month_value = str(month or "").strip()
        if month_value:
            adjustment_month_sql = " AND substr(a.effective_at, 1, 7) = ? "
            adjustment_month_params.append(month_value)

        adjustment_rows = conn.execute(
            f"""
            SELECT
                a.transfer_id,
                a.employee_discord_id AS discord_id,
                COALESCE(NULLIF(a.employee_display_name, ''), a.employee_discord_id) AS display_name,
                a.counterparty_display_name,
                a.direction,
                a.amount,
                a.reason,
                a.payout_status,
                a.effective_at,
                COALESCE(m.is_customer_service, 0) AS is_customer_service,
                COALESCE(m.is_worker, 0) AS is_worker,
                COALESCE(m.is_companion, 0) AS is_companion
            FROM employee_payroll_adjustments a
            LEFT JOIN web_staff_members m
              ON CAST(m.discord_id AS TEXT) = CAST(a.employee_discord_id AS TEXT)
            WHERE 1 = 1
              {adjustment_status_sql}
              {adjustment_month_sql}
              {_adjustment_role_sql(role)}
            ORDER BY a.effective_at DESC, a.id DESC
            """,
            [*adjustment_status_params, *adjustment_month_params],
        ).fetchall()

        for row in adjustment_rows:
            is_cs = bool(int(row["is_customer_service"] or 0))
            is_worker = bool(int(row["is_worker"] or 0) or int(row["is_companion"] or 0))
            role_key = "customer_service" if is_cs and not is_worker else "worker"
            counterparty = str(row["counterparty_display_name"] or "內部員工")
            direction = str(row["direction"] or "")
            label = f"轉入｜來自 {counterparty}" if direction == "incoming" else f"轉出｜給 {counterparty}"
            reason = str(row["reason"] or "").strip()
            if reason:
                label += f"｜{reason}"

            add_person(
                people,
                discord_id=row["discord_id"],
                display_name=row["display_name"],
                role=role_key,
                amount=row["amount"],
                payout_status=row["payout_status"],
                filter_status=status,
                customer_name=counterparty,
                closed_at=row["effective_at"],
                order_no=f"內部轉帳 #{int(row['transfer_id'])}",
                category="內部轉帳",
                item=label,
                item_role_label="內部轉帳",
            )
            if str(row["discord_id"]) in people and is_cs and is_worker:
                people[str(row["discord_id"])]["roles"].add("customer_service")

    finally:
        conn.close()

    rows = finalize_people(people, q, status)
    totals = {
        "person_count": len(rows),
        "unpaid_total": sum(int(row.get("unpaid_total") or 0) for row in rows),
        "unpaid_count": sum(int(row.get("unpaid_count") or 0) for row in rows),
        "locked_total": sum(int(row.get("locked_total") or 0) for row in rows),
        "locked_count": sum(int(row.get("locked_count") or 0) for row in rows),
        "paid_total": sum(int(row.get("paid_total") or 0) for row in rows),
        "paid_count": sum(int(row.get("paid_count") or 0) for row in rows),
        "display_total": sum(int(row.get("display_total") or 0) for row in rows),
        "display_count": sum(int(row.get("display_count") or 0) for row in rows),
    }
    return rows, totals''',
)

replace_between(
    router,
    "def _audit_payout_state(",
    "def get_summary_month_options(",
    '''def _audit_payout_state(
    month: str | None,
    role: str | None,
    *,
    person_id: str | None = None,
) -> dict:
    rows, totals = fetch_rows(month, role, "", "all")
    person_value = str(person_id or "").strip()
    if person_value:
        rows = [row for row in rows if str(row.get("discord_id") or "") == person_value]
        totals = {
            "person_count": len(rows),
            "unpaid_total": sum(int(row.get("unpaid_total") or 0) for row in rows),
            "unpaid_count": sum(int(row.get("unpaid_count") or 0) for row in rows),
            "locked_total": sum(int(row.get("locked_total") or 0) for row in rows),
            "locked_count": sum(int(row.get("locked_count") or 0) for row in rows),
            "paid_total": sum(int(row.get("paid_total") or 0) for row in rows),
            "paid_count": sum(int(row.get("paid_count") or 0) for row in rows),
        }
    return {
        "month": str(month or "").strip() or "全部月份",
        "role": str(role or "all").strip(),
        "person_id": person_value or None,
        "totals": totals,
        "people": [
            {
                "discord_id": row.get("discord_id"),
                "display_name": row.get("display_name"),
                "unpaid_total": int(row.get("unpaid_total") or 0),
                "locked_total": int(row.get("locked_total") or 0),
                "paid_total": int(row.get("paid_total") or 0),
            }
            for row in rows
        ],
    }''',
)

replace_between(
    router,
    "def update_summary_payout_status(",
    "def update_summary_person_payout_status(",
    '''def update_summary_payout_status(
    month: str | None,
    role: str | None,
    target_status: str,
) -> None:
    ensure_worker_tip_table()
    ensure_internal_transfer_tables(db_path())
    month = normalize_summary_month(month)
    role = str(role or "all").strip()
    target_status = "paid" if target_status == "paid" else "unpaid"
    paid_at_sql = "datetime('now', '+8 hours')" if target_status == "paid" else "NULL"

    conn = sqlite3.connect(summary_db_path())
    try:
        order_filter = "w.status = 'closed'"
        params: list[str] = []
        if month:
            order_filter += (
                " AND substr(COALESCE(NULLIF(w.closed_at, ''), "
                "NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')), 1, 7) = ?"
            )
            params.append(month)
        salary_order_filter = order_filter
        if target_status == "paid":
            salary_order_filter += (
                " AND EXISTS (SELECT 1 FROM order_reports r "
                "WHERE r.order_id = w.id AND r.status = 'approved')"
            )

        if role in {"all", "", "worker", "護航 / 陪玩"}:
            conn.execute(
                f"""
                UPDATE worker_payouts
                SET payout_status = ?, paid_at = {paid_at_sql}
                WHERE order_id IN (
                    SELECT w.id FROM web_orders w WHERE {salary_order_filter}
                )
                """,
                [target_status, *params],
            )
            conn.execute(
                f"""
                UPDATE worker_tips
                SET payout_status = ?,
                    payout_paid_at = {paid_at_sql},
                    updated_at = datetime('now', '+8 hours')
                WHERE payment_status = 'paid'
                  AND order_id IN (
                    SELECT w.id FROM web_orders w WHERE {order_filter}
                  )
                """,
                [target_status, *params],
            )

        if role in {"all", "", "customer_service", "客服"}:
            conn.execute(
                f"""
                UPDATE customer_service_payouts
                SET payout_status = ?, paid_at = {paid_at_sql}
                WHERE order_id IN (
                    SELECT w.id FROM web_orders w WHERE {salary_order_filter}
                )
                  AND COALESCE(customer_service_discord_id, '') <> ''
                  AND COALESCE(customer_service_discord_id, '') <> 'demo_customer_service'
                  AND COALESCE(customer_service_display_name, '') <> '測試客服'
                """,
                [target_status, *params],
            )
        conn.commit()
    finally:
        conn.close()

    mark_bulk_adjustments(
        target_status=target_status,
        month=month,
        role=role,
    )''',
)

replace_between(
    router,
    "def update_summary_person_payout_status(",
    "def build_combined_summary_rows(",
    '''def update_summary_person_payout_status(
    month: str,
    person_role: str,
    person_id: str,
    target_status: str,
):
    ensure_worker_tip_table()
    ensure_internal_transfer_tables(db_path())
    person_id = str(person_id or "").strip()
    if not person_id:
        return

    target_status = "paid" if str(target_status or "").strip() == "paid" else "unpaid"
    paid_at_sql = "datetime('now', '+8 hours')" if target_status == "paid" else "NULL"
    role_text = str(person_role or "").strip().lower()

    update_worker = role_text in {
        "worker", "護航 / 陪玩", "worker_payout", "護航 / 陪玩分潤",
        "mixed", "mix", "both", "hybrid", "混合", "混合身分",
        "客服 / 護航", "護航 / 客服", "總控 / 客服 / 護航",
    }
    update_customer_service = role_text in {
        "customer_service", "customer-service", "cs", "客服", "魔丸♫客服分潤",
        "mixed", "mix", "both", "hybrid", "混合", "混合身分",
        "客服 / 護航", "護航 / 客服", "總控 / 客服 / 護航",
    }
    if not update_worker and not update_customer_service:
        update_worker = True
        update_customer_service = True

    conn = sqlite3.connect(db_path())
    try:
        order_filter = "w.status = 'closed'"
        params_worker: list[str] = [target_status, person_id]
        params_cs: list[str] = [target_status, person_id]
        if month:
            order_filter += (
                " AND substr(COALESCE(NULLIF(w.closed_at, ''), "
                "NULLIF(w.updated_at, ''), NULLIF(w.created_at, '')), 1, 7) = ?"
            )
            params_worker.append(month)
            params_cs.append(month)
        salary_order_filter = order_filter
        if target_status == "paid":
            salary_order_filter += (
                " AND EXISTS (SELECT 1 FROM order_reports r "
                "WHERE r.order_id = w.id AND r.status = 'approved')"
            )

        if update_worker:
            conn.execute(
                f"""
                UPDATE worker_payouts
                SET payout_status = ?, paid_at = {paid_at_sql}
                WHERE worker_discord_id = ?
                  AND order_id IN (
                    SELECT w.id FROM web_orders w WHERE {salary_order_filter}
                  )
                """,
                params_worker,
            )
            conn.execute(
                f"""
                UPDATE worker_tips
                SET payout_status = ?,
                    payout_paid_at = {paid_at_sql},
                    updated_at = datetime('now', '+8 hours')
                WHERE payment_status = 'paid'
                  AND worker_discord_id = ?
                  AND order_id IN (
                    SELECT w.id FROM web_orders w WHERE {order_filter}
                  )
                """,
                params_worker,
            )

        if update_customer_service:
            conn.execute(
                f"""
                UPDATE customer_service_payouts
                SET payout_status = ?, paid_at = {paid_at_sql}
                WHERE customer_service_discord_id = ?
                  AND order_id IN (
                    SELECT w.id FROM web_orders w WHERE {salary_order_filter}
                  )
                """,
                params_cs,
            )
        conn.commit()
    finally:
        conn.close()

    mark_employee_adjustments(
        employee_discord_id=person_id,
        target_status=target_status,
        month=month,
    )''',
)

replace_between(
    router,
    "def build_combined_summary_rows(",
    "def attach_staff_avatars_to_summary_rows(",
    '''def build_combined_summary_rows(
    unpaid_rows: list[dict],
    paid_rows: list[dict],
    locked_rows: list[dict] | None = None,
) -> list[dict]:
    combined: dict[tuple[str, str], dict] = {}

    def as_number(value) -> float:
        try:
            return float(value or 0)
        except Exception:
            return 0

    def as_int(value) -> int:
        try:
            return int(value or 0)
        except Exception:
            return 0

    def get_value(row, key, default=None):
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)

    def ensure_row(row) -> dict:
        role = str(get_value(row, "role", "") or "")
        discord_id = str(get_value(row, "discord_id", "") or "")
        key = (role, discord_id)
        if key not in combined:
            combined[key] = {
                "role": role,
                "role_label": get_value(row, "role_label", role or "人員"),
                "discord_id": discord_id,
                "display_name": get_value(row, "display_name", discord_id or "未知人員"),
                "unpaid_total": 0,
                "locked_total": 0,
                "paid_total": 0,
                "unpaid_count": 0,
                "locked_count": 0,
                "paid_count": 0,
                "items": [],
            }
        return combined[key]

    for row in unpaid_rows or []:
        target = ensure_row(row)
        target["unpaid_total"] += as_number(get_value(row, "display_total", get_value(row, "unpaid_total", 0)))
        target["unpaid_count"] += as_int(get_value(row, "unpaid_count", 0))
        target["items"].extend(list(get_value(row, "items", []) or []))

    for row in locked_rows or []:
        target = ensure_row(row)
        target["locked_total"] += as_number(get_value(row, "display_total", get_value(row, "locked_total", 0)))
        target["locked_count"] += as_int(get_value(row, "locked_count", 0))
        target["items"].extend(list(get_value(row, "items", []) or []))

    for row in paid_rows or []:
        target = ensure_row(row)
        target["paid_total"] += as_number(get_value(row, "paid_total", 0))
        target["paid_count"] += as_int(get_value(row, "paid_count", 0))
        target["items"].extend(list(get_value(row, "items", []) or []))

    rows = list(combined.values())
    for row in rows:
        row["total_count"] = (
            int(row["unpaid_count"] or 0)
            + int(row["locked_count"] or 0)
            + int(row["paid_count"] or 0)
        )
        if row["locked_count"]:
            row["summary_status"] = "部分鎖定" if row["unpaid_count"] or row["paid_count"] else "報單鎖定"
            row["summary_status_class"] = "unpaid"
        elif row["unpaid_count"] and row["paid_count"]:
            row["summary_status"] = "部分待發放"
            row["summary_status_class"] = "partial"
        elif row["unpaid_count"]:
            row["summary_status"] = "待發放"
            row["summary_status_class"] = "unpaid"
        else:
            row["summary_status"] = "正常"
            row["summary_status_class"] = "paid"
        row["items"].sort(
            key=lambda item: (str(item.get("closed_date") or ""), str(item.get("order_no") or "")),
            reverse=True,
        )

    rows.sort(
        key=lambda row: (
            int(row.get("unpaid_count") or 0) <= 0,
            int(row.get("locked_count") or 0) <= 0,
            -float(row.get("unpaid_total") or 0),
            -float(row.get("locked_total") or 0),
            str(row.get("display_name") or ""),
        )
    )
    return rows''',
)

replace_once(
    router,
    '''    rows, totals = fetch_rows(month, role, q, status)\n    unpaid_rows, unpaid_totals = fetch_rows(month, role, q, "unpaid")\n    paid_rows, paid_totals = fetch_rows(month, role, q, "paid")\n    summary_rows = build_combined_summary_rows(unpaid_rows, paid_rows)\n''',
    '''    rows, totals = fetch_rows(month, role, q, status)\n    unpaid_rows, unpaid_totals = fetch_rows(month, role, q, "unpaid")\n    locked_rows, locked_totals = fetch_rows(month, role, q, "locked")\n    paid_rows, paid_totals = fetch_rows(month, role, q, "paid")\n    summary_rows = build_combined_summary_rows(unpaid_rows, paid_rows, locked_rows)\n''',
)
replace_once(
    router,
    '''            "unpaid_rows": unpaid_rows,\n            "paid_rows": paid_rows,\n            "unpaid_totals": unpaid_totals,\n            "paid_totals": paid_totals,\n''',
    '''            "unpaid_rows": unpaid_rows,\n            "locked_rows": locked_rows,\n            "paid_rows": paid_rows,\n            "unpaid_totals": unpaid_totals,\n            "locked_totals": locked_totals,\n            "paid_totals": paid_totals,\n''',
)

# Payout summary UI: payable, locked and paid are visibly separate.
template = "web/app/templates/admin_payout_summary.html"
replace_between(
    template,
    '    <section class="staff-summary-total-grid">',
    '    <section class="staff-summary-ledger-panel">',
    '''    <section class="staff-summary-total-grid">
        <div class="staff-summary-total-card mw-r56-payout-metric">
            <span>待發放總額 ◆</span>
            <strong class="mw-r56-payout-value">{{ unpaid_totals.display_total|default(unpaid_totals.unpaid_total)|round(0, 'common')|int }}</strong>
            <small>可發放 {{ unpaid_totals.display_count|default(unpaid_totals.unpaid_count) }} 筆</small>
        </div>

        <div class="staff-summary-total-card mw-r56-payout-metric">
            <span>報單鎖定總額 ◆</span>
            <strong class="mw-r56-payout-value">{{ locked_totals.display_total|default(locked_totals.locked_total)|round(0, 'common')|int }}</strong>
            <small>鎖定 {{ locked_totals.display_count|default(locked_totals.locked_count) }} 筆</small>
        </div>

        <div class="staff-summary-total-card mw-r56-payout-metric">
            <span>已發放總額 ◆</span>
            <strong class="mw-r56-payout-value">{{ paid_totals.paid_total|round(0, 'common')|int }}</strong>
            <small>本期已發放 {{ paid_totals.paid_count }} 筆</small>
        </div>

        <div class="staff-summary-total-card mw-r56-payout-metric">
            <span>薪資筆數 ◆</span>
            <strong class="mw-r56-payout-value">{{ unpaid_totals.unpaid_count + locked_totals.locked_count + paid_totals.paid_count }}</strong>
            <small>待 {{ unpaid_totals.unpaid_count }} / 鎖 {{ locked_totals.locked_count }} / 已 {{ paid_totals.paid_count }}</small>
        </div>
    </section>''',
)
replace_once(template, "                            <th>未發放</th>\n                            <th>已發放</th>", "                            <th>待發放</th>\n                            <th>報單鎖定</th>\n                            <th>已發放</th>")
replace_once(
    template,
    '''                                <td>\n                                    <span class="staff-money">{{ row.unpaid_total|round(0, 'common')|int }}T</span>\n                                </td>\n\n                                <td>\n                                    <span class="staff-money">{{ row.paid_total|round(0, 'common')|int }}T</span>\n                                </td>''',
    '''                                <td>\n                                    <span class="staff-money">{{ row.unpaid_total|round(0, 'common')|int }}T</span>\n                                </td>\n\n                                <td>\n                                    <span class="staff-money">{{ row.locked_total|round(0, 'common')|int }}T</span>\n                                </td>\n\n                                <td>\n                                    <span class="staff-money">{{ row.paid_total|round(0, 'common')|int }}T</span>\n                                </td>''',
)
replace_once(template, '<span class="staff-count-sub">未 {{ row.unpaid_count }} / 已 {{ row.paid_count }}</span>', '<span class="staff-count-sub">待 {{ row.unpaid_count }} / 鎖 {{ row.locked_count }} / 已 {{ row.paid_count }}</span>')
replace_once(
    template,
    '<button class="staff-summary-button primary" type="submit" name="target_status" value="paid">已發放</button>',
    '''{% if row.unpaid_count > 0 %}\n                                                    <button class="staff-summary-button primary" type="submit" name="target_status" value="paid">已發放</button>\n                                                {% else %}\n                                                    <button class="staff-summary-button primary" type="button" disabled title="報單尚未審核通過，薪資目前鎖定">已發放（鎖定）</button>\n                                                {% endif %}''',
)
replace_once(template, '<td colspan="7">', '<td colspan="8">')
replace_once(
    template,
    '''                                                            {% if item.payout_status == "paid" %}\n                                                                <span class="staff-ledger-stamp paid">已發放</span>\n                                                            {% else %}\n                                                                <span class="staff-ledger-stamp unpaid">未發放</span>\n                                                            {% endif %}''',
    '''                                                            {% if item.financial_state == "paid" %}\n                                                                <span class="staff-ledger-stamp paid">{{ item.status_label }}</span>\n                                                            {% else %}\n                                                                <span class="staff-ledger-stamp unpaid">{{ item.status_label }}</span>\n                                                            {% endif %}''',
)

# Regression coverage for domain state and actual DB update guard.
Path("tests/test_payout_report_gate.py").write_text(
    '''from __future__ import annotations

import sqlite3

from web.app.services.payout_report_gate import payout_financial_state, payout_status_label


def test_order_salary_requires_approved_report_before_becoming_payable():
    assert payout_financial_state(payout_status="unpaid", report_status="missing", report_required=True) == "locked"
    assert payout_status_label(payout_status="unpaid", report_status="missing", report_required=True) == "未填寫報單"
    assert payout_status_label(payout_status="unpaid", report_status="pending", report_required=True) == "報單待審核"
    assert payout_status_label(payout_status="unpaid", report_status="changes_requested", report_required=True) == "報單需修改"
    assert payout_financial_state(payout_status="unpaid", report_status="approved", report_required=True) == "unpaid"
    assert payout_status_label(payout_status="unpaid", report_status="approved", report_required=True) == "待發放"
    assert payout_financial_state(payout_status="paid", report_status="missing", report_required=True) == "paid"


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE web_orders (
            id INTEGER PRIMARY KEY,
            bot_order_no TEXT,
            status TEXT,
            category TEXT,
            item TEXT,
            customer_display_name TEXT,
            customer_discord_id TEXT,
            created_at TEXT,
            updated_at TEXT,
            closed_at TEXT
        );
        CREATE TABLE worker_payouts (
            id INTEGER PRIMARY KEY,
            order_id INTEGER,
            worker_discord_id TEXT,
            worker_display_name TEXT,
            final_payout INTEGER,
            payout_status TEXT,
            paid_at TEXT
        );
        CREATE TABLE worker_tips (
            id INTEGER PRIMARY KEY,
            order_id INTEGER,
            worker_discord_id TEXT,
            worker_display_name TEXT,
            amount INTEGER,
            payment_status TEXT,
            payout_status TEXT,
            payout_paid_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE customer_service_payouts (
            id INTEGER PRIMARY KEY,
            order_id INTEGER,
            customer_service_discord_id TEXT,
            customer_service_display_name TEXT,
            payout_amount INTEGER,
            payout_status TEXT,
            paid_at TEXT
        );
        CREATE TABLE order_reports (order_id INTEGER PRIMARY KEY, status TEXT);
        CREATE TABLE employee_payroll_adjustments (
            id INTEGER PRIMARY KEY,
            transfer_id INTEGER,
            employee_discord_id TEXT,
            employee_display_name TEXT,
            counterparty_display_name TEXT,
            direction TEXT,
            amount INTEGER,
            reason TEXT,
            payout_status TEXT,
            effective_at TEXT
        );
        CREATE TABLE web_staff_members (
            discord_id TEXT PRIMARY KEY,
            is_customer_service INTEGER,
            is_worker INTEGER,
            is_companion INTEGER
        );
        """
    )
    conn.execute(
        "INSERT INTO web_orders VALUES (1, 'MO-1', 'closed', '三角洲', '技術陪', '老闆', '9', '2026-10-14', '2026-10-14', '2026-10-14')"
    )
    conn.execute(
        "INSERT INTO worker_payouts VALUES (1, 1, '123', '測試陪玩', 500, 'unpaid', NULL)"
    )
    conn.execute("INSERT INTO order_reports VALUES (1, 'missing')")
    conn.commit()
    conn.close()


def test_individual_paid_action_cannot_release_report_locked_salary(tmp_path, monkeypatch):
    from web.app.routers import admin_payout_summary as payout

    db = tmp_path / "payout.db"
    _make_db(db)
    monkeypatch.setattr(payout, "db_path", lambda: str(db))
    monkeypatch.setattr(payout, "summary_db_path", lambda: str(db))
    monkeypatch.setattr(payout, "ensure_worker_tip_table", lambda: None)
    monkeypatch.setattr(payout, "ensure_internal_transfer_tables", lambda *args, **kwargs: None)
    monkeypatch.setattr(payout, "mark_employee_adjustments", lambda **kwargs: None)

    locked_rows, locked_totals = payout.fetch_rows("2026-10", "worker", "", "locked")
    unpaid_rows, unpaid_totals = payout.fetch_rows("2026-10", "worker", "", "unpaid")
    assert locked_totals["locked_count"] == 1
    assert locked_rows[0]["items"][0]["status_label"] == "未填寫報單"
    assert unpaid_totals["unpaid_count"] == 0
    assert unpaid_rows == []

    payout.update_summary_person_payout_status("2026-10", "worker", "123", "paid")
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT payout_status FROM worker_payouts WHERE id=1").fetchone()[0] == "unpaid"
    conn.execute("UPDATE order_reports SET status='approved' WHERE order_id=1")
    conn.commit()
    conn.close()

    unpaid_rows, unpaid_totals = payout.fetch_rows("2026-10", "worker", "", "unpaid")
    assert unpaid_totals["unpaid_count"] == 1
    assert unpaid_rows[0]["items"][0]["status_label"] == "待發放"

    payout.update_summary_person_payout_status("2026-10", "worker", "123", "paid")
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT payout_status FROM worker_payouts WHERE id=1").fetchone()[0] == "paid"
    finally:
        conn.close()


def test_payout_summary_template_exposes_report_lock_state():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "web/app/templates/admin_payout_summary.html").read_text(encoding="utf-8")
    assert "報單鎖定" in source
    assert "已發放（鎖定）" in source
    assert "item.status_label" in source
''',
    encoding="utf-8",
)

print("payout report gate repair applied")
