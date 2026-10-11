from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    return text.replace(old, new, 1)


def replace_between(text: str, start: str, end: str, new_block: str, label: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise SystemExit(f"{label}: start marker not found")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:start_index] + new_block.rstrip() + "\n\n\n" + text[end_index:]


# 1) One shared rule for customer-service payout base.
path = Path("shared/payout.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from dataclasses import dataclass\n",
    "import json\nfrom dataclasses import dataclass\n",
    "shared payout json import",
)
helper = '''def calculate_customer_service_payout_base_amount(\n    *,\n    payout_base_amount: int,\n    price_snapshot_json=None,\n) -> int:\n    \"\"\"Return the amount eligible for customer-service commission.\n\n    Store-funded free service (points / cross-order benefit service value)\n    still counts toward companion payout value, but must not create extra\n    customer-service commission. This pure helper is the single source used by\n    payout creation, safe repair, and accounting reconciliation.\n    \"\"\"\n    base = max(0, int(payout_base_amount or 0))\n\n    if isinstance(price_snapshot_json, dict):\n        snapshot = price_snapshot_json\n    else:\n        try:\n            snapshot = json.loads(str(price_snapshot_json or \"{}\"))\n        except Exception:\n            snapshot = {}\n\n    if not isinstance(snapshot, dict):\n        return base\n\n    preview = (\n        snapshot.get(\"preview\")\n        if isinstance(snapshot.get(\"preview\"), dict)\n        else snapshot\n    )\n    finance = (\n        preview.get(\"finance\")\n        if isinstance(preview, dict)\n        and isinstance(preview.get(\"finance\"), dict)\n        else {}\n    )\n\n    def _amount(name: str) -> int:\n        try:\n            return max(0, int(round(float(finance.get(name) or 0))))\n        except (TypeError, ValueError):\n            return 0\n\n    store_funded_service = (\n        _amount(\"point_service_value\")\n        + _amount(\"benefit_service_value\")\n    )\n    return max(0, base - store_funded_service)\n'''
text = replace_once(
    text,
    "\ndef calculate_order_payout(\n",
    "\n" + helper + "\n\ndef calculate_order_payout(\n",
    "shared payout helper insertion",
)
path.write_text(text, encoding="utf-8")


# 2) Payout creation/repair delegates to the shared base rule.
path = Path("web/app/services/order_service.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from shared.payout import calculate_order_payout\n",
    "from shared.payout import (\n    calculate_customer_service_payout_base_amount,\n    calculate_order_payout,\n)\n",
    "order service payout import",
)
new_cs_base = '''def _customer_service_payout_base(order: WebOrder) -> int:\n    return calculate_customer_service_payout_base_amount(\n        payout_base_amount=int(\n            getattr(order, \"payout_base_amount\", None)\n            or getattr(order, \"amount\", 0)\n            or 0\n        ),\n        price_snapshot_json=getattr(order, \"price_snapshot_json\", None),\n    )'''
text = replace_between(
    text,
    "def _customer_service_payout_base(order: WebOrder) -> int:\n",
    "def recalculate_order_payouts(db: Session, order_id: int) -> None:\n",
    new_cs_base,
    "order service customer-service base",
)
path.write_text(text, encoding="utf-8")


# 3) Accounting detector uses the exact same CS commission base as repair.
path = Path("web/app/services/accounting_reconciliation.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from shared.payout import calculate_order_payout\n",
    "from shared.payout import (\n    calculate_customer_service_payout_base_amount,\n    calculate_order_payout,\n)\n",
    "accounting reconciliation payout import",
)
text = replace_once(
    text,
    "            payout_base_amount,\n            payment_method,\n",
    "            payout_base_amount,\n            price_snapshot_json,\n            payment_method,\n",
    "accounting reconciliation select snapshot",
)
text = replace_once(
    text,
    '''        expected = calculate_order_payout(\n            total_amount=payout_base,\n            worker_discord_ids=worker_ids,\n            named_bonus_worker_ids=named_bonus_ids,\n        )\n''',
    '''        expected = calculate_order_payout(\n            total_amount=payout_base,\n            worker_discord_ids=worker_ids,\n            named_bonus_worker_ids=named_bonus_ids,\n            customer_service_total_amount=(\n                calculate_customer_service_payout_base_amount(\n                    payout_base_amount=payout_base,\n                    price_snapshot_json=order.get(\"price_snapshot_json\"),\n                )\n            ),\n        )\n''',
    "accounting reconciliation expected payout",
)
path.write_text(text, encoding="utf-8")


