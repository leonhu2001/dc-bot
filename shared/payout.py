DEFAULT_PAYOUT_RATE = 0.8


def calculate_worker_payout(
    total_amount: int,
    worker_count: int,
    payout_rate: float = DEFAULT_PAYOUT_RATE,
) -> int:
    if total_amount <= 0:
        return 0

    if worker_count <= 0:
        return 0

    return int((total_amount / worker_count) * payout_rate)