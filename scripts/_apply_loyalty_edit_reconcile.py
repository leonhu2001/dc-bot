from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


loyalty_path = Path("services/loyalty_benefits.py")
text = loyalty_path.read_text(encoding="utf-8")

text = replace_once(
    text,
    'EXPIRED = "expired"\n',
    'EXPIRED = "expired"\nREVOKED = "revoked"\n',
    "add revoked status",
)

text = replace_once(
    text,
    '''                progress_units REAL NOT NULL DEFAULT 0,\n                threshold_units REAL NOT NULL,\n''',
    '''                progress_units REAL NOT NULL DEFAULT 0,\n                debt_units REAL NOT NULL DEFAULT 0,\n                threshold_units REAL NOT NULL,\n''',
    "add debt column to create table",
)

text = replace_once(
    text,
    '''        conn.execute(text("""\n            CREATE TABLE IF NOT EXISTS customer_benefit_coupons (\n''',
    '''        progress_columns = {\n            str(row[1])\n            for row in conn.execute(text("PRAGMA table_info(customer_loyalty_progress)")).fetchall()\n        }\n        if "debt_units" not in progress_columns:\n            conn.execute(text(\n                "ALTER TABLE customer_loyalty_progress "\n                "ADD COLUMN debt_units REAL NOT NULL DEFAULT 0"\n            ))\n\n        conn.execute(text("""\n            CREATE TABLE IF NOT EXISTS customer_benefit_coupons (\n''',
    "migrate debt column",
)

