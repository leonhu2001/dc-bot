from services.one_companion_one_guard_payout import (
    ONE_COMPANION_ONE_GUARD_PAYOUT_BASES,
    allocate_integer_gross_shares,
    calculate_one_companion_one_guard_order_payout,
    worker_basis_weights,
)


DESKTOP_SECRET = "basic_one_companion_one_guard_secret"
DESKTOP_TOPSECRET = "basic_one_companion_one_guard_topsecret"
MOBILE_SECRET = "basic_mobile_one_companion_one_guard_secret"
MOBILE_TOPSECRET = "basic_mobile_one_companion_one_guard_topsecret"


def test_one_companion_one_guard_payout_bases_match_prices():
    assert ONE_COMPANION_ONE_GUARD_PAYOUT_BASES == {
        DESKTOP_SECRET: (450, 350),
        DESKTOP_TOPSECRET: (500, 350),
        MOBILE_SECRET: (380, 320),
        MOBILE_TOPSECRET: (420, 320),
    }


def test_protector_and_companion_receive_their_own_gross_basis():
    assert worker_basis_weights(
        DESKTOP_SECRET,
        [("guard", "booster"), ("companion", "companion")],
    ) == {
        "guard": 450,
        "companion": 350,
    }

    result = calculate_one_companion_one_guard_order_payout(
        rule_key=DESKTOP_SECRET,
        total_amount=800,
        worker_roles=[("guard", "booster"), ("companion", "companion")],
        customer_service_total_amount=800,
    )

    assert result is not None
    workers = {row.worker_discord_id: row for row in result.worker_payouts}
    assert workers["guard"].gross_share == 450
    assert workers["companion"].gross_share == 350
    assert workers["guard"].final_payout == 360
    assert workers["companion"].final_payout == 280
    assert result.customer_service_payout == 40


def test_two_protectors_are_allowed_without_overallocating_gross_basis():
    assert worker_basis_weights(
        MOBILE_TOPSECRET,
        [("guard-a", "booster"), ("guard-b", "booster")],
    ) == {
        "guard-a": 420,
        "guard-b": 320,
    }

    assert allocate_integer_gross_shares(
        MOBILE_TOPSECRET,
        [("guard-a", "booster"), ("guard-b", "booster")],
        740,
    ) == {
        "guard-a": 420,
        "guard-b": 320,
    }


def test_two_companion_only_workers_do_not_get_special_allocation():
    assert worker_basis_weights(
        DESKTOP_SECRET,
        [("companion-a", "companion"), ("companion-b", "companion")],
    ) is None


def test_discounted_payout_base_scales_both_slots_proportionally():
    shares = allocate_integer_gross_shares(
        MOBILE_SECRET,
        [("guard", "booster"), ("companion", "companion")],
        686,
    )

    assert shares == {"guard": 372, "companion": 314}
    assert sum(shares.values()) == 686


def test_topsecret_900_invoice_uses_exact_500_plus_350_staff_bases():
    from services.one_companion_one_guard_payout import worker_basis_total
    result = calculate_one_companion_one_guard_order_payout(
        rule_key=DESKTOP_TOPSECRET,
        total_amount=900,
        worker_roles=[("tech", "booster"), ("entertain", "companion")],
        customer_service_total_amount=900,
    )
    assert result is not None
    workers = {row.worker_discord_id: row for row in result.worker_payouts}
    assert worker_basis_total(DESKTOP_TOPSECRET, 900) == 850
    assert workers["tech"].gross_share == 500
    assert workers["entertain"].gross_share == 350
    assert workers["tech"].final_payout == 400
    assert workers["entertain"].final_payout == 280
    assert result.customer_service_payout == 55
    # Store retains 165T after both worker payouts and the 25%-margin CS payout.
    assert 900 - sum(row.final_payout for row in workers.values()) - result.customer_service_payout == 165


def test_historical_770_topsecret_snapshot_keeps_old_450_plus_320_bases():
    from services.one_companion_one_guard_payout import (
        resolve_one_guard_unit_price, worker_basis_total,
    )
    quoted = resolve_one_guard_unit_price(DESKTOP_TOPSECRET, '{"rule":{"price":770}}')
    assert quoted == 770
    assert worker_basis_total(DESKTOP_TOPSECRET, 770, unit_price=quoted) == 770
    result = calculate_one_companion_one_guard_order_payout(
        rule_key=DESKTOP_TOPSECRET,
        total_amount=770,
        worker_roles=[("guard", "booster"), ("companion", "companion")],
        customer_service_total_amount=770,
        unit_price=quoted,
    )
    workers = {row.worker_discord_id: row for row in result.worker_payouts}
    assert workers["guard"].gross_share == 450
    assert workers["companion"].gross_share == 320
    assert result.customer_service_payout == 38.5


def test_timer_decimal_allocation_keeps_50t_per_hour_outside_staff_basis():
    from decimal import Decimal
    from services.one_companion_one_guard_payout import allocate_decimal_gross_shares

    current = allocate_decimal_gross_shares(
        DESKTOP_TOPSECRET, [("guard", "booster"), ("companion", "companion")],
        Decimal(900), unit_price=900, scale_to_worker_basis=True,
    )
    assert current == {"guard": Decimal(500), "companion": Decimal(350)}

    historical = allocate_decimal_gross_shares(
        DESKTOP_TOPSECRET, [("guard", "booster"), ("companion", "companion")],
        Decimal(770), unit_price=770, scale_to_worker_basis=True,
    )
    assert historical == {"guard": Decimal(450), "companion": Decimal(320)}
