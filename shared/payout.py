import json
from dataclasses import dataclass


WORKER_BASE_PAYOUT_RATE = 0.80
# 客服不再固定抽訂單總額 5%。改為抽「打手分潤後毛利池」的 25%。
# 基本打手 80% 時：20% 毛利池 × 25% = 訂單總額 5%，因此一般單與舊體感一致。
CUSTOMER_SERVICE_PAYOUT_RATE = 0.25
LEGACY_CUSTOMER_SERVICE_GROSS_RATE = 0.05
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
    # Persist/display the effective share of the order payout basis. Under the
    # new 25%-of-margin policy this is 5% at 80% worker, 3.75% at 85% worker.
    customer_service_rate: float
    named_bonus_rate: float
    customer_service_payout: float
    worker_payouts: list[WorkerPayoutResult]
    total_worker_payout: float
    total_payout: float


def calculate_customer_service_payout(
    total_amount: int,
    customer_service_rate: float = CUSTOMER_SERVICE_PAYOUT_RATE,
    *,
    effective_worker_rate: float = WORKER_BASE_PAYOUT_RATE,
) -> float:
    """Return CS payout as a share of the positive post-worker margin pool.

    ``customer_service_rate`` is the margin-pool share (25% by current policy),
    not a gross-order percentage.

    ``total_amount`` is the CS-eligible payout basis, not necessarily what the
    customer paid. Store-funded coupons therefore do not erase CS pay. Store-
    funded *extra service* is removed from this basis by
    ``calculate_customer_service_payout_base_amount`` so it does not create a
    second commission on a service the store is gifting.
    """
    amount = max(0, int(total_amount or 0))
    if amount <= 0:
        return 0

    worker_rate = max(0.0, min(1.0, float(effective_worker_rate or 0)))
    margin_share = max(0.0, min(1.0, float(customer_service_rate or 0)))
    margin_pool = amount * max(0.0, 1.0 - worker_rate)
    return margin_pool * margin_share


def calculate_customer_service_payout_base_amount(
    *,
    payout_base_amount: int,
    price_snapshot_json=None,
) -> int:
    """Return the amount eligible for customer-service margin sharing.

    Store-funded free service (points / cross-order benefit service value)
    still counts toward companion payout value, but must not create extra
    customer-service commission. Store-funded cash coupons are intentionally
    *not* removed here: the customer may pay less or zero, while workers and
    customer service still receive their normal payout on the subsidised basis.
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
    legacy_customer_service_gross_rate: float | None = None,
) -> OrderPayoutResult:
    customer_service_amount = (
        max(0, int(total_amount or 0))
        if customer_service_total_amount is None
        else max(0, int(customer_service_total_amount or 0))
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
    named_bonus_worker_set = {
        str(worker_id)
        for worker_id in (named_bonus_worker_ids or [])
        if str(worker_id)
    }
    named_count = sum(
        1
        for worker_id in unique_worker_ids
        if worker_id in named_bonus_worker_set
    )

    # Each active worker receives an equal gross share. Therefore the order-wide
    # effective worker rate is base + the named bonus weighted by the share of
    # workers who actually receive that bonus.
    effective_worker_rate = max(0.0, min(1.0, float(worker_base_rate or 0)))
    if worker_count > 0 and named_count > 0:
        effective_worker_rate += (
            max(0.0, float(named_bonus_rate or 0))
            * named_count
            / worker_count
        )
    effective_worker_rate = max(0.0, min(1.0, effective_worker_rate))

    if legacy_customer_service_gross_rate is not None:
        effective_customer_service_rate = max(
            0.0,
            min(1.0, float(legacy_customer_service_gross_rate or 0)),
        )
        customer_service_payout = customer_service_amount * effective_customer_service_rate
    else:
        customer_service_payout = calculate_customer_service_payout(
            customer_service_amount,
            customer_service_rate,
            effective_worker_rate=effective_worker_rate,
        )
        effective_customer_service_rate = (
            customer_service_payout / customer_service_amount
            if customer_service_amount > 0
            else 0.0
        )

    if total_amount <= 0:
        return OrderPayoutResult(
            total_amount=0,
            worker_count=worker_count,
            worker_base_rate=worker_base_rate,
            customer_service_rate=effective_customer_service_rate,
            named_bonus_rate=named_bonus_rate,
            customer_service_payout=customer_service_payout,
            worker_payouts=[],
            total_worker_payout=0,
            total_payout=customer_service_payout,
        )

    if worker_count <= 0:
        return OrderPayoutResult(
            total_amount=total_amount,
            worker_count=0,
            worker_base_rate=worker_base_rate,
            customer_service_rate=effective_customer_service_rate,
            named_bonus_rate=named_bonus_rate,
            customer_service_payout=customer_service_payout,
            worker_payouts=[],
            total_worker_payout=0,
            total_payout=customer_service_payout,
        )

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

    total_worker_payout = sum(worker.final_payout for worker in worker_payouts)
    total_payout = total_worker_payout + customer_service_payout

    return OrderPayoutResult(
        total_amount=total_amount,
        worker_count=worker_count,
        worker_base_rate=worker_base_rate,
        customer_service_rate=effective_customer_service_rate,
        named_bonus_rate=named_bonus_rate,
        customer_service_payout=customer_service_payout,
        worker_payouts=worker_payouts,
        total_worker_payout=total_worker_payout,
        total_payout=total_payout,
    )