reconcile_block = r'''

def _append_reconcile_note(existing: object, marker: str) -> str:
    note = str(existing or "").strip()
    if not note:
        return marker
    parts = [part.strip() for part in note.split(";") if part.strip()]
    if marker not in parts:
        parts.append(marker)
    return ";".join(parts)


def _loyalty_bucket_from_order(row: dict[str, Any]) -> dict[str, Any] | None:
    customer_id = str(row.get("customer_discord_id") or "").strip()
    rule_key = str(row.get("order_rule_key") or "").strip()
    policy = loyalty_policy_for_rule(rule_key)
    if (
        not customer_id
        or str(row.get("status") or "").strip().lower() != "closed"
        or policy is None
        or not _event_time_is_in_scope(row)
        or _qualifying_paid_amount(row) <= 0
    ):
        return None

    rule = _rule_for_key(rule_key)
    player_count = _extract_player_count(row)
    companion_count = _service_companion_count(rule, player_count)
    return {
        "customer_id": customer_id,
        "scope_key": loyalty_scope_key(rule_key, player_count),
        "rule_key": rule_key,
        "rule_label": _loyalty_display_label(
            rule_key,
            getattr(rule, "label", rule_key),
        ),
        "pricing_type": str(policy["pricing_type"]),
        "threshold_units": float(policy["threshold_units"]),
        "benefit_kind": str(policy["benefit_kind"]),
        "benefit_units": float(policy["benefit_units"]),
        "paid_units": float(
            max(0, int(row.get("quantity") or 0)) * companion_count
        ),
    }


def reconcile_customer_loyalty_in_connection(conn, customer_id: str | int) -> dict[str, Any]:
    """Rebuild one customer's loyalty pools from current closed orders.

    Unused over-issued rewards are revoked. Redeemed/reserved rewards are never
    clawed back; when an edit makes them exceed the customer's earned total,
    debt_units makes future service units pay back that difference before new
    progress can earn another reward.
    """
    customer = str(customer_id or "").strip()
    if not customer:
        return {"customer_id": "", "scopes": 0, "revoked": 0, "issued": 0}

    progress_columns = {
        str(row[1])
        for row in conn.execute(text("PRAGMA table_info(customer_loyalty_progress)")).fetchall()
    }
    if "debt_units" not in progress_columns:
        conn.execute(text(
            "ALTER TABLE customer_loyalty_progress "
            "ADD COLUMN debt_units REAL NOT NULL DEFAULT 0"
        ))

    now = get_taipei_now_iso()
    _expire_active_coupons(conn)

    # Existing events are markers for idempotency. Reset this customer's markers
    # first, then rewrite them from the current source-of-truth order rows.
    event_rows = conn.execute(text("""
        SELECT order_id, note
        FROM loyalty_order_events
        WHERE customer_discord_id = :customer_id
    """), {"customer_id": customer}).mappings().all()
    for event in event_rows:
        conn.execute(text("""
            UPDATE loyalty_order_events
            SET scope_key = NULL,
                paid_units = 0,
                processed_at = :processed_at,
                note = :note
            WHERE order_id = :order_id
        """), {
            "order_id": int(event["order_id"]),
            "processed_at": now,
            "note": _append_reconcile_note(event.get("note"), "admin_reconciled"),
        })

    order_rows = conn.execute(text("""
        SELECT id, customer_discord_id, order_rule_key, quantity,
               amount, original_amount, customer_pay_amount,
               status, created_at, updated_at, closed_at,
               price_snapshot_json, ticket_channel_id
        FROM web_orders
        WHERE customer_discord_id = :customer_id
          AND status = 'closed'
        ORDER BY id ASC
    """), {"customer_id": customer}).mappings().all()

    buckets: dict[str, dict[str, Any]] = {}
    for raw in order_rows:
        row = dict(raw)
        bucket = _loyalty_bucket_from_order(row)
        note = "admin_reconciled"
        scope = None
        paid_units = 0.0
        if bucket is not None:
            scope = str(bucket["scope_key"])
            paid_units = float(bucket["paid_units"])
            aggregate = buckets.setdefault(scope, dict(bucket))
            aggregate["paid_units"] = float(aggregate.get("paid_units") or 0) + paid_units
        elif not str(row.get("customer_discord_id") or "").strip():
            note = "admin_reconciled;missing_customer"
        elif not _event_time_is_in_scope(row):
            note = "admin_reconciled;before_program_start"
        elif loyalty_policy_for_rule(str(row.get("order_rule_key") or "").strip()) is None:
            note = "admin_reconciled;rule_not_eligible"
        elif _qualifying_paid_amount(row) <= 0:
            note = "admin_reconciled;no_paid_amount"

        conn.execute(text("""
            INSERT INTO loyalty_order_events (
                order_id, customer_discord_id, scope_key, paid_units,
                issued_coupon_count, processed_at, note
            ) VALUES (
                :order_id, :customer_id, :scope_key, :paid_units,
                0, :processed_at, :note
            )
            ON CONFLICT(order_id) DO UPDATE SET
                customer_discord_id = excluded.customer_discord_id,
                scope_key = excluded.scope_key,
                paid_units = excluded.paid_units,
                processed_at = excluded.processed_at,
                note = excluded.note
        """), {
            "order_id": int(row["id"]),
            "customer_id": customer,
            "scope_key": scope,
            "paid_units": paid_units,
            "processed_at": now,
            "note": note,
        })

    scope_meta: dict[str, dict[str, Any]] = {
        scope: dict(bucket) for scope, bucket in buckets.items()
    }

    progress_rows = conn.execute(text("""
        SELECT *
        FROM customer_loyalty_progress
        WHERE customer_discord_id = :customer_id
    """), {"customer_id": customer}).mappings().all()
    for raw in progress_rows:
        row = dict(raw)
        scope = str(row.get("scope_key") or "").strip()
        if not scope or scope in scope_meta:
            continue
        scope_meta[scope] = {
            "customer_id": customer,
            "scope_key": scope,
            "rule_key": str(row.get("rule_key") or ""),
            "rule_label": str(row.get("rule_label") or row.get("rule_key") or "福利"),
            "pricing_type": str(row.get("pricing_type") or ""),
            "threshold_units": float(row.get("threshold_units") or 0),
            "benefit_kind": str(row.get("benefit_kind") or ""),
            "benefit_units": float(row.get("benefit_units") or 0),
            "paid_units": 0.0,
        }

    coupon_meta_rows = conn.execute(text("""
        SELECT scope_key, rule_key, rule_label, pricing_type,
               benefit_kind, benefit_units
        FROM customer_benefit_coupons
        WHERE customer_discord_id = :customer_id
          AND source = 'loyalty'
        ORDER BY id ASC
    """), {"customer_id": customer}).mappings().all()
    for raw in coupon_meta_rows:
        row = dict(raw)
        scope = str(row.get("scope_key") or "").strip()
        if not scope or scope in scope_meta:
            continue
        rule_key = str(row.get("rule_key") or "").strip()
        policy = loyalty_policy_for_rule(rule_key)
        if policy is None:
            continue
        scope_meta[scope] = {
            "customer_id": customer,
            "scope_key": scope,
            "rule_key": rule_key,
            "rule_label": _loyalty_display_label(rule_key, row.get("rule_label")),
            "pricing_type": str(row.get("pricing_type") or policy["pricing_type"]),
            "threshold_units": float(policy["threshold_units"]),
            "benefit_kind": str(row.get("benefit_kind") or policy["benefit_kind"]),
            "benefit_units": float(row.get("benefit_units") or policy["benefit_units"]),
            "paid_units": 0.0,
        }

    revoked_total = 0
    issued_total = 0

    for scope, meta in scope_meta.items():
        threshold = float(meta.get("threshold_units") or 0)
        if threshold <= 0:
            continue
        total_units = float((buckets.get(scope) or {}).get("paid_units") or 0)
        earned_count = max(0, int(total_units // threshold))
        remainder = max(0.0, total_units - earned_count * threshold)

        coupons = [
            dict(row)
            for row in conn.execute(text("""
                SELECT *
                FROM customer_benefit_coupons
                WHERE customer_discord_id = :customer_id
                  AND scope_key = :scope_key
                  AND source = 'loyalty'
                ORDER BY issued_at ASC, id ASC
            """), {
                "customer_id": customer,
                "scope_key": scope,
            }).mappings().all()
        ]
        protected = [
            row for row in coupons
            if str(row.get("status") or "").lower() in {RESERVED, REDEEMED}
        ]
        expired = [
            row for row in coupons
            if str(row.get("status") or "").lower() == EXPIRED
        ]
        active = [
            row for row in coupons
            if str(row.get("status") or "").lower() == ACTIVE
        ]

        target_nonprotected = max(0, earned_count - len(protected))
        keep_expired = min(len(expired), target_nonprotected)
        revoke_expired = expired[keep_expired:]
        target_active = max(0, target_nonprotected - keep_expired)

        excess_active = max(0, len(active) - target_active)
        # Revoke newest active rewards first so the oldest valid reward remains FIFO.
        revoke_active = list(reversed(active))[:excess_active]
        revoke_rows = revoke_expired + revoke_active
        if revoke_rows:
            ids = [int(row["id"]) for row in revoke_rows]
            placeholders = ",".join(str(value) for value in ids)
            result = conn.execute(text(f"""
                UPDATE customer_benefit_coupons
                SET status = 'revoked',
                    reserved_order_id = NULL
                WHERE id IN ({placeholders})
                  AND status IN ('active', 'expired')
            """))
            revoked_total += int(result.rowcount or 0)

        active_after = max(0, len(active) - excess_active)
        missing_active = max(0, target_active - active_after)
        expires_at = _coupon_expiry_iso(now)
        for _ in range(missing_active):
            conn.execute(text("""
                INSERT INTO customer_benefit_coupons (
                    customer_discord_id, scope_key, rule_key, rule_label,
                    pricing_type, player_count, benefit_kind, benefit_units,
                    status, source, issued_at, expires_at
                ) VALUES (
                    :customer_id, :scope_key, :rule_key, :rule_label,
                    :pricing_type, 1, :benefit_kind, :benefit_units,
                    'active', 'loyalty', :issued_at, :expires_at
                )
            """), {
                "customer_id": customer,
                "scope_key": scope,
                "rule_key": str(meta.get("rule_key") or ""),
                "rule_label": str(meta.get("rule_label") or meta.get("rule_key") or "福利"),
                "pricing_type": str(meta.get("pricing_type") or ""),
                "benefit_kind": str(meta.get("benefit_kind") or ""),
                "benefit_units": float(meta.get("benefit_units") or 0),
                "issued_at": now,
                "expires_at": expires_at,
            })
            issued_total += 1

        debt_units = max(0.0, len(protected) * threshold - total_units)
        progress_units = 0.0 if debt_units > 0.0001 else remainder
        current_bucket = buckets.get(scope)

        if current_bucket is None and progress_units <= 0.0001 and debt_units <= 0.0001:
            conn.execute(text("""
                DELETE FROM customer_loyalty_progress
                WHERE customer_discord_id = :customer_id
                  AND scope_key = :scope_key
            """), {"customer_id": customer, "scope_key": scope})
            continue

        conn.execute(text("""
            INSERT INTO customer_loyalty_progress (
                customer_discord_id, scope_key, rule_key, rule_label,
                pricing_type, player_count, progress_units, debt_units,
                threshold_units, benefit_kind, benefit_units, updated_at
            ) VALUES (
                :customer_id, :scope_key, :rule_key, :rule_label,
                :pricing_type, 1, :progress_units, :debt_units,
                :threshold_units, :benefit_kind, :benefit_units, :updated_at
            )
            ON CONFLICT(customer_discord_id, scope_key) DO UPDATE SET
                rule_key = excluded.rule_key,
                rule_label = excluded.rule_label,
                pricing_type = excluded.pricing_type,
                player_count = 1,
                progress_units = excluded.progress_units,
                debt_units = excluded.debt_units,
                threshold_units = excluded.threshold_units,
                benefit_kind = excluded.benefit_kind,
                benefit_units = excluded.benefit_units,
                updated_at = excluded.updated_at
        """), {
            "customer_id": customer,
            "scope_key": scope,
            "rule_key": str(meta.get("rule_key") or ""),
            "rule_label": str(meta.get("rule_label") or meta.get("rule_key") or "福利"),
            "pricing_type": str(meta.get("pricing_type") or ""),
            "progress_units": progress_units,
            "debt_units": debt_units,
            "threshold_units": threshold,
            "benefit_kind": str(meta.get("benefit_kind") or ""),
            "benefit_units": float(meta.get("benefit_units") or 0),
            "updated_at": now,
        })

    return {
        "customer_id": customer,
        "scopes": len(scope_meta),
        "revoked": revoked_total,
        "issued": issued_total,
    }


def reconcile_loyalty_after_order_edit_in_connection(
    conn,
    *,
    order_id: int,
    previous_customer_id: str | int | None = None,
) -> dict[str, Any]:
    """Reconcile old/new customer pools after an admin changes an order."""
    row = conn.execute(text("""
        SELECT customer_discord_id, status
        FROM web_orders
        WHERE id = :order_id
        LIMIT 1
    """), {"order_id": int(order_id)}).mappings().first()
    if row is None:
        return {"customers": [], "revoked": 0, "issued": 0}

    current_customer = str(row.get("customer_discord_id") or "").strip()
    current_status = str(row.get("status") or "").strip().lower()
    previous_customer = str(previous_customer_id or "").strip()

    if current_status != "closed":
        conn.execute(text(
            "DELETE FROM loyalty_order_events WHERE order_id = :order_id"
        ), {"order_id": int(order_id)})

    customers = []
    for customer in (previous_customer, current_customer):
        if customer and customer not in customers:
            customers.append(customer)

    summaries = [
        reconcile_customer_loyalty_in_connection(conn, customer)
        for customer in customers
    ]
    return {
        "customers": customers,
        "revoked": sum(int(item.get("revoked") or 0) for item in summaries),
        "issued": sum(int(item.get("issued") or 0) for item in summaries),
    }
'''

