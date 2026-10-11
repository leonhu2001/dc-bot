import json
from dataclasses import dataclass


WORKER_BASE_PAYOUT_RATE = 0.80
CUSTOMER_SERVICE_PAYOUT_RATE = 0.05
WORKER_NAMED_BONUS_RATE = 0.05


@dataclass(frozen=True)
class WorkerPayoutResult:
    worker_discord_id: str
    gross_share: float
    base_rate: float
    base_payout: float
    named_bonus_rate: float
    named_bonus_amount: float
    final_payout: float
    has_named_bonus: bool


@dataclass(frozen=True)
class OrderPayoutResult:
    total_amount: int
    worker_count: int
    worker_base_rate: float
    customer_service_rate: float
    named_bonus_rate: float
    customer_service_payout: float
    worker_payouts: list[WorkerPayoutResult]
    total_worker_payout: float
    total_payout: float


def calculate_customer_service_payout(
    total_amount: int,
    customer_service_rate: float = CUSTOMER_SERVICE_PAYOUT_RATE,
) -> float:
    if total_amount <= 0:
        return 0

    return total_amount * customer_service_rate


def calculate_customer_service_payout_base_amount(
    *,
    payout_base_amount: int,
    price_snapshot_json=None,
) -> int:
    """Return the amount eligible for customer-service commission.

    Store-funded free service (points / cross-order benefit service value)
    still counts toward companion payout value, but must not create extra
    customer-service commission. This pure helper is the single source used by
    payout creation, safe repair, and accounting reconciliation.
    """
    base = max(0, int(payout_base_amount or 0))

    if isinstance(price_snapshot_json, dict):
        snapshot = price_snapshot_json
    else:
        try:
            snapshot = json.loads(str(price_snapshot_json or "{}"))
        except Exception:
            snapshot = {}

    if not isinstance(snapshot, dict):
        return base

    preview = (
        snapshot.get("preview")
        if isinstance(snapshot.get("preview"), dict)
        else snapshot
    )
    finance = (
        preview.get("finance")
        if isinstance(preview, dict)
        and isinstance(preview.get("finance"), dict)
        else {}
    )

    def _amount(name: str) -> int:
        try:
            return max(0, int(round(float(finance.get(name) or 0))))
        except (TypeError, ValueError):
            return 0

    store_funded_service = (
        _amount("point_service_value")
        + _amount("benefit_service_value")
    )
    return max(0, base - store_funded_service)


def calculate_order_payout(
    *,
    total_amount: int,
    worker_discord_ids: list[str],
    named_bonus_worker_ids: list[str] | set[str] | None = None,
    worker_base_rate: float = WORKER_BASE_PAYOUT_RATE,
    customer_service_rate: float = CUSTOMER_SERVICE_PAYOUT_RATE,
    named_bonus_rate: float = WORKER_NAMED_BONUS_RATE,
    customer_service_total_amount: int | None = None,
) -> OrderPayoutResult:
    customer_service_amount = (
        max(0, int(total_amount or 0))
        if customer_service_total_amount is None
        else max(0, int(customer_service_total_amount or 0))
    )

    if total_amount <= 0:
        customer_service_payout = calculate_customer_service_payout(
            customer_service_amount,
            customer_service_rate,
        )
        return OrderPayoutResult(
            total_amount=0,
            worker_count=0,
            worker_base_rate=worker_base_rate,
            customer_service_rate=customer_service_rate,
            named_bonus_rate=named_bonus_rate,
            customer_service_payout=customer_service_payout,
            worker_payouts=[],
            total_worker_payout=0,
            total_payout=customer_service_payout,
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
            customer_service_amount,
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

    gross_share = total_amount / worker_count
    worker_payouts = []

    for worker_id in unique_worker_ids:
        base_payout = gross_share * worker_base_rate
        has_named_bonus = worker_id in named_bonus_worker_set
        named_bonus_amount = gross_share * named_bonus_rate if has_named_bonus else 0
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
        customer_service_amount,
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