# 4) VIP monthly benefits are governed by the member's current effective tier.
path = Path("services/vip_monthly_benefits.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    'REDEEMED = "redeemed"\n',
    'REDEEMED = "redeemed"\nREVOKED = "revoked"\n',
    "VIP revoked status",
)
new_sync = '''def sync_current_month_vip_benefits(\n    *,\n    now: datetime | None = None,\n    web_db: str | Path | None = None,\n    bot_db: str | Path | None = None,\n) -> dict[str, Any]:\n    \"\"\"Synchronize current-month benefits to each member's current tier.\n\n    Unused monthly benefits above the member's current effective tier are\n    revoked immediately. Redeemed benefits remain immutable history, and an\n    already-reserved black-diamond redemption may finish normally. If the\n    member becomes eligible again in the same month, a previously revoked\n    unused benefit is reactivated instead of issuing a duplicate row.\n    \"\"\"\n    current = _normalize_now(now)\n    month = _month_key(current)\n    now_text = current.isoformat(timespec=\"seconds\")\n    path = _web_db_path(web_db)\n    ensure_vip_monthly_tables(path)\n\n    snapshot = build_vip_review_snapshot(\n        db_file=_bot_db_path(bot_db),\n        view=\"all\",\n        now=current,\n    )\n    member_rows = list(snapshot.get(\"rows\") or [])\n\n    issued = 0\n    revoked = 0\n    reactivated = 0\n    eligible_customers = 0\n    legacy_seeded = 0\n    first_refresh = False\n    entitlement_by_customer: dict[str, set[str]] = {}\n\n    with sqlite3.connect(path, timeout=15) as conn:\n        conn.row_factory = sqlite3.Row\n        legacy_seeded = _seed_october_2026_used_200(conn, now_text=now_text)\n\n        for row in member_rows:\n            customer_id = str(row.get(\"customer_id\") or \"\").strip()\n            if not customer_id:\n                continue\n\n            keys = _benefit_keys_for_level(str(row.get(\"current_level\") or \"\"))\n            entitlement_by_customer[customer_id] = keys\n\n            if bool(row.get(\"is_due\")) or not keys:\n                # Due members do not receive/reactivate a new benefit, but an\n                # already-issued current-tier benefit is not revoked only for\n                # becoming due. Tier eligibility remains the revocation rule.\n                continue\n\n            eligible_customers += 1\n            for benefit_key in MONTHLY_BENEFIT_KEYS:\n                if benefit_key not in keys:\n                    continue\n\n                existing = conn.execute(\n                    \"\"\"\n                    SELECT id, status\n                    FROM vip_monthly_benefits\n                    WHERE customer_id=? AND month_key=? AND benefit_key=?\n                    LIMIT 1\n                    \"\"\",\n                    (customer_id, month, benefit_key),\n                ).fetchone()\n\n                if existing is None:\n                    cur = conn.execute(\n                        \"\"\"\n                        INSERT INTO vip_monthly_benefits (\n                            customer_id,\n                            month_key,\n                            benefit_key,\n                            benefit_label,\n                            status,\n                            issued_at,\n                            updated_at,\n                            source\n                        ) VALUES (?, ?, ?, ?, 'available', ?, ?, 'system')\n                        \"\"\",\n                        (\n                            customer_id,\n                            month,\n                            benefit_key,\n                            BENEFIT_LABELS[benefit_key],\n                            now_text,\n                            now_text,\n                        ),\n                    )\n                    issued += int(cur.rowcount or 0)\n                elif str(existing[\"status\"] or \"\") == REVOKED:\n                    cur = conn.execute(\n                        \"\"\"\n                        UPDATE vip_monthly_benefits\n                        SET status='available',\n                            choice_key=NULL,\n                            reserved_at=NULL,\n                            reserved_channel_id=NULL,\n                            redeemed_at=NULL,\n                            updated_at=?\n                        WHERE id=? AND status='revoked'\n                        \"\"\",\n                        (now_text, int(existing[\"id\"])),\n                    )\n                    reactivated += int(cur.rowcount or 0)\n\n        available_rows = conn.execute(\n            \"\"\"\n            SELECT id, customer_id, benefit_key\n            FROM vip_monthly_benefits\n            WHERE month_key=? AND status='available'\n            \"\"\",\n            (month,),\n        ).fetchall()\n        for benefit_row in available_rows:\n            customer_id = str(benefit_row[\"customer_id\"] or \"\")\n            benefit_key = str(benefit_row[\"benefit_key\"] or \"\")\n            current_keys = entitlement_by_customer.get(customer_id, set())\n            if benefit_key in current_keys:\n                continue\n            cur = conn.execute(\n                \"\"\"\n                UPDATE vip_monthly_benefits\n                SET status='revoked',\n                    choice_key=NULL,\n                    reserved_at=NULL,\n                    reserved_channel_id=NULL,\n                    updated_at=?\n                WHERE id=? AND status='available'\n                \"\"\",\n                (now_text, int(benefit_row[\"id\"])),\n            )\n            revoked += int(cur.rowcount or 0)\n\n        state = conn.execute(\n            \"SELECT month_key, refreshed_at, announced_at FROM vip_monthly_refresh_state WHERE month_key=?\",\n            (month,),\n        ).fetchone()\n        if state is None:\n            first_refresh = True\n            bootstrap_announced_at = (\n                now_text\n                if month == \"2026-10\" and current.day > 1\n                else None\n            )\n            conn.execute(\n                \"\"\"\n                INSERT INTO vip_monthly_refresh_state (month_key, refreshed_at, announced_at)\n                VALUES (?, ?, ?)\n                \"\"\",\n                (month, now_text, bootstrap_announced_at),\n            )\n        else:\n            conn.execute(\n                \"UPDATE vip_monthly_refresh_state SET refreshed_at=? WHERE month_key=?\",\n                (now_text, month),\n            )\n        conn.commit()\n\n        state = conn.execute(\n            \"SELECT announced_at FROM vip_monthly_refresh_state WHERE month_key=?\",\n            (month,),\n        ).fetchone()\n        announcement_needed = bool(state is not None and not state[\"announced_at\"])\n\n    return {\n        \"month_key\": month,\n        \"issued_count\": issued,\n        \"revoked_count\": revoked,\n        \"reactivated_count\": reactivated,\n        \"eligible_customer_count\": eligible_customers,\n        \"legacy_seeded_count\": legacy_seeded,\n        \"first_refresh\": first_refresh,\n        \"announcement_needed\": announcement_needed,\n        \"expires_at\": _next_month_start(current).isoformat(timespec=\"seconds\"),\n    }'''
text = replace_between(
    text,
    "def sync_current_month_vip_benefits(\n",
    "def mark_month_announcement_sent(\n",
    new_sync,
    "VIP sync function",
)
new_snapshot = '''def get_customer_vip_monthly_snapshot(\n    customer_id: str | int,\n    *,\n    now: datetime | None = None,\n    web_db: str | Path | None = None,\n    bot_db: str | Path | None = None,\n    ensure_synced: bool = True,\n) -> dict[str, Any]:\n    current = _normalize_now(now)\n    month = _month_key(current)\n    customer = str(customer_id)\n    if ensure_synced:\n        sync_current_month_vip_benefits(\n            now=current,\n            web_db=web_db,\n            bot_db=bot_db,\n        )\n    else:\n        ensure_vip_monthly_tables(web_db)\n\n    member_status = _current_member_status(\n        customer,\n        now=current,\n        bot_db=bot_db,\n    )\n    level_name = str(member_status.get(\"current_level\") or \"普通魔丸\")\n    level_keys = _benefit_keys_for_level(level_name)\n\n    with sqlite3.connect(_web_db_path(web_db), timeout=15) as conn:\n        conn.row_factory = sqlite3.Row\n        rows = conn.execute(\n            \"\"\"\n            SELECT *\n            FROM vip_monthly_benefits\n            WHERE customer_id=? AND month_key=?\n            ORDER BY id ASC\n            \"\"\",\n            (customer, month),\n        ).fetchall()\n\n    raw_by_key = {str(row[\"benefit_key\"]): dict(row) for row in rows}\n    by_key = {\n        key: row\n        for key, row in raw_by_key.items()\n        if key in level_keys and str(row.get(\"status\") or \"\") != REVOKED\n    }\n    cash_rows = [\n        by_key[key]\n        for key in (MONTHLY_COUPON_200, MONTHLY_COUPON_500)\n        if key in by_key\n    ]\n    black_entitled = BLACK_DIAMOND_CHOICE in level_keys\n    black_row = by_key.get(BLACK_DIAMOND_CHOICE) if black_entitled else None\n    black_suspended = bool(\n        black_entitled\n        and member_status.get(\"is_due\")\n        and black_row is None\n    )\n\n    return {\n        \"month_key\": month,\n        \"current_level\": level_name,\n        \"is_due\": bool(member_status.get(\"is_due\")),\n        \"benefits\": list(by_key.values()),\n        \"by_key\": by_key,\n        \"cash_benefits\": cash_rows,\n        \"black_diamond\": black_row,\n        \"black_diamond_entitled\": black_entitled,\n        \"black_diamond_suspended\": black_suspended,\n        \"black_diamond_available\": bool(\n            black_entitled\n            and black_row\n            and str(black_row.get(\"status\")) == AVAILABLE\n        ),\n    }'''
text = replace_between(
    text,
    "def get_customer_vip_monthly_snapshot(\n",
    "def reserve_black_diamond_choice(\n",
    new_snapshot,
    "VIP snapshot function",
)
new_reserve = '''def reserve_black_diamond_choice(\n    customer_id: str | int,\n    choice_key: str,\n    *,\n    now: datetime | None = None,\n    web_db: str | Path | None = None,\n    bot_db: str | Path | None = None,\n) -> dict[str, Any]:\n    choice = str(choice_key or \"\").strip()\n    if choice not in BLACK_DIAMOND_CHOICES:\n        raise ValueError(\"不支援的黑鑽福利選項\")\n\n    current = _normalize_now(now)\n    sync_current_month_vip_benefits(\n        now=current,\n        web_db=web_db,\n        bot_db=bot_db,\n    )\n    customer = str(customer_id)\n    member_status = _current_member_status(\n        customer,\n        now=current,\n        bot_db=bot_db,\n    )\n    current_keys = _benefit_keys_for_level(\n        str(member_status.get(\"current_level\") or \"普通魔丸\")\n    )\n    if BLACK_DIAMOND_CHOICE not in current_keys:\n        raise ValueError(\"目前 VIP 等級沒有黑鑽尊享福利，無法兌換。\")\n\n    month = _month_key(current)\n    now_text = current.isoformat(timespec=\"seconds\")\n\n    with sqlite3.connect(_web_db_path(web_db), timeout=15) as conn:\n        conn.row_factory = sqlite3.Row\n        cur = conn.execute(\n            \"\"\"\n            UPDATE vip_monthly_benefits\n            SET status='reserved',\n                choice_key=?,\n                reserved_at=?,\n                reserved_channel_id=NULL,\n                updated_at=?\n            WHERE customer_id=?\n              AND month_key=?\n              AND benefit_key=?\n              AND status='available'\n            \"\"\",\n            (\n                choice,\n                now_text,\n                now_text,\n                customer,\n                month,\n                BLACK_DIAMOND_CHOICE,\n            ),\n        )\n        if int(cur.rowcount or 0) != 1:\n            raise ValueError(\"本月黑鑽尊享福利目前不可兌換，可能已使用、兌換中或暫停發放。\")\n        conn.commit()\n        row = conn.execute(\n            \"\"\"\n            SELECT * FROM vip_monthly_benefits\n            WHERE customer_id=? AND month_key=? AND benefit_key=?\n            LIMIT 1\n            \"\"\",\n            (customer, month, BLACK_DIAMOND_CHOICE),\n        ).fetchone()\n    return dict(row)'''
text = replace_between(
    text,
    "def reserve_black_diamond_choice(\n",
    "def bind_black_diamond_reservation_channel(\n",
    new_reserve,
    "VIP reserve function",
)
new_release = '''def release_black_diamond_choice(\n    customer_id: str | int,\n    *,\n    month_key: str | None = None,\n    now: datetime | None = None,\n    web_db: str | Path | None = None,\n    bot_db: str | Path | None = None,\n) -> bool:\n    current = _normalize_now(now)\n    month = str(month_key or _month_key(current))\n    customer = str(customer_id)\n    member_status = _current_member_status(\n        customer,\n        now=current,\n        bot_db=bot_db,\n    )\n    current_keys = _benefit_keys_for_level(\n        str(member_status.get(\"current_level\") or \"普通魔丸\")\n    )\n    next_status = AVAILABLE if BLACK_DIAMOND_CHOICE in current_keys else REVOKED\n    with sqlite3.connect(_web_db_path(web_db), timeout=15) as conn:\n        cur = conn.execute(\n            \"\"\"\n            UPDATE vip_monthly_benefits\n            SET status=?,\n                choice_key=NULL,\n                reserved_at=NULL,\n                reserved_channel_id=NULL,\n                updated_at=?\n            WHERE customer_id=? AND month_key=? AND benefit_key=? AND status='reserved'\n            \"\"\",\n            (\n                next_status,\n                current.isoformat(timespec=\"seconds\"),\n                customer,\n                month,\n                BLACK_DIAMOND_CHOICE,\n            ),\n        )\n        conn.commit()\n        return int(cur.rowcount or 0) == 1'''
text = replace_between(
    text,
    "def release_black_diamond_choice(\n",
    "def redeem_black_diamond_choice(\n",
    new_release,
    "VIP release function",
)
text = replace_once(
    text,
    '''        REDEEMED: "已使用",\n    }.get(str(status or ""), str(status or "未知"))\n''',
    '''        REDEEMED: "已使用",\n        REVOKED: "已失效（目前等級不符）",\n    }.get(str(status or ""), str(status or "未知"))\n''',
    "VIP status label",
)
path.write_text(text, encoding="utf-8")


