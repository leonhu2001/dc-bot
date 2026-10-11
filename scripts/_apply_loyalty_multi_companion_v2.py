from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Loyalty core: companion-count-neutral scopes, companion service units,
# one-time repair of already-processed progress/coupons.
# ---------------------------------------------------------------------------
replace_once(
    "services/loyalty_benefits.py",
    '''        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS loyalty_order_events (
                order_id INTEGER PRIMARY KEY,
                customer_discord_id TEXT,
                scope_key TEXT,
                paid_units REAL NOT NULL DEFAULT 0,
                issued_coupon_count INTEGER NOT NULL DEFAULT 0,
                processed_at TEXT NOT NULL,
                note TEXT
            )
        """))
''',
    '''        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS loyalty_order_events (
                order_id INTEGER PRIMARY KEY,
                customer_discord_id TEXT,
                scope_key TEXT,
                paid_units REAL NOT NULL DEFAULT 0,
                issued_coupon_count INTEGER NOT NULL DEFAULT 0,
                processed_at TEXT NOT NULL,
                note TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS loyalty_migrations (
                migration_key TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL,
                note TEXT
            )
        """))
        _repair_companion_loyalty_v2(conn)
''',
)

replace_once(
    "services/loyalty_benefits.py",
    '''def loyalty_scope_key(rule_key: str, player_count: int = 1) -> str:
    rule = _rule_for_key(rule_key)
    players = max(1, int(player_count or 1))
    if rule is None or not bool(getattr(rule, "player_count_enabled", False)):
        players = 1
    return f"{str(rule_key)}|players:{players}"


def _coupon_title(row: dict[str, Any]) -> str:
    kind = str(row.get("benefit_kind") or "")
    units = float(row.get("benefit_units") or 0)
    if kind == "extra_hours":
        benefit = "+30 分鐘" if abs(units - 0.5) < 0.001 else f"+{units:g} 小時"
    else:
        benefit = f"+{int(round(units))} 局"
    players = max(1, int(row.get("player_count") or 1))
    suffix = f"｜{players}位" if players > 1 else ""
    return f"{row.get('rule_label') or row.get('rule_key')}｜{benefit}{suffix}"
''',
    '''_LOYALTY_SCOPE_FAMILY_ALIASES = {
    # 同一個遊戲／服務只是陪玩席位數不同，必須共用同一個老闆福利池。
    "basic_entertain_single": "basic_entertain",
    "basic_entertain_double": "basic_entertain",
    "basic_mobile_entertain_single": "basic_mobile_entertain",
    "basic_mobile_entertain_double": "basic_mobile_entertain",
}
_LOYALTY_COMPANION_MIGRATION_KEY = "20261011_companion_service_units_v2"


def _canonical_loyalty_rule_key(rule_key: str) -> str:
    key = str(rule_key or "").strip()
    return _LOYALTY_SCOPE_FAMILY_ALIASES.get(key, key)


def _service_companion_count(rule: Any, player_count: int = 1) -> int:
    requested = max(1, int(player_count or 1))
    if rule is None:
        return requested
    required = getattr(rule, "required_staff_count", 1)
    if str(required) == "player_count":
        return requested
    try:
        return max(1, int(required or 1))
    except (TypeError, ValueError):
        return requested if bool(getattr(rule, "player_count_enabled", False)) else 1


def _extract_player_count(row: dict[str, Any]) -> int:
    try:
        import json

        snapshot = json.loads(str(row.get("price_snapshot_json") or "{}"))
        if isinstance(snapshot, dict):
            preview = (
                snapshot.get("preview")
                if isinstance(snapshot.get("preview"), dict)
                else snapshot
            )
            quote = (
                preview.get("quote")
                if isinstance(preview, dict)
                and isinstance(preview.get("quote"), dict)
                else {}
            )
            input_data = snapshot.get("input") if isinstance(snapshot.get("input"), dict) else {}
            return max(1, int(quote.get("player_count") or input_data.get("player_count") or 1))
    except Exception:
        pass
    return 1


def _loyalty_display_label(rule_key: str, fallback: object = "") -> str:
    label = str(fallback or rule_key or "").strip()
    for suffix in ("｜單陪", "｜雙陪", "｜三陪", "｜四陪"):
        if label.endswith(suffix):
            label = label[: -len(suffix)]
            break
    return label or str(rule_key or "")


def loyalty_scope_key(rule_key: str, player_count: int = 1) -> str:
    # player_count intentionally does not participate in the scope. A customer
    # owns one progress pool per game/service family, regardless of 1/2/3/4陪.
    _ = player_count
    rule = _rule_for_key(rule_key)
    category = str(getattr(rule, "category", "") or "unknown").strip()
    family = _canonical_loyalty_rule_key(rule_key)
    return f"{category}|{family}"


def _coupon_title(row: dict[str, Any]) -> str:
    kind = str(row.get("benefit_kind") or "")
    units = float(row.get("benefit_units") or 0)
    if kind == "extra_hours":
        benefit = "折抵 30 分鐘額度" if abs(units - 0.5) < 0.001 else f"折抵 {units:g} 小時額度"
    else:
        benefit = f"折抵 {int(round(units))} 局額度"
    label = _loyalty_display_label(str(row.get("rule_key") or ""), row.get("rule_label"))
    return f"{label}｜{benefit}"
''',
)

