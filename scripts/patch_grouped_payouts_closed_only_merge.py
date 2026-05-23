from pathlib import Path
import re

PY_PATH = Path("web/app/routers/admin_payouts_grouped.py")
HTML_PATH = Path("web/app/templates/admin_payouts_grouped.html")

text = PY_PATH.read_text(encoding="utf-8")
html = HTML_PATH.read_text(encoding="utf-8")

# 1. 分潤只抓 closed 訂單
text = text.replace(
    "WHERE 1 = 1\n            {month_sql}",
    "WHERE o.status = 'closed'\n            {month_sql}",
)

# 2. 依 Discord ID 合併，不再用身份拆分
start = text.find("def group_rows")
end = text.find("\ndef build_summary", start)

if start == -1 or end == -1:
    raise RuntimeError("找不到 group_rows 區塊")

new_group_rows = r'''def group_rows(rows: list[dict]) -> list[dict]:
    """依 Discord ID 合併分潤，不再把客服/打手身份拆成兩列。"""
    grouped: dict[str, dict] = {}

    for row in rows:
        person_id = str(row["person_id"] or "")
        key = person_id or str(row["person_name"] or "")

        if key not in grouped:
            grouped[key] = {
                "payout_role": "person",
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
        else:
            group["role_label"] = "人員"

        result.append(group)

    return sorted(
        result,
        key=lambda item: str(item["person_name"] or ""),
    )
'''

text = text[:start] + new_group_rows + text[end:]

# 3. 整組標記時，person 代表同一 Discord ID 同時更新客服 + 打手
text = text.replace(
    'payout_role = normalize_filter(payout_role, {"worker", "customer_service"}, "worker")',
    'payout_role = normalize_filter(payout_role, {"person", "worker", "customer_service"}, "person")',
)

old_update_block = r'''    table = "worker_payouts" if payout_role == "worker" else "customer_service_payouts"
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

new_update_block = r'''    set_paid_at = "CURRENT_TIMESTAMP" if new_status == "paid" else "NULL"

    def build_update_sql(table: str, person_col: str) -> tuple[str, list[str]]:
        conditions = [f"{person_col} = ?"]
        params: list[str] = [person_id]

        if month:
            conditions.append("strftime('%Y-%m', created_at) = ?")
            params.append(month)

        if status != "all":
            conditions.append("payout_status = ?")
            params.append(status)

        sql = f"""
            UPDATE {table}
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
            sql, params = build_update_sql(table, person_col)
            cur = conn.execute(sql, [new_status, *params])
            changed += cur.rowcount

        conn.commit()
    finally:
        conn.close()
'''

if old_update_block not in text:
    raise RuntimeError("找不到 update_group_status 舊區塊")

text = text.replace(old_update_block, new_update_block)

# 4. 模板顯示身份改成 group.role_label，不再固定客服/打手拆列
html = html.replace(
'''                                    <div class="person-role">
                                        {% if group.payout_role == "worker" %}打手{% else %}客服{% endif %}
                                    </div>''',
'''                                    <div class="person-role">{{ group.role_label }}</div>'''
)

PY_PATH.write_text(text, encoding="utf-8")
HTML_PATH.write_text(html, encoding="utf-8")

print("patched grouped payouts: closed only + merge same Discord ID")
