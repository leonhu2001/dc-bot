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
        DESKTOP_SECRET: (400, 320),
        DESKTOP_TOPSECRET: (450, 320),
        MOBILE_SECRET: (380, 320),
        MOBILE_TOPSECRET: (420, 320),
    }


def test_protector_and_companion_receive_their_own_gross_basis():
    assert worker_basis_weights(
        DESKTOP_SECRET,
        [("guard", "booster"), ("companion", "companion")],
    ) == {
        "guard": 400,
        "companion": 320,
    }

    result = calculate_one_companion_one_guard_order_payout(
        rule_key=DESKTOP_SECRET,
        total_amount=720,
        worker_roles=[("guard", "booster"), ("companion", "companion")],
        customer_service_total_amount=720,
    )

    assert result is not None
    workers = {row.worker_discord_id: row for row in result.worker_payouts}
    assert workers["guard"].gross_share == 400
    assert workers["companion"].gross_share == 320
    assert workers["guard"].final_payout == 320
    assert workers["companion"].final_payout == 256
    assert result.customer_service_payout == 36


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
