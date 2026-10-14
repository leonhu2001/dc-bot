from __future__ import annotations

from services.payment_methods import WALLET_PAYMENT_METHOD


EXTERNAL_REVIEW_PAYMENT_METHODS = frozenset({"街口", "轉帳"})


def is_zero_amount_order(amount: int | None) -> bool:
    return int(amount or 0) == 0


def requires_external_payment_review(payment_method: str | None, amount: int | None) -> bool:
    return int(amount or 0) > 0 and str(payment_method or "") in EXTERNAL_REVIEW_PAYMENT_METHODS


def requires_wallet_debit(payment_method: str | None, amount: int | None) -> bool:
    return int(amount or 0) > 0 and str(payment_method or "") == WALLET_PAYMENT_METHOD
