from dataclasses import dataclass


WORKER_BASE_PAYOUT_RATE = 0.80
CUSTOMER_SERVICE_PAYOUT_RATE = 0.05
WORKER_NAMED_BONUS_RATE = 0.05


@dataclass(frozen=True)
class WorkerPayoutResult:
    worker_discord_id: str
    gross_share: int
    base_rate: float
    base_payout: int
    named_bonus_rate: float
    named_bonus_amount: int
    final_payout: int
    has_named_bonus: bool


@dataclass(frozen=True)
class OrderPayoutResult:
    total_amount: int
    worker_count: int
    worker_base_rate: float
    customer_service_rate: float
    named_bonus_rate: float
    customer_service_payout: int
    worker_payouts: list[WorkerPayoutResult]
    total_worker_payout: int
    total_payout: int


def calculate_customer_service_payout(
    total_amount: int,
    customer_service_rate: float = CUSTOMER_SERVICE_PAYOUT_RATE,
) -> int:
    if total_amount <= 0:
        return 0

    return int(total_amount * customer_service_rate)


def calculate_order_payout(
    *,
    total_amount: int,
    worker_discord_ids: list[str],
    named_bonus_worker_ids: list[str] | set[str] | None = None,
    worker_base_rate: float = WORKER_BASE_PAYOUT_RATE,
    customer_service_rate: float = CUSTOMER_SERVICE_PAYOUT_RATE,
    named_bonus_rate: float = WORKER_NAMED_BONUS_RATE,
) -> OrderPayoutResult:
    if total_amount <= 0:
        return OrderPayoutResult(
            total_amount=0,
            worker_count=0,
            worker_base_rate=worker_base_rate,
            customer_service_rate=customer_service_rate,
            named_bonus_rate=named_bonus_rate,
            customer_service_payout=0,
            worker_payouts=[],
            total_worker_payout=0,
            total_payout=0,
        )

    unique_worker_ids = []
    seen_worker_ids = set()

    for worker_id in worker_discord_ids:
        worker_id_text = str(worker_id)

        if not worker_id_text:
            continue

        if worker_id_text in seen_worker_ids:
            continue

        unique_worker_ids.append(worker_id_text)
        seen_worker_ids.add(worker_id_text)

    worker_count = len(unique_worker_ids)

    if worker_count <= 0:
        customer_service_payout = calculate_customer_service_payout(
            total_amount,
            customer_service_rate,
        )

        return OrderPayoutResult(
            total_amount=total_amount,
            worker_count=0,
            worker_base_rate=worker_base_rate,
            customer_service_rate=customer_service_rate,
            named_bonus_rate=named_bonus_rate,
            customer_service_payout=customer_service_payout,
            worker_payouts=[],
            total_worker_payout=0,
            total_payout=customer_service_payout,
        )

    named_bonus_worker_set = {
        str(worker_id)
        for worker_id in (named_bonus_worker_ids or [])
        if str(worker_id)
    }

    gross_share = int(total_amount / worker_count)
    worker_payouts = []

    for worker_id in unique_worker_ids:
        base_payout = int(gross_share * worker_base_rate)
        has_named_bonus = worker_id in named_bonus_worker_set
        named_bonus_amount = int(gross_share * named_bonus_rate) if has_named_bonus else 0
        final_payout = base_payout + named_bonus_amount

        worker_payouts.append(
            WorkerPayoutResult(
                worker_discord_id=worker_id,
                gross_share=gross_share,
                base_rate=worker_base_rate,
                base_payout=base_payout,
                named_bonus_rate=named_bonus_rate,
                named_bonus_amount=named_bonus_amount,
                final_payout=final_payout,
                has_named_bonus=has_named_bonus,
            )
        )

    customer_service_payout = calculate_customer_service_payout(
        total_amount,
        customer_service_rate,
    )

    total_worker_payout = sum(worker.final_payout for worker in worker_payouts)
    total_payout = total_worker_payout + customer_service_payout

    return OrderPayoutResult(
        total_amount=total_amount,
        worker_count=worker_count,
        worker_base_rate=worker_base_rate,
        customer_service_rate=customer_service_rate,
        named_bonus_rate=named_bonus_rate,
        customer_service_payout=customer_service_payout,
        worker_payouts=worker_payouts,
        total_worker_payout=total_worker_payout,
        total_payout=total_payout,
    )