text = replace_once(
    text,
    '\n\ndef process_closed_order(order_id: int) -> dict[str, Any] | None:\n',
    reconcile_block + '\n\ndef process_closed_order(order_id: int) -> dict[str, Any] | None:\n',
    "insert reconcile functions",
)

text = replace_once(
    text,
    '''            previous = conn.execute(text("""\n                SELECT progress_units\n                FROM customer_loyalty_progress\n                WHERE customer_discord_id = :customer_id\n                  AND scope_key = :scope_key\n                LIMIT 1\n            """), {\n                "customer_id": customer_id,\n                "scope_key": scope,\n            }).scalar()\n            total = float(previous or 0) + paid_units\n            issued_count = int(total // threshold)\n            remainder = total - issued_count * threshold\n''',
    '''            progress_row = conn.execute(text("""\n                SELECT progress_units, debt_units\n                FROM customer_loyalty_progress\n                WHERE customer_discord_id = :customer_id\n                  AND scope_key = :scope_key\n                LIMIT 1\n            """), {\n                "customer_id": customer_id,\n                "scope_key": scope,\n            }).mappings().first()\n            previous = float(progress_row.get("progress_units") or 0) if progress_row else 0.0\n            debt_before = float(progress_row.get("debt_units") or 0) if progress_row else 0.0\n            debt_after = max(0.0, debt_before - paid_units)\n            credited_units = max(0.0, paid_units - debt_before)\n            total = previous + credited_units\n            issued_count = max(0, int(total // threshold))\n            remainder = total - issued_count * threshold\n''',
    "apply debt before new progress",
)