replace_once(
    "services/loyalty_benefits.py",
    '''        players = max(1, int(row.get("player_count") or 1))
        row["title"] = str(row.get("rule_label") or row.get("rule_key")) + (
            f"｜{players}位" if players > 1 else ""
        )
''',
    '''        row["title"] = _loyalty_display_label(
            str(row.get("rule_key") or ""),
            row.get("rule_label"),
        )
''',
)

replace_once(
    "services/loyalty_benefits.py",
    '''def calculate_coupon_service_value(
    *,
    rule_key: str,
    player_count: int,
    coupon: dict[str, Any] | None,
) -> int:
    """Store-funded worker payout value, always based on normal list price.

    VIP/customer discounts never lower the value of gifted work.
    """
    if not coupon:
        return 0
    rule = _rule_for_key(rule_key)
    if rule is None:
        return 0
    kind = str(coupon.get("benefit_kind") or "")
    units = float(coupon.get("benefit_units") or 0)
    if units <= 0:
        return 0
    if kind not in {"extra_hours", "extra_games"}:
        return 0
    per_unit = max(0, int(getattr(rule, "price", 0) or 0))
    if bool(getattr(rule, "price_multiply_player_count", False)):
        per_unit *= max(1, int(player_count or 1))
    return max(0, int(round(per_unit * units)))


def coupon_service_note(coupon: dict[str, Any] | None) -> str:
    if not coupon:
        return ""
    kind = str(coupon.get("benefit_kind") or "")
    units = float(coupon.get("benefit_units") or 0)
    if kind == "extra_hours":
        return "福利券：服務時間 +30 分鐘" if abs(units - 0.5) < 0.001 else f"福利券：服務時間 +{units:g} 小時"
    return f"福利券：服務局數 +{int(round(units))} 局"
''',
    '''def calculate_coupon_service_value(
    *,
    rule_key: str,
    player_count: int,
    coupon: dict[str, Any] | None,
) -> int:
    """Cash value of one customer benefit service-unit credit at list price.

    One benefit hour/game always means one companion's service unit. Multi-
    companion orders therefore redeem the same credit proportionally instead
    of multiplying the coupon by the number of companions.
    """
    if not coupon:
        return 0
    rule = _rule_for_key(rule_key)
    if rule is None:
        return 0
    kind = str(coupon.get("benefit_kind") or "")
    units = float(coupon.get("benefit_units") or 0)
    if units <= 0 or kind not in {"extra_hours", "extra_games"}:
        return 0

    requested_players = max(1, int(player_count or 1))
    companion_count = _service_companion_count(rule, requested_players)
    order_unit_price = max(0, int(getattr(rule, "price", 0) or 0))
    if bool(getattr(rule, "price_multiply_player_count", False)):
        order_unit_price *= requested_players

    per_companion_unit = order_unit_price / max(1, companion_count)
    return max(0, int(round(per_companion_unit * units)))


def coupon_service_note(coupon: dict[str, Any] | None) -> str:
    if not coupon:
        return ""
    kind = str(coupon.get("benefit_kind") or "")
    units = float(coupon.get("benefit_units") or 0)
    if kind == "extra_hours":
        amount = "30 分鐘" if abs(units - 0.5) < 0.001 else f"{units:g} 小時"
        return f"福利券：折抵 {amount} 服務額度"
    return f"福利券：折抵 {int(round(units))} 局服務額度"
''',
)