# 5) VIP regression tests: black -> platinum revokes higher-tier benefits and blocks redemption.
path = Path("tests/test_vip_monthly_benefits.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "import sqlite3\n",
    "import sqlite3\n\nimport pytest\n",
    "VIP tests pytest import",
)
text = replace_once(
    text,
    "    OCTOBER_2026_USED_200_CUSTOMERS,\n",
    "    OCTOBER_2026_USED_200_CUSTOMERS,\n    REVOKED,\n",
    "VIP tests revoked import",
)
append = r'''


def _rewrite_customer_data(bot_db, customer_id: str, mutate):
    with sqlite3.connect(bot_db) as conn:
        row = conn.execute(
            "SELECT data_json FROM customers WHERE customer_id=?",
            (str(customer_id),),
        ).fetchone()
        assert row is not None
        data = json.loads(row[0])
        mutate(data)
        conn.execute(
            "UPDATE customers SET data_json=? WHERE customer_id=?",
            (json.dumps(data, ensure_ascii=False), str(customer_id)),
        )
        conn.commit()


def test_downgrade_revokes_unused_higher_tier_monthly_benefits_and_reupgrade_restores(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"
    customer_id = "black-to-platinum"
    _make_bot_db(
        bot_db,
        [
            (
                customer_id,
                {
                    "total_spent": 88888,
                    "vip_level_index": 6,
                    "last_order_at": "2026-11-05T10:00:00+08:00",
                },
            )
        ],
    )
    now = datetime(2026, 11, 5, 12, tzinfo=TAIPEI_TZ)

    black = get_customer_vip_monthly_snapshot(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert black["current_level"] == "黑鑽魔丸"
    assert {row["benefit_key"] for row in black["cash_benefits"]} == {
        MONTHLY_COUPON_200,
        MONTHLY_COUPON_500,
    }
    assert black["black_diamond_available"] is True

    def downgrade(data):
        data["vip_level_index"] = 3
        data["vip_progress_base_total_spent"] = 88888
        data["vip_progress_reset_active"] = True
        data["last_level_manual_fixed_at"] = "2026-11-05T11:00:00+08:00"

    _rewrite_customer_data(bot_db, customer_id, downgrade)
    platinum = get_customer_vip_monthly_snapshot(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )

    assert platinum["current_level"] == "白金魔丸"
    assert [row["benefit_key"] for row in platinum["cash_benefits"]] == [
        MONTHLY_COUPON_200
    ]
    assert platinum["black_diamond"] is None
    assert platinum["black_diamond_entitled"] is False
    assert platinum["black_diamond_available"] is False

    raw = {
        row["benefit_key"]: row["status"]
        for row in _benefit_rows(web_db, customer_id, "2026-11")
    }
    assert raw[MONTHLY_COUPON_200] == "available"
    assert raw[MONTHLY_COUPON_500] == REVOKED
    assert raw[BLACK_DIAMOND_CHOICE] == REVOKED

    with pytest.raises(ValueError, match="目前 VIP 等級沒有黑鑽尊享福利"):
        reserve_black_diamond_choice(
            customer_id,
            "entertainment_2h",
            now=now,
            bot_db=bot_db,
            web_db=web_db,
        )

    def upgrade_again(data):
        data["vip_level_index"] = 6
        data["vip_progress_reset_active"] = False
        data.pop("vip_progress_base_total_spent", None)
        data.pop("last_level_manual_fixed_at", None)

    _rewrite_customer_data(bot_db, customer_id, upgrade_again)
    restored = get_customer_vip_monthly_snapshot(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert {row["benefit_key"] for row in restored["cash_benefits"]} == {
        MONTHLY_COUPON_200,
        MONTHLY_COUPON_500,
    }
    assert restored["black_diamond_available"] is True


def test_releasing_reserved_black_benefit_after_downgrade_revokes_instead_of_reopening(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"
    customer_id = "reserved-then-downgraded"
    _make_bot_db(
        bot_db,
        [
            (
                customer_id,
                {
                    "total_spent": 88888,
                    "vip_level_index": 6,
                    "last_order_at": "2026-11-05T10:00:00+08:00",
                },
            )
        ],
    )
    now = datetime(2026, 11, 5, 12, tzinfo=TAIPEI_TZ)
    reserve_black_diamond_choice(
        customer_id,
        "entertainment_2h",
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )

    def downgrade(data):
        data["vip_level_index"] = 3
        data["vip_progress_base_total_spent"] = 88888
        data["vip_progress_reset_active"] = True
        data["last_level_manual_fixed_at"] = "2026-11-05T11:00:00+08:00"

    _rewrite_customer_data(bot_db, customer_id, downgrade)
    assert release_black_diamond_choice(
        customer_id,
        month_key="2026-11",
        now=now,
        web_db=web_db,
        bot_db=bot_db,
    ) is True

    raw = {
        row["benefit_key"]: row["status"]
        for row in _benefit_rows(web_db, customer_id, "2026-11")
    }
    assert raw[BLACK_DIAMOND_CHOICE] == REVOKED
'''
if "test_downgrade_revokes_unused_higher_tier_monthly_benefits" in text:
    raise SystemExit("VIP downgrade tests already present")