text = replace_once(
    text,
    '''                    pricing_type, player_count, progress_units, threshold_units,\n                    benefit_kind, benefit_units, updated_at\n                ) VALUES (\n                    :customer_id, :scope_key, :rule_key, :rule_label,\n                    :pricing_type, :player_count, :progress_units, :threshold_units,\n                    :benefit_kind, :benefit_units, :updated_at\n                )\n                ON CONFLICT(customer_discord_id, scope_key) DO UPDATE SET\n                    rule_label = excluded.rule_label,\n                    progress_units = excluded.progress_units,\n                    threshold_units = excluded.threshold_units,\n''',
    '''                    pricing_type, player_count, progress_units, debt_units, threshold_units,\n                    benefit_kind, benefit_units, updated_at\n                ) VALUES (\n                    :customer_id, :scope_key, :rule_key, :rule_label,\n                    :pricing_type, :player_count, :progress_units, :debt_units, :threshold_units,\n                    :benefit_kind, :benefit_units, :updated_at\n                )\n                ON CONFLICT(customer_discord_id, scope_key) DO UPDATE SET\n                    rule_label = excluded.rule_label,\n                    progress_units = excluded.progress_units,\n                    debt_units = excluded.debt_units,\n                    threshold_units = excluded.threshold_units,\n''',
    "write debt in close flow",
)