replace_once(
    "services/loyalty_benefits.py",
    '''    return max(0, amount)


def process_closed_order(order_id: int) -> dict[str, Any] | None:
''',
    '''    return max(0, amount)


def _repair_companion_loyalty_v2(conn) -> None:
    """One-time repair for progress created before companion service units.

    Only orders that already have loyalty_order_events are recalculated. Orders
    not yet processed remain untouched so the normal close-order flow can issue
    rewards exactly once after deployment.
    """
    applied = conn.execute(text("""
        SELECT migration_key
        FROM loyalty_migrations
        WHERE migration_key = :migration_key
        LIMIT 1
    """), {"migration_key": _LOYALTY_COMPANION_MIGRATION_KEY}).first()
    if applied is not None:
        return

    has_orders = conn.execute(text("""
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'web_orders'
        LIMIT 1
    """)).first()
    if has_orders is None:
        conn.execute(text("""
            INSERT INTO loyalty_migrations (migration_key, applied_at, note)
            VALUES (:migration_key, :applied_at, 'no_web_orders_table')
        """), {
            "migration_key": _LOYALTY_COMPANION_MIGRATION_KEY,
            "applied_at": get_taipei_now_iso(),
        })
        return

    now = get_taipei_now_iso()

    # Existing coupons keep their status/order links, but become usable across
    # companion counts inside the same canonical game/service scope.
    coupon_rows = conn.execute(text("""
        SELECT id, rule_key, rule_label, player_count
        FROM customer_benefit_coupons
    """)).mappings().all()
    for raw in coupon_rows:
        row = dict(raw)
        rule_key = str(row.get("rule_key") or "").strip()
        if loyalty_policy_for_rule(rule_key) is None:
            continue
        scope = loyalty_scope_key(rule_key, int(row.get("player_count") or 1))
        conn.execute(text("""
            UPDATE customer_benefit_coupons
            SET scope_key = :scope_key,
                rule_label = :rule_label
            WHERE id = :coupon_id
        """), {
            "scope_key": scope,
            "rule_label": _loyalty_display_label(rule_key, row.get("rule_label")),
            "coupon_id": int(row["id"]),
        })

    # Old progress rows were split by player count. Remove eligible rows and
    # rebuild them from already-processed closed orders so double/triple/quad
    # orders receive the missing multiplier without double-counting.
    progress_rows = conn.execute(text("""
        SELECT customer_discord_id, scope_key, rule_key
        FROM customer_loyalty_progress
    """)).mappings().all()
    for raw in progress_rows:
        rule_key = str(raw.get("rule_key") or "").strip()
        if loyalty_policy_for_rule(rule_key) is None:
            continue
        conn.execute(text("""
            DELETE FROM customer_loyalty_progress
            WHERE customer_discord_id = :customer_id
              AND scope_key = :scope_key
        """), {
            "customer_id": str(raw.get("customer_discord_id") or ""),
            "scope_key": str(raw.get("scope_key") or ""),
        })

    order_rows = conn.execute(text("""
        SELECT o.id, o.customer_discord_id, o.order_rule_key, o.quantity,
               o.amount, o.original_amount, o.customer_pay_amount,
               o.status, o.created_at, o.updated_at, o.closed_at,
               o.price_snapshot_json, o.ticket_channel_id
        FROM web_orders o
        INNER JOIN loyalty_order_events e ON e.order_id = o.id
        WHERE o.status = 'closed'
        ORDER BY o.id ASC
    """)).mappings().all()

    aggregates: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in order_rows:
        row = dict(raw)
        customer_id = str(row.get("customer_discord_id") or "").strip()
        rule_key = str(row.get("order_rule_key") or "").strip()
        policy = loyalty_policy_for_rule(rule_key)
        if (
            not customer_id
            or policy is None
            or not _event_time_is_in_scope(row)
            or _qualifying_paid_amount(row) <= 0
        ):
            continue

        rule = _rule_for_key(rule_key)
        player_count = _extract_player_count(row)
        companion_count = _service_companion_count(rule, player_count)
        paid_units = float(max(0, int(row.get("quantity") or 0)) * companion_count)
        scope = loyalty_scope_key(rule_key, player_count)
        key = (customer_id, scope)
        bucket = aggregates.setdefault(key, {
            "customer_id": customer_id,
            "scope_key": scope,
            "rule_key": rule_key,
            "rule_label": _loyalty_display_label(
                rule_key,
                getattr(rule, "label", rule_key),
            ),
            "pricing_type": policy["pricing_type"],
            "threshold_units": float(policy["threshold_units"]),
            "benefit_kind": policy["benefit_kind"],
            "benefit_units": float(policy["benefit_units"]),
            "paid_units": 0.0,
        })
        bucket["paid_units"] = float(bucket["paid_units"]) + paid_units

        conn.execute(text("""
            UPDATE loyalty_order_events
            SET scope_key = :scope_key,
                paid_units = :paid_units,
                note = CASE
                    WHEN note IS NULL OR TRIM(note) = '' THEN 'companion_units_v2'
                    ELSE note || ';companion_units_v2'
                END
            WHERE order_id = :order_id
        """), {
            "scope_key": scope,
            "paid_units": paid_units,
            "order_id": int(row["id"]),
        })

    for bucket in aggregates.values():
        total = float(bucket["paid_units"])
        threshold = float(bucket["threshold_units"])
        earned_count = int(total // threshold) if threshold > 0 else 0
        remainder = total - earned_count * threshold if threshold > 0 else 0.0

        existing_count = int(conn.execute(text("""
            SELECT COUNT(*)
            FROM customer_benefit_coupons
            WHERE customer_discord_id = :customer_id
              AND scope_key = :scope_key
              AND source = 'loyalty'
        """), {
            "customer_id": bucket["customer_id"],
            "scope_key": bucket["scope_key"],
        }).scalar() or 0)

        missing_count = max(0, earned_count - existing_count)
        expires_at = _coupon_expiry_iso(now)
        for _ in range(missing_count):
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
                "customer_id": bucket["customer_id"],
                "scope_key": bucket["scope_key"],
                "rule_key": bucket["rule_key"],
                "rule_label": bucket["rule_label"],
                "pricing_type": bucket["pricing_type"],
                "benefit_kind": bucket["benefit_kind"],
                "benefit_units": bucket["benefit_units"],
                "issued_at": now,
                "expires_at": expires_at,
            })

        conn.execute(text("""
            INSERT INTO customer_loyalty_progress (
                customer_discord_id, scope_key, rule_key, rule_label,
                pricing_type, player_count, progress_units, threshold_units,
                benefit_kind, benefit_units, updated_at
            ) VALUES (
                :customer_id, :scope_key, :rule_key, :rule_label,
                :pricing_type, 1, :progress_units, :threshold_units,
                :benefit_kind, :benefit_units, :updated_at
            )
            ON CONFLICT(customer_discord_id, scope_key) DO UPDATE SET
                rule_key = excluded.rule_key,
                rule_label = excluded.rule_label,
                pricing_type = excluded.pricing_type,
                player_count = 1,
                progress_units = excluded.progress_units,
                threshold_units = excluded.threshold_units,
                benefit_kind = excluded.benefit_kind,
                benefit_units = excluded.benefit_units,
                updated_at = excluded.updated_at
        """), {
            "customer_id": bucket["customer_id"],
            "scope_key": bucket["scope_key"],
            "rule_key": bucket["rule_key"],
            "rule_label": bucket["rule_label"],
            "pricing_type": bucket["pricing_type"],
            "progress_units": remainder,
            "threshold_units": threshold,
            "benefit_kind": bucket["benefit_kind"],
            "benefit_units": bucket["benefit_units"],
            "updated_at": now,
        })

    conn.execute(text("""
        INSERT INTO loyalty_migrations (migration_key, applied_at, note)
        VALUES (:migration_key, :applied_at, :note)
    """), {
        "migration_key": _LOYALTY_COMPANION_MIGRATION_KEY,
        "applied_at": now,
        "note": f"repaired_scopes={len(aggregates)}",
    })


def process_closed_order(order_id: int) -> dict[str, Any] | None:
''',
)

