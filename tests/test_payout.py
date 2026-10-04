from shared.payout import calculate_order_payout


def test_single_worker_payout():
    result = calculate_order_payout(
        total_amount=1000,
        worker_discord_ids=["worker_a"],
        named_bonus_worker_ids=[],
    )

    assert result.customer_service_payout == 50
    assert result.total_worker_payout == 800
    assert result.total_payout == 850
    assert result.worker_payouts[0].final_payout == 800


def test_two_workers_without_named_bonus():
    result = calculate_order_payout(
        total_amount=1000,
        worker_discord_ids=["worker_a", "worker_b"],
        named_bonus_worker_ids=[],
    )

    assert result.customer_service_payout == 50
    assert result.total_worker_payout == 800
    assert result.total_payout == 850

    payouts = {
        worker.worker_discord_id: worker.final_payout
        for worker in result.worker_payouts
    }

    assert payouts["worker_a"] == 400
    assert payouts["worker_b"] == 400


def test_two_workers_with_named_bonus_for_one_worker():
    result = calculate_order_payout(
        total_amount=1000,
        worker_discord_ids=["worker_a", "worker_b"],
        named_bonus_worker_ids=["worker_a"],
    )

    assert result.customer_service_payout == 50
    assert result.total_worker_payout == 825
    assert result.total_payout == 875

    payouts = {
        worker.worker_discord_id: worker.final_payout
        for worker in result.worker_payouts
    }

    assert payouts["worker_a"] == 425
    assert payouts["worker_b"] == 400