path.write_text(text.rstrip() + append + "\n", encoding="utf-8")


# 6) Accounting detector regression for point/cross-order store-funded service.
path = Path("tests/test_accounting_reconciliation.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "import sqlite3\n",
    "import json\nimport sqlite3\n",
    "accounting reconciliation json import",
)
text = replace_once(
    text,
    "                payout_base_amount INTEGER,\n                payment_method TEXT,\n",
    "                payout_base_amount INTEGER,\n                price_snapshot_json TEXT,\n                payment_method TEXT,\n",
    "accounting reconciliation test schema snapshot",
)
append = r'''


def test_store_funded_service_value_does_not_create_false_cs_payout_mismatch(tmp_path):
    root = _healthy_root(tmp_path)
    snapshot_json = json.dumps(
        {
            "preview": {
                "finance": {
                    "point_service_value": 60,
                    "benefit_service_value": 40,
                }
            }
        }
    )

    with sqlite3.connect(root / "web_dashboard.db") as conn:
        conn.execute(
            """
            UPDATE web_orders
            SET amount = 200,
                customer_pay_amount = 200,
                payout_base_amount = 300,
                price_snapshot_json = ?
            WHERE id = 1
            """,
            (snapshot_json,),
        )
        conn.execute(
            "UPDATE worker_payouts SET final_payout = 240 WHERE order_id = 1"
        )
        conn.execute(
            "UPDATE customer_service_payouts SET payout_amount = 10 WHERE order_id = 1"
        )

    snapshot = build_accounting_reconciliation_snapshot(root)
    order_issues = [
        issue
        for issue in snapshot["issues"]
        if issue.get("order_id") == 1
    ]
    assert "worker_payout_amount_mismatch" not in {
        issue["code"] for issue in order_issues
    }
    assert "customer_service_payout_amount_mismatch" not in {
        issue["code"] for issue in order_issues
    }
'''
if "test_store_funded_service_value_does_not_create_false_cs_payout_mismatch" in text:
    raise SystemExit("accounting reconciliation regression already present")