replace_once(
    "services/loyalty_benefits.py",
    '''            player_count = 1
            try:
                import json
                snapshot = json.loads(str(row.get("price_snapshot_json") or "{}"))
                if isinstance(snapshot, dict):
                    preview = snapshot.get("preview") if isinstance(snapshot.get("preview"), dict) else snapshot
                    quote = preview.get("quote") if isinstance(preview, dict) and isinstance(preview.get("quote"), dict) else {}
                    input_data = snapshot.get("input") if isinstance(snapshot.get("input"), dict) else {}
                    player_count = int(quote.get("player_count") or input_data.get("player_count") or 1)
            except Exception:
                player_count = 1

            rule = _rule_for_key(rule_key)
            if rule is None or not bool(getattr(rule, "player_count_enabled", False)):
                player_count = 1
            player_count = max(1, player_count)
            scope = loyalty_scope_key(rule_key, player_count)
            paid_units = float(max(0, int(row.get("quantity") or 0)))
''',
    '''            player_count = _extract_player_count(row)
            rule = _rule_for_key(rule_key)
            companion_count = _service_companion_count(rule, player_count)
            scope = loyalty_scope_key(rule_key, player_count)
            paid_units = float(
                max(0, int(row.get("quantity") or 0)) * companion_count
            )
''',
)

replace_once(
    "services/loyalty_benefits.py",
    '''            rule_label = str(getattr(rule, "label", rule_key))
''',
    '''            rule_label = _loyalty_display_label(
                rule_key,
                getattr(rule, "label", rule_key),
            )
''',
)

# ---------------------------------------------------------------------------
# Checkout: benefit coupon is now a store-funded cash reduction of the service
# portion, not extra gifted play time. It never reduces payout base.
# ---------------------------------------------------------------------------
replace_once(
    "web/app/services/checkout_preview.py",
    '''    effective_specify_fee = max(0, specify_fee - point_waived_specify)
    after_point = max(0, after_vip - point_cash_discount)
    subtotal = max(0, after_point + effective_specify_fee)
    wallet_use = min(wallet_balance, subtotal) if use_wallet else 0
    remaining = max(0, subtotal - wallet_use)
''',
    '''    effective_specify_fee = max(0, specify_fee - point_waived_specify)
    after_point = max(0, after_vip - point_cash_discount)
    benefit_discount_amount = (
        min(after_point, benefit_service_value)
        if benefit_coupon
        else 0
    )
    after_benefit = max(0, after_point - benefit_discount_amount)
    subtotal = max(0, after_benefit + effective_specify_fee)
    wallet_use = min(wallet_balance, subtotal) if use_wallet else 0
    remaining = max(0, subtotal - wallet_use)
''',
)

replace_once(
    "web/app/services/checkout_preview.py",
    '''    # All point rewards are funded by the store. Customer discounts and free
    # specify do not lower worker payout, while point-added time/games add the
    # equivalent discounted service value to the payout base.
    payout_base = max(
        0,
        after_vip + specify_fee + point_service_value + benefit_service_value,
    )
    point_store_absorbed = max(
        0,
        point_cash_discount + point_waived_specify + point_service_value,
    )
    benefit_store_absorbed = benefit_service_value if benefit_coupon else 0
''',
    '''    # Point rewards and loyalty benefits are store-funded. A loyalty benefit
    # only lowers what the customer pays; it must not reduce worker payout or
    # add phantom service time to the payout base.
    payout_base = max(
        0,
        after_vip + specify_fee + point_service_value,
    )
    point_store_absorbed = max(
        0,
        point_cash_discount + point_waived_specify + point_service_value,
    )
    benefit_store_absorbed = benefit_discount_amount
''',
)

replace_once(
    "web/app/services/checkout_preview.py",
    '''        "cash_coupon_amount": 0,
        "fixed_discount_amount": 0,
''',
    '''        "cash_coupon_amount": benefit_discount_amount,
        "fixed_discount_amount": 0,
''',
)

replace_once(
    "web/app/services/checkout_preview.py",
    '''        "benefit_service_note": coupon_service_note(benefit_coupon),
        "benefit_service_value": benefit_service_value,
        "benefit_store_absorbed_amount": benefit_store_absorbed,
''',
    '''        "benefit_service_note": coupon_service_note(benefit_coupon),
        "benefit_service_value": benefit_service_value,
        "benefit_discount_amount": benefit_discount_amount,
        "benefit_store_absorbed_amount": benefit_store_absorbed,
''',
)

