import json
from dataclasses import dataclass


WORKER_BASE_PAYOUT_RATE = 0.80
LEGACY_CUSTOMER_SERVICE_PAYOUT_RATE = 0.05
# 客服新制：抽「扣除打手薪資後正毛利池」的 25%。
# 在基本打手 80% 的訂單上，效果仍等同總額 5%；打手分成較高時客服會同步下降。
CUSTOMER_SERVICE_MARGIN_SHARE_RATE = 0.25
# 保留舊常數名稱，讓既有匯入不中斷；新制語意為「毛利池分成率」。
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
    """Calculate new-policy CS payout from the positive margin pool."""
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

    Store-funded free service (points / cross-order loyalty service value) can
    count toward companion payout while being intentionally excluded from CS.
    Store-funded promotional cash coupons do NOT appear here: they preserve the
    normal payout base, so both workers and CS still receive their entitlement.
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
    legacy_customer_service_flat: bool = False,
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

    if legacy_customer_service_flat:
        applied_cs_rate = LEGACY_CUSTOMER_SERVICE_PAYOUT_RATE
        customer_service_payout = customer_service_amount * applied_cs_rate
    else:
        applied_cs_rate = max(0.0, float(customer_service_rate or 0))
        # CS 的毛利池必須和 CS eligible base 使用同一個打手有效分成率。
        # 點數/跨單免費服務若已從 CS base 排除，也不能再拿那段打手薪資
        # 去壓低客服分潤。
        if total_amount > 0 and total_worker_payout > 0:
            effective_worker_rate = total_worker_payout / total_amount
        else:
            effective_worker_rate = max(0.0, float(worker_base_rate or 0))

        cs_worker_payout = customer_service_amount * effective_worker_rate
        customer_service_payout = calculate_customer_service_payout(
            customer_service_amount,
            applied_cs_rate,
            worker_payout_amount=cs_worker_payout,
            fallback_worker_rate=worker_base_rate,
        )

    total_payout = total_worker_payout + customer_service_payout

    return OrderPayoutResult(
        total_amount=total_amount,
        worker_count=worker_count,
        worker_base_rate=worker_base_rate,
        customer_service_rate=applied_cs_rate,
        named_bonus_rate=named_bonus_rate,
        customer_service_payout=customer_service_payout,
        worker_payouts=worker_payouts,
        total_worker_payout=total_worker_payout,
        total_payout=total_payout,
    )