path.write_text(text.rstrip() + append + "\n", encoding="utf-8")


# 7) Safe repair itself uses the same store-funded CS base.
path = Path("tests/test_accounting_repair.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from datetime import datetime\n",
    "import json\nfrom datetime import datetime\n",
    "accounting repair json import",
)
append = r'''


def test_recalculate_unpaid_payouts_uses_store_funded_service_exclusion_for_cs():
    db = _make_session()
    try:
        _seed_order(db)
        order = db.get(WebOrder, 1)
        assert order is not None
        order.amount = 200
        order.customer_pay_amount = 200
        order.payout_base_amount = 300
        order.price_snapshot_json = json.dumps(
            {
                "preview": {
                    "finance": {
                        "point_service_value": 60,
                        "benefit_service_value": 40,
                    }
                }
            }
        )
        db.flush()

        apply_accounting_repair_in_session(
            db,
            order_id=1,
            action=RECALCULATE_UNPAID_PAYOUTS,
            actor={"id": "manager-1"},
        )
        db.flush()

        worker = db.scalar(
            select(WorkerPayout).where(WorkerPayout.order_id == 1)
        )
        cs = db.scalar(
            select(CustomerServicePayout).where(CustomerServicePayout.order_id == 1)
        )
        assert worker is not None
        assert worker.final_payout == 240
        assert cs is not None
        assert cs.payout_amount == 10
    finally:
        db.close()
'''
if "test_recalculate_unpaid_payouts_uses_store_funded_service_exclusion_for_cs" in text:
    raise SystemExit("accounting repair store-funded regression already present")
path.write_text(text.rstrip() + append + "\n", encoding="utf-8")