# ---------------------------------------------------------------------------
# Regression tests. Replace old expectations that explicitly enforced the
# broken one-pool-per-companion-count behavior.
# ---------------------------------------------------------------------------
(ROOT / "tests/test_loyalty_companion_count.py").write_text(
    '''from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, text

from services import loyalty_benefits as loyalty
from services.order_rules import ORDER_RULES


def _test_engine(tmp_path: Path):
    db = tmp_path / "loyalty_companion_count.db"
    return create_engine(
        f"sqlite:///{db}",
        connect_args={"check_same_thread": False},
    )


def _insert_coupon(conn, *, coupon_id: int, customer_id: str, rule_key: str) -> None:
    rule = ORDER_RULES[rule_key]
    scope_key = loyalty.loyalty_scope_key(rule_key, 1)
    conn.execute(text("""
        INSERT INTO customer_benefit_coupons (
            id,
            customer_discord_id,
            scope_key,
            rule_key,
            rule_label,
            pricing_type,
            player_count,
            benefit_kind,
            benefit_units,
            status,
            source,
            issued_at,
            expires_at
        ) VALUES (
            :id,
            :customer_id,
            :scope_key,
            :rule_key,
            :rule_label,
            'hourly',
            1,
            'extra_hours',
            0.5,
            'active',
            'loyalty',
            '2026-10-11T00:00:00+08:00',
            '2099-01-01T00:00:00+08:00'
        )
    """), {
        "id": coupon_id,
        "customer_id": customer_id,
        "scope_key": scope_key,
        "rule_key": rule_key,
        "rule_label": rule.label,
    })


def test_single_double_and_dynamic_companion_counts_share_the_same_scope():
    assert loyalty.loyalty_scope_key("basic_entertain_single", 1) == loyalty.loyalty_scope_key(
        "basic_entertain_double", 2
    )

    scopes = {
        loyalty.loyalty_scope_key("valorant_entertain_ng", players)
        for players in (1, 2, 3, 4)
    }
    assert len(scopes) == 1


def test_different_games_never_share_loyalty_scope():
    valorant = loyalty.loyalty_scope_key("valorant_entertain_ng", 2)
    lol = loyalty.loyalty_scope_key("lol_entertain_ng", 2)
    apex = loyalty.loyalty_scope_key("apex_entertain_platinum", 2)
    assert len({valorant, lol, apex}) == 3


def test_single_and_double_orders_can_use_the_same_family_coupon(monkeypatch, tmp_path: Path):
    test_engine = _test_engine(tmp_path)
    monkeypatch.setattr(loyalty, "engine", test_engine)
    loyalty.ensure_loyalty_tables(test_engine)

    with test_engine.begin() as conn:
        _insert_coupon(
            conn,
            coupon_id=1,
            customer_id="123",
            rule_key="basic_entertain_single",
        )

    single = loyalty.list_applicable_coupons(
        "123",
        rule_key="basic_entertain_single",
        player_count=1,
    )
    double = loyalty.list_applicable_coupons(
        "123",
        rule_key="basic_entertain_double",
        player_count=2,
    )

    assert [row["id"] for row in single] == [1]
    assert [row["id"] for row in double] == [1]
    assert "單陪" not in single[0]["title"]
    assert "雙陪" not in double[0]["title"]
    assert "折抵" in single[0]["title"]


def test_coupon_value_is_one_companion_service_unit_not_whole_multi_order():
    coupon = {"benefit_kind": "extra_hours", "benefit_units": 0.5}

    single_value = loyalty.calculate_coupon_service_value(
        rule_key="basic_entertain_single",
        player_count=1,
        coupon=coupon,
    )
    double_value = loyalty.calculate_coupon_service_value(
        rule_key="basic_entertain_double",
        player_count=2,
        coupon=coupon,
    )
    valorant_four_value = loyalty.calculate_coupon_service_value(
        rule_key="valorant_entertain_ng",
        player_count=4,
        coupon=coupon,
    )

    assert single_value == 160
    assert double_value == 150
    assert valorant_four_value == 150


def test_existing_processed_progress_is_repaired_from_real_companion_units(monkeypatch, tmp_path: Path):
    test_engine = _test_engine(tmp_path)
    monkeypatch.setattr(loyalty, "engine", test_engine)

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

    loyalty.ensure_loyalty_tables(test_engine)

    # Reset only the marker so this fixture can represent a pre-migration DB.
    with test_engine.begin() as conn:
        conn.execute(text("DELETE FROM loyalty_migrations"))
        old_scope = "valorant_entertain_ng|players:2"
        conn.execute(text("""
            INSERT INTO customer_loyalty_progress (
                customer_discord_id, scope_key, rule_key, rule_label,
                pricing_type, player_count, progress_units, threshold_units,
                benefit_kind, benefit_units, updated_at
            ) VALUES (
                '123', :scope_key, 'valorant_entertain_ng', 'VALORANT｜娛樂陪｜一般',
                'hourly', 2, 6, 10, 'extra_hours', 0.5, '2026-10-11T01:00:00+08:00'
            )
        """), {"scope_key": old_scope})
        for order_id in (1, 2):
            conn.execute(text("""
                INSERT INTO web_orders (
                    id, customer_discord_id, order_rule_key, quantity,
                    amount, original_amount, customer_pay_amount, status,
                    created_at, updated_at, closed_at, price_snapshot_json,
                    ticket_channel_id
                ) VALUES (
                    :id, '123', 'valorant_entertain_ng', 3,
                    1800, 1800, 1800, 'closed',
                    '2026-10-11T01:00:00+08:00',
                    '2026-10-11T02:00:00+08:00',
                    '2026-10-11T02:00:00+08:00',
                    :snapshot, 'ticket'
                )
            """), {
                "id": order_id,
                "snapshot": json.dumps({"input": {"player_count": 2}}),
            })
            conn.execute(text("""
                INSERT INTO loyalty_order_events (
                    order_id, customer_discord_id, scope_key, paid_units,
                    issued_coupon_count, processed_at, note
                ) VALUES (
                    :id, '123', :scope_key, 3, 0,
                    '2026-10-11T02:00:00+08:00', NULL
                )
            """), {"id": order_id, "scope_key": old_scope})

    loyalty.ensure_loyalty_tables(test_engine)
    data = loyalty.list_customer_loyalty("123")

    # 2 orders × 3h × 2 companions = 12 service-hours => one 0.5h coupon + 2h progress.
    assert data["active_count"] == 1
    assert len(data["progress"]) == 1
    assert data["progress"][0]["progress_units"] == 2
    assert "players:" not in data["progress"][0]["scope_key"]

    # The repair is idempotent and must not issue another coupon on the next startup.
    loyalty.ensure_loyalty_tables(test_engine)
    assert loyalty.list_customer_loyalty("123")["active_count"] == 1
''',
    encoding="utf-8",
)