text = replace_once(
    text,
    '''                "progress_units": remainder,\n                "threshold_units": threshold,\n''',
    '''                "progress_units": remainder,\n                "debt_units": debt_after,\n                "threshold_units": threshold,\n''',
    "bind debt in close flow",
)

loyalty_path.write_text(text, encoding="utf-8")


admin_path = Path("web/app/routers/admin.py")
text = admin_path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''    db = SessionLocal()\n\n    try:\n        before_row = db.execute(\n''',
    '''    loyalty_reconciled = False\n    db = SessionLocal()\n\n    try:\n        before_row = db.execute(\n''',
    "initialize reconciliation flag",
)
text = replace_once(
    text,
    '''            _mw_r8_restore_payout_status(db, int(order_id), payout_snapshot)\n\n        after_row = db.execute(\n''',
    '''            _mw_r8_restore_payout_status(db, int(order_id), payout_snapshot)\n\n        if previous_status == "closed" or status == "closed":\n            from services.loyalty_benefits import (\n                reconcile_loyalty_after_order_edit_in_connection,\n            )\n\n            reconcile_loyalty_after_order_edit_in_connection(\n                db.connection(),\n                order_id=int(order_id),\n                previous_customer_id=old_customer_discord_id,\n            )\n            loyalty_reconciled = True\n\n        after_row = db.execute(\n''',
    "reconcile loyalty in admin edit transaction",
)
text = replace_once(
    text,
    '''    return _mw4a2r6_redirect(order_id,request=request, message="訂單資料已更新。")\n\n\n@router.post("/admin/order-workspace/{order_id}/add-worker")\n''',
    '''    return _mw4a2r6_redirect(\n        order_id,\n        request=request,\n        message=(\n            "訂單資料已更新，福利進度已重新對帳。"\n            if loyalty_reconciled\n            else "訂單資料已更新。"\n        ),\n    )\n\n\n@router.post("/admin/order-workspace/{order_id}/add-worker")\n''',
    "report reconciliation in success message",
)
admin_path.write_text(text, encoding="utf-8")


admin_loyalty_path = Path("web/app/services/admin_customer_loyalty.py")
text = admin_loyalty_path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''KNOWN_STATUSES = ("active", "reserved", "redeemed", "expired")\nSTATUS_LABELS = {\n    "active": "可使用",\n    "reserved": "使用中",\n    "redeemed": "已使用",\n    "expired": "已過期",\n}\n''',
    '''KNOWN_STATUSES = ("active", "reserved", "redeemed", "expired", "revoked")\nSTATUS_LABELS = {\n    "active": "可使用",\n    "reserved": "使用中",\n    "redeemed": "已使用",\n    "expired": "已過期",\n    "revoked": "已收回",\n}\n''',
    "label revoked benefits",
)
text = replace_once(
    text,
    '''            "expired": 0,\n            "other": 0,\n''',
    '''            "expired": 0,\n            "revoked": 0,\n            "other": 0,\n''',
    "count revoked benefits",
)
admin_loyalty_path.write_text(text, encoding="utf-8")


template_path = Path("web/app/templates/admin_customer_benefits.html")
text = template_path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''.coupon-status.expired{color:#969289}.empty-benefit''',
    '''.coupon-status.expired{color:#969289}.coupon-status.revoked{color:#969289}.empty-benefit''',
    "style revoked benefit",
)
template_path.write_text(text, encoding="utf-8")


test_path = Path("tests/test_loyalty_benefits.py")
text = test_path.read_text(encoding="utf-8")
append = r'''


def _setup_reconcile_db(monkeypatch, tmp_path: Path):
    db = tmp_path / "loyalty-reconcile.db"
    test_engine = create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(loyalty, "engine", test_engine)
    loyalty.ensure_loyalty_tables(test_engine)
    with test_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                customer_discord_id TEXT,
                order_rule_key TEXT,
                quantity INTEGER,
                amount INTEGER,
                original_amount INTEGER,
                customer_pay_amount INTEGER,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                closed_at TEXT,
                price_snapshot_json TEXT,
                ticket_channel_id TEXT
            )
        """))
    return test_engine


def _insert_closed_order(engine, order_id: int, customer: str, quantity: int):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO web_orders (
                id, customer_discord_id, order_rule_key, quantity,
                amount, original_amount, customer_pay_amount, status,
                created_at, updated_at, closed_at, price_snapshot_json
            ) VALUES (
                :id, :customer, 'basic_entertain_single', :quantity,
                1000, 1000, 1000, 'closed',
                '2026-10-11 10:00:00', '2026-10-11 10:00:00',
                '2026-10-11 10:00:00', '{}'
            )
        """), {"id": order_id, "customer": customer, "quantity": quantity})


def test_reconcile_closed_order_quantity_increase_updates_progress_and_rewards(monkeypatch, tmp_path: Path):
    engine = _setup_reconcile_db(monkeypatch, tmp_path)
    _insert_closed_order(engine, 1, "owner-a", 4)
    loyalty.process_closed_order(1)

    with engine.begin() as conn:
        conn.execute(text("UPDATE web_orders SET quantity = 12 WHERE id = 1"))
        result = loyalty.reconcile_loyalty_after_order_edit_in_connection(
            conn, order_id=1, previous_customer_id="owner-a"
        )
        progress = conn.execute(text("""
            SELECT progress_units, debt_units
            FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-a'
        """)).mappings().one()
        active = conn.execute(text("""
            SELECT COUNT(*) FROM customer_benefit_coupons
            WHERE customer_discord_id = 'owner-a' AND status = 'active'
        """)).scalar_one()
        paid_units = conn.execute(text(
            "SELECT paid_units FROM loyalty_order_events WHERE order_id = 1"
        )).scalar_one()

    assert result["issued"] == 1
    assert float(progress["progress_units"]) == 2.0
    assert float(progress["debt_units"]) == 0.0
    assert active == 1
    assert float(paid_units) == 12.0


def test_reconcile_closed_order_quantity_decrease_revokes_unused_reward(monkeypatch, tmp_path: Path):
    engine = _setup_reconcile_db(monkeypatch, tmp_path)
    _insert_closed_order(engine, 1, "owner-a", 12)
    loyalty.process_closed_order(1)

    with engine.begin() as conn:
        conn.execute(text("UPDATE web_orders SET quantity = 4 WHERE id = 1"))
        result = loyalty.reconcile_loyalty_after_order_edit_in_connection(
            conn, order_id=1, previous_customer_id="owner-a"
        )
        statuses = [row[0] for row in conn.execute(text("""
            SELECT status FROM customer_benefit_coupons
            WHERE customer_discord_id = 'owner-a'
            ORDER BY id
        """)).fetchall()]
        progress = conn.execute(text("""
            SELECT progress_units, debt_units
            FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-a'
        """)).mappings().one()

    assert result["revoked"] == 1
    assert statuses == ["revoked"]
    assert float(progress["progress_units"]) == 4.0
    assert float(progress["debt_units"]) == 0.0


def test_reconcile_keeps_redeemed_reward_and_future_units_pay_debt_first(monkeypatch, tmp_path: Path):
    engine = _setup_reconcile_db(monkeypatch, tmp_path)
    _insert_closed_order(engine, 1, "owner-a", 12)
    loyalty.process_closed_order(1)

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE customer_benefit_coupons
            SET status = 'redeemed', redeemed_order_id = 999,
                redeemed_at = '2026-10-11T12:00:00+08:00'
            WHERE customer_discord_id = 'owner-a'
        """))
        conn.execute(text("UPDATE web_orders SET quantity = 4 WHERE id = 1"))
        loyalty.reconcile_loyalty_after_order_edit_in_connection(
            conn, order_id=1, previous_customer_id="owner-a"
        )
        progress = conn.execute(text("""
            SELECT progress_units, debt_units
            FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-a'
        """)).mappings().one()
        redeemed = conn.execute(text("""
            SELECT COUNT(*) FROM customer_benefit_coupons
            WHERE customer_discord_id = 'owner-a' AND status = 'redeemed'
        """)).scalar_one()

    assert redeemed == 1
    assert float(progress["progress_units"]) == 0.0
    assert float(progress["debt_units"]) == 6.0

    _insert_closed_order(engine, 2, "owner-a", 8)
    loyalty.process_closed_order(2)
    with engine.begin() as conn:
        progress = conn.execute(text("""
            SELECT progress_units, debt_units
            FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-a'
        """)).mappings().one()
        active = conn.execute(text("""
            SELECT COUNT(*) FROM customer_benefit_coupons
            WHERE customer_discord_id = 'owner-a' AND status = 'active'
        """)).scalar_one()
    assert float(progress["debt_units"]) == 0.0
    assert float(progress["progress_units"]) == 2.0
    assert active == 0

    _insert_closed_order(engine, 3, "owner-a", 8)
    loyalty.process_closed_order(3)
    with engine.begin() as conn:
        active = conn.execute(text("""
            SELECT COUNT(*) FROM customer_benefit_coupons
            WHERE customer_discord_id = 'owner-a' AND status = 'active'
        """)).scalar_one()
    assert active == 1


def test_reconcile_customer_move_rebuilds_old_and_new_owner_pools(monkeypatch, tmp_path: Path):
    engine = _setup_reconcile_db(monkeypatch, tmp_path)
    _insert_closed_order(engine, 1, "owner-a", 5)
    loyalty.process_closed_order(1)

    with engine.begin() as conn:
        conn.execute(text("UPDATE web_orders SET customer_discord_id = 'owner-b' WHERE id = 1"))
        loyalty.reconcile_loyalty_after_order_edit_in_connection(
            conn, order_id=1, previous_customer_id="owner-a"
        )
        old_progress = conn.execute(text("""
            SELECT COUNT(*) FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-a'
        """)).scalar_one()
        new_progress = conn.execute(text("""
            SELECT progress_units FROM customer_loyalty_progress
            WHERE customer_discord_id = 'owner-b'
        """)).scalar_one()
        event_owner = conn.execute(text(
            "SELECT customer_discord_id FROM loyalty_order_events WHERE order_id = 1"
        )).scalar_one()

    assert old_progress == 0
    assert float(new_progress) == 5.0
    assert event_owner == "owner-b"
'''
if "test_reconcile_closed_order_quantity_increase_updates_progress_and_rewards" in text:
    raise SystemExit("reconcile tests already present")
test_path.write_text(text.rstrip() + append + "\n", encoding="utf-8")


admin_test_path = Path("tests/test_admin_customer_loyalty.py")
text = admin_test_path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''        "expired": 1,\n        "other": 0,\n''',
    '''        "expired": 1,\n        "revoked": 0,\n        "other": 0,\n''',
    "update admin coupon count expectation",
)
admin_test_path.write_text(text, encoding="utf-8")
