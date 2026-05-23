from pathlib import Path
import re

GROUPED_PY = Path("web/app/routers/admin_payouts_grouped.py")
GROUPED_HTML = Path("web/app/templates/admin_payouts_grouped.html")
ORDER_SERVICE = Path("web/app/services/order_service.py")

py = GROUPED_PY.read_text(encoding="utf-8")
html = GROUPED_HTML.read_text(encoding="utf-8")
service = ORDER_SERVICE.read_text(encoding="utf-8")

# 1. 月結查詢只抓 closed 訂單
py = re.sub(
    r"WHERE 1 = 1\s*\n\s*\{month_sql\}\s*\n\s*\{status_sql\}",
    "WHERE o.status = 'closed'\n            {month_sql}\n            {status_sql}",
    py,
)

# 2. group_rows 改成同 Discord ID 合併，不再用身份拆分
new_group_rows = r'''def group_rows(rows: list[dict]) -> list[dict]:
    """同一 Discord ID 合併統計，不分客服/打手拆列。"""
    grouped: dict[str, dict] = {}

    for row in rows:
        person_id = str(row["person_id"] or "").strip()
        key = person_id or str(row["person_name"] or "").strip()

        if key not in grouped:
            grouped[key] = {
                "payout_role": "person",
                "role_label": "人員",
                "roles": set(),
                "person_id": row["person_id"],
                "person_name": row["person_name"],
                "unpaid_total": 0,
                "paid_total": 0,
                "all_total": 0,
                "count": 0,
                "rows": [],
            }

        group = grouped[key]
        group["roles"].add(row["payout_role"])

        if not group.get("person_name") or str(group["person_name"]) == person_id:
            group["person_name"] = row["person_name"]

        amount = int(row["final_amount"] or 0)
        group["all_total"] += amount
        group["count"] += 1
        group["rows"].append(row)

        if row["payout_status"] == "paid":
            group["paid_total"] += amount
        else:
            group["unpaid_total"] += amount

    result = []

    for group in grouped.values():
        roles = set(group.pop("roles", set()))

        if roles == {"worker"}:
            group["role_label"] = "打手"
        elif roles == {"customer_service"}:
            group["role_label"] = "客服"
        elif roles:
            group["role_label"] = "混合"

        result.append(group)

    return sorted(
        result,
        key=lambda item: str(item["person_name"] or ""),
    )
'''

py = re.sub(
    r"def group_rows\(rows: list\[dict\]\) -> list\[dict\]:[\s\S]*?\n\ndef build_summary",
    new_group_rows + "\n\ndef build_summary",
    py,
    count=1,
)

# 3. update_group_status 整段重寫：person 會同時更新客服+打手，但只更新 closed 訂單
new_update_group_status = r'''@router.post("/admin/payouts/grouped/status")
async def update_group_status(
    request: Request,
    payout_role: str = Form(...),
    person_id: str = Form(...),
    new_status: str = Form(...),
    month: str | None = Form(default=""),
    status: str | None = Form(default="unpaid"),
    role: str | None = Form(default="all"),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_grouped(error="你沒有總控後台權限。")

    payout_role = normalize_filter(payout_role, {"person", "worker", "customer_service"}, "person")
    new_status = normalize_filter(new_status, {"unpaid", "paid"}, "unpaid")
    status = normalize_filter(status, {"all", "unpaid", "paid"}, "unpaid")
    role = normalize_filter(role, {"all", "worker", "customer_service"}, "all")
    month = (month or "").strip()

    set_paid_at = "CURRENT_TIMESTAMP" if new_status == "paid" else "NULL"

    def build_update(table: str, person_col: str) -> tuple[str, list[str]]:
        conditions = [f"{person_col} = ?"]
        params: list[str] = [person_id]

        if month:
            conditions.append("strftime('%Y-%m', p.created_at) = ?")
            params.append(month)

        if status != "all":
            conditions.append("p.payout_status = ?")
            params.append(status)

        conditions.append(
            "EXISTS (SELECT 1 FROM web_orders o WHERE o.id = p.order_id AND o.status = 'closed')"
        )

        sql = f"""
            UPDATE {table} AS p
            SET payout_status = ?, paid_at = {set_paid_at}
            WHERE {' AND '.join(conditions)}
        """

        return sql, params

    targets: list[tuple[str, str]] = []

    if payout_role in {"person", "worker"}:
        targets.append(("worker_payouts", "worker_discord_id"))

    if payout_role in {"person", "customer_service"}:
        targets.append(("customer_service_payouts", "customer_service_discord_id"))

    conn = connect_db()

    try:
        changed = 0

        for table, person_col in targets:
            sql, params = build_update(table, person_col)
            cur = conn.execute(sql, [new_status, *params])
            changed += cur.rowcount

        conn.commit()
    finally:
        conn.close()

    return redirect_to_grouped(
        month=month,
        status=status,
        role=role,
        message=f"已更新 {changed} 筆分潤狀態。",
    )
'''

py = re.sub(
    r'@router\.post\("/admin/payouts/grouped/status"\)\nasync def update_group_status\([\s\S]*?\n\n(?=@router\.get|@router\.post|def |\Z)',
    new_update_group_status + "\n\n",
    py,
    count=1,
)

# 4. 模板：身份顯示 role_label，狀態中文化
html = re.sub(
    r'''<div class="person-role">\s*\{% if group\.payout_role == "worker" %\}打手\{% else %\}客服\{% endif %\}\s*</div>''',
    '<div class="person-role">{{ group.role_label }}</div>',
    html,
)

html = html.replace(
    "{{ row.payout_status }}",
    "{{ {'unpaid': '未支付', 'paid': '已支付'}.get(row.payout_status, row.payout_status) }}",
)

# 5. order_service：非 closed 訂單不產生分潤
guard = '''    db.execute(delete(WorkerPayout).where(WorkerPayout.order_id == order_id))
    db.execute(delete(CustomerServicePayout).where(CustomerServicePayout.order_id == order_id))

    if str(order.status) != "closed":
        return

'''

if 'if str(order.status) != "closed":' not in service:
    needle = '''    if order is None:
        raise ValueError("找不到這張訂單，無法計算分潤。")

'''
    if needle not in service:
        raise RuntimeError("找不到 recalculate_order_payouts 的 order None 區塊")

    service = service.replace(needle, needle + guard, 1)

GROUPED_PY.write_text(py, encoding="utf-8")
GROUPED_HTML.write_text(html, encoding="utf-8")
ORDER_SERVICE.write_text(service, encoding="utf-8")

print("patched v2: closed-only payouts + merged same Discord ID")