(ROOT / "tests/test_loyalty_checkout_discount.py").write_text(
    '''from web.app.services.checkout_preview import calculate_checkout_financials


def test_loyalty_coupon_reduces_customer_service_charge_without_reducing_payout():
    coupon = {"id": 7, "title": "VALORANT｜娛樂陪｜折抵 30 分鐘額度", "benefit_kind": "extra_hours", "benefit_units": 0.5}

    finance = calculate_checkout_financials(
        service_amount=1200,
        vip_pay_rate=100,
        specify_fee=0,
        point_item=None,
        wallet_balance=0,
        use_wallet=False,
        benefit_coupon=coupon,
        benefit_service_value=150,
    )

    assert finance["benefit_discount_amount"] == 150
    assert finance["customer_pay_amount"] == 1050
    assert finance["cash_coupon_amount"] == 150
    assert finance["store_absorbed_amount"] == 150
    assert finance["payout_base_amount"] == 1200


def test_loyalty_coupon_only_discounts_service_and_never_makes_total_negative():
    coupon = {"id": 8, "title": "福利券", "benefit_kind": "extra_hours", "benefit_units": 10}

    finance = calculate_checkout_financials(
        service_amount=100,
        vip_pay_rate=100,
        specify_fee=80,
        point_item=None,
        wallet_balance=0,
        use_wallet=False,
        benefit_coupon=coupon,
        benefit_service_value=9999,
    )

    assert finance["benefit_discount_amount"] == 100
    assert finance["customer_pay_amount"] == 80
    assert finance["payout_base_amount"] == 180
    assert finance["store_absorbed_amount"] == 100
''',
    encoding="utf-8",
)

print("loyalty multi-companion v2 patch applied")
