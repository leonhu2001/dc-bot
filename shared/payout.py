import json
from dataclasses import dataclass


WORKER_BASE_PAYOUT_RATE = 0.80
# 客服不再固定抽訂單總額 5%。改為抽「扣除打手薪資後正毛利池」的 25%。
# 在基本打手 80% 的訂單上，效果仍等同總額 5%；打手分成較高時客服會同步下降。
CUSTOMER_SERVICE_MARGIN_SHARE_RATE = 0.25
# 保留舊常數名稱，避免其他模組匯入中斷；語意已改為「毛利池分成率」。
CUSTOMER_SERVICE_PAYOUT_RATE = CUSTOMER_SERVICE_MARGIN_SHARE_RATE
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
    *,
    worker_payout_amount: float | None = None,
    fallback_worker_rate: float = WORKER_BASE_PAYOUT_RATE,
) -> float:
    """Calculate customer-service payout from the positive margin pool.

    ``total_amount`` is the CS-eligible settlement base.  Store-funded gifted
    service should already have been removed from this amount by
    ``calculate_customer_service_payout_base_amount``.

    When the caller knows the worker payout attributable to the same base it
    should pass ``worker_payout_amount``.  The fallback keeps legacy/direct
    callers safe by assuming the normal worker base rate; with 80% workers and
    a 25% margin share this remains exactly 5% of the eligible amount.
    """
    eligible_amount = max(0, int(total_amount or 0))
    if eligible_amount <= 0:
        return 0

    rate = max(0.0, float(customer_service_rate or 0))
    if worker_payout_amount is None:
        worker_amount = eligible_amount * max(0.0, float(fallback_worker_rate or 0))
    else:
        worker_amount = max(0.0, float(worker_payout_amount or 0))

    margin_pool = max(0.0, float(eligible_amount) - worker_amount)
    return margin_pool * rate


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
    total_amount = max(0, int(total_amount or 0))
    customer_service_amount = (
        total_amount
        if customer_service_total_amount is None
        else max(0, int(customer_service_total_amount or 0))
    )

    unique_worker_ids: list[str] = []
    seen_worker_ids: set[str] = set()

    for worker_id in worker_discord_ids:
        worker_id_text = str(worker_id)
        if not worker_id_text or worker_id_text in seen_worker_ids:
            continue
        unique_worker_ids.append(worker_id_text)
        seen_worker_ids.add(worker_id_text)

    worker_count = len(unique_worker_ids)
    named_bonus_worker_set = {
        str(worker_id)
        for worker_id in (named_bonus_worker_ids or [])
        if str(worker_id)
    }

    worker_payouts: list[WorkerPayoutResult] = []
    if total_amount > 0 and worker_count > 0:
        gross_share = total_amount / worker_count
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

    # CS 的毛利池必須和 CS eligible base 使用同一個打手有效分成率。
    # 例如點數加時由店家補貼給打手時，該加時價值已從 CS base 排除，
    # 也不能再拿那段打手薪資去壓低客服分潤。
    if total_amount > 0 and total_worker_payout > 0:
        effective_worker_rate = total_worker_payout / total_amount
    else:
        effective_worker_rate = max(0.0, float(worker_base_rate or 0))

    cs_worker_payout = customer_service_amount * effective_worker_rate
    customer_service_payout = calculate_customer_service_payout(
        customer_service_amount,
        customer_service_rate,
        worker_payout_amount=cs_worker_payout,
        fallback_worker_rate=worker_base_rate,
    )
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
