from __future__ import annotations

from typing import Any


WALLET_PAYMENT_METHOD = "我的錢包"


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def build_wallet_payment_adjustment_plan(
    *,
    old_amount: int,
    new_amount: int,
    old_payment_method: str | None,
    new_payment_method: str | None,
    old_customer_id: str | int | None,
    new_customer_id: str | int | None,
) -> dict[str, Any] | None:
    """Return the single wallet delta needed to match the edited order.

    Positive amount refunds the wallet. Negative amount charges the wallet.
    The caller is responsible for idempotent persistence of the returned delta.
    """
    old_amount = max(0, int(old_amount or 0))
    new_amount = max(0, int(new_amount or 0))

    old_method = _normalize(old_payment_method)
    new_method = _normalize(new_payment_method)
    old_customer = _normalize(old_customer_id)
    new_customer = _normalize(new_customer_id)

    was_wallet = old_method == WALLET_PAYMENT_METHOD
    is_wallet = new_method == WALLET_PAYMENT_METHOD

    if not was_wallet and not is_wallet:
        return None

    if was_wallet and is_wallet:
        if not old_customer or not new_customer:
            raise ValueError(
                "錢包訂單缺少修改前或修改後的顧客 Discord ID。"
            )

        if old_customer != new_customer:
            raise ValueError(
                "錢包付款訂單同時更換顧客，禁止自動搬移錢包款項；請人工確認。"
            )

        delta = old_amount - new_amount
        customer_id = new_customer
        mode = "wallet_to_wallet"

    elif was_wallet:
        if not old_customer:
            raise ValueError(
                "原錢包付款訂單缺少顧客 Discord ID，無法自動退款。"
            )

        delta = old_amount
        customer_id = old_customer
        mode = "wallet_to_non_wallet"

    else:
        if not new_customer:
            raise ValueError(
                "新錢包付款訂單缺少顧客 Discord ID，無法自動扣款。"
            )

        delta = -new_amount
        customer_id = new_customer
        mode = "non_wallet_to_wallet"

    if delta == 0:
        return None

    return {
        "customer_id": customer_id,
        "amount": int(delta),
        "mode": mode,
        "old_amount": old_amount,
        "new_amount": new_amount,
        "old_payment_method": old_method,
        "new_payment_method": new_method,
    }
