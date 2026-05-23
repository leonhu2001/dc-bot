from pathlib import Path
import re

GROUPED_PY = Path("web/app/routers/admin_payouts_grouped.py")
GROUPED_HTML = Path("web/app/templates/admin_payouts_grouped.html")
ORDER_SERVICE = Path("web/app/services/order_service.py")

py = GROUPED_PY.read_text(encoding="utf-8")
html = GROUPED_HTML.read_text(encoding="utf-8")
service = ORDER_SERVICE.read_text(encoding="utf-8")


# 1) 月結查詢只抓 closed 訂單
py = py.replace(
"""            WHERE 1 = 1
            {month_sql}
            {status_sql}""",
"""            WHERE o.status = 'closed'
            {month_sql}
            {status_sql}"""
)


# 2) 同一個 Discord ID 合併，不再用 payout_role 分開
start = py.find("def group_rows")
end = py.find("\ndef build_summary", start)

if start == -1 or end == -1:
    raise RuntimeError("找不到 group_rows / build_summary 區塊")

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

py = py[:start] + new_group_rows + py[end:]


# 3) 整組標記已發放/未發放時，person 同時更新客服與打手
py = py.replace(
'payout_role = normalize_filter(payout_role, {"worker", "customer_service"}, "worker")',
'payout_role = normalize_filter(payout_role, {"person", "worker", "customer_service"}, "person")',
)

old_block = r'''    table = "worker_payouts" if payout_role == "worker" else "customer_service_payouts"
    person_col = "worker_discord_id" if payout_role == "worker" else "customer_service_discord_id"

    conditions = [f"{person_col} = ?"]
    params: list[str] = [person_id]

    if month:
        conditions.append("strftime('%Y-%m', created_at) = ?")
        params.append(month)

    if status != "all":
        conditions.append("payout_status = ?")
        params.append(status)

    set_paid_at = "CURRENT_TIMESTAMP" if new_status == "paid" else "NULL"
    sql = f"""
        UPDATE {table}
        SET payout_status = ?, paid_at = {set_paid_at}
        WHERE {' AND '.join(conditions)}
    """

    conn = connect_db()

    try:
        cur = conn.execute(sql, [new_status, *params])
        conn.commit()
        changed = cur.rowcount
    finally:
        conn.close()
'''

new_block = r'''    set_paid_at = "CURRENT_TIMESTAMP" if new_status == "paid" else "NULL"

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
'''

if old_block not in py:
    raise RuntimeError("找不到 update_group_status 舊區塊，請貼 admin_payouts_grouped.py 最新內容。")

py = py.replace(old_block, new_block)


# 4) 模板身份顯示改成 role_label，hidden payout_role 用 person
html = html.replace(
'''                                    <div class="person-role">
                                        {% if group.payout_role == "worker" %}打手{% else %}客服{% endif %}
                                    </div>''',
'''                                    <div class="person-role">{{ group.role_label }}</div>'''
)

html = html.replace(
'name="payout_role" value="{{ group.payout_role }}"',
'name="payout_role" value="{{ group.payout_role }}"'
)

html = html.replace(
'{{ row.payout_status }}',
"{{ {'unpaid': '未支付', 'paid': '已支付'}.get(row.payout_status, row.payout_status) }}"
)


# 5) order_service：非 closed 訂單不產生分潤
needle = '''    if order is None:
        raise ValueError("找不到這張訂單，無法計算分潤。")

'''
insert = '''    if order is None:
        raise ValueError("找不到這張訂單，無法計算分潤。")

    db.execute(delete(WorkerPayout).where(WorkerPayout.order_id == order_id))
    db.execute(delete(CustomerServicePayout).where(CustomerServicePayout.order_id == order_id))

    if str(order.status) != "closed":
        return

'''

if insert not in service:
    if needle not in service:
        raise RuntimeError("找不到 recalculate_order_payouts 的 order None 區塊")
    service = service.replace(needle, insert, 1)

# 避免 closed 狀態下重複 delete，移除後面原本的 delete 兩行
service = service.replace(
'''    db.execute(delete(WorkerPayout).where(WorkerPayout.order_id == order_id))
    db.execute(delete(CustomerServicePayout).where(CustomerServicePayout.order_id == order_id))

    assignment_name_map = {''',
'''    assignment_name_map = {''',
    1,
)


GROUPED_PY.write_text(py, encoding="utf-8")
GROUPED_HTML.write_text(html, encoding="utf-8")
ORDER_SERVICE.write_text(service, encoding="utf-8")

print("patched closed-only payouts and merged person grouping")
