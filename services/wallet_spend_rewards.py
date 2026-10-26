from __future__ import annotations

from typing import Any

from services import rewards


_PATCH_INSTALLED_ATTR = "_wallet_spend_rewards_patch_installed"
_RUNTIME_PATCH_INSTALLED_ATTR = "_wallet_spend_rewards_runtime_patch_installed"


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _order_amount(order_data: dict[str, Any], amount_text: str | None = None) -> int:
    for key in ("wallet_paid_amount", "amount", "total_amount"):
        value = order_data.get(key)
        if value in (None, ""):
            continue
        parsed = rewards.parse_receipt_amount(str(value))
        if parsed is not None:
            return max(0, int(parsed))

    parsed = rewards.parse_receipt_amount(str(amount_text or order_data.get("amount_text") or ""))
    return max(0, int(parsed or 0))


def _is_wallet_point_excluded(order_data: dict[str, Any]) -> bool:
    item = str(order_data.get("item") or "").strip()
    return item in rewards.NO_VIP_REWARD_ITEMS or item in rewards.VIP_PROGRESS_EXCLUDED_ITEMS


def _award_wallet_spend_points(data: dict[str, Any], amount: int) -> int:
    """Award usable points from actual wallet spend without touching VIP spend.

    Wallet spend has its own cumulative bucket so sub-100T orders carry forward:
    50T + 50T => 1 point.  Points are written through point_adjustment because
    total_spent is reserved for VIP progress and already includes top-up principal.
    """

    amount = max(0, int(amount or 0))
    before_total = max(0, _as_int(data.get("wallet_point_spend_total"), 0))
    after_total = before_total + amount
    before_points = rewards.calculate_reward_points(before_total)
    after_points = rewards.calculate_reward_points(after_total)
    earned = max(0, int(after_points - before_points))

    data["wallet_point_spend_total"] = after_total
    if earned:
        data["point_adjustment"] = _as_int(data.get("point_adjustment"), 0) + earned
    data["points"] = rewards.get_current_reward_points(data)
    return earned


def _mark_wallet_order(
    order_data: dict[str, Any],
    *,
    amount: int,
    earned: int,
    counted_at: str | None = None,
    excluded: bool = False,
) -> None:
    order_data["reward_counted"] = True
    # Wallet payment never adds VIP cumulative spend a second time.
    order_data["reward_amount"] = 0
    order_data["reward_excluded"] = True
    if excluded:
        order_data["reward_excluded_reason"] = "此項目不累積 VIP／錢包消費點數"
    else:
        order_data["reward_excluded_reason"] = (
            "錢包付款：儲值本金已累積 VIP；本次實際消費僅累積可用點數"
        )
    order_data["wallet_points_counted"] = True
    order_data["wallet_point_amount"] = max(0, int(amount or 0))
    order_data["wallet_points_awarded"] = max(0, int(earned or 0))
    order_data["wallet_points_counted_at"] = counted_at or rewards.get_taipei_now_iso()
    order_data.setdefault("reward_counted_at", counted_at or rewards.get_taipei_now_iso())


async def _wallet_aware_add_customer_reward_from_order(
    guild,
    order_channel_id: int,
    customer_id: int,
    amount_text: str,
    notify_channel=None,
) -> str:
    order_data = rewards._ORDER_SELECTIONS.get(order_channel_id, {})
    payment_method = str(order_data.get("payment_method") or "").strip()

    if payment_method != rewards.WALLET_PAYMENT_METHOD:
        return await _ORIGINAL_ADD_REWARD(
            guild=guild,
            order_channel_id=order_channel_id,
            customer_id=customer_id,
            amount_text=amount_text,
            notify_channel=notify_channel,
        )

    if order_data.get("wallet_points_counted"):
        return "此錢包訂單已累積過消費點數，未重複累積。"

    if order_data.get("reward_counted"):
        # Old wallet orders are handled by the startup backfill.  If one reaches
        # here after boot, keep runtime idempotent instead of awarding twice.
        return "此訂單已累積過會員紀錄，未重複累積。"

    data = rewards.get_customer_reward_data(int(customer_id))
    data["order_count"] = _as_int(data.get("order_count"), 0) + 1
    data["last_order_at"] = rewards.get_taipei_now_iso()

    amount = _order_amount(order_data, amount_text)
    excluded = _is_wallet_point_excluded(order_data)
    earned = 0 if excluded else _award_wallet_spend_points(data, amount)
    if excluded:
        data["points"] = rewards.get_current_reward_points(data)

    _mark_wallet_order(
        order_data,
        amount=0 if excluded else amount,
        earned=earned,
        excluded=excluded,
    )
    rewards._ORDER_SELECTIONS[order_channel_id] = order_data

    if rewards._SAVE_BOT_DATA is not None:
        rewards._SAVE_BOT_DATA()

    if excluded:
        return "會員紀錄已更新：完成訂單 +1；此項目不累積 VIP／錢包消費點數。"

    remainder = max(0, _as_int(data.get("wallet_point_spend_total"), 0)) % max(
        1, _as_int(getattr(rewards, "_REWARD_POINT_DIVISOR", 100), 100)
    )
    return (
        f"會員紀錄已更新：完成訂單 +1；錢包實際消費 {amount:,}T，"
        f"本次增加 {earned:,} 點，目前可用 {rewards.get_current_reward_points(data):,} 點。"
        f"（錢包消費累積尾數 {remainder}T）"
    )


def backfill_historical_wallet_spend_points() -> dict[str, int]:
    """Backfill only legacy wallet orders explicitly excluded by the old rule.

    Per-order wallet_points_counted makes the migration safe to run every boot.
    It never increments order_count and never changes VIP total_spent.
    """

    candidates: list[tuple[str, int, dict[str, Any]]] = []
    for channel_id, order_data in list(rewards._ORDER_SELECTIONS.items()):
        if not isinstance(order_data, dict):
            continue
        if str(order_data.get("payment_method") or "").strip() != rewards.WALLET_PAYMENT_METHOD:
            continue
        if bool(order_data.get("wallet_points_counted")):
            continue
        if not bool(order_data.get("reward_counted")):
            continue
        old_reason = str(order_data.get("reward_excluded_reason") or "")
        if "錢包付款" not in old_reason:
            continue

        sort_key = str(
            order_data.get("reward_counted_at")
            or order_data.get("payment_submitted_at")
            or order_data.get("created_at")
            or ""
        )
        candidates.append((sort_key, _as_int(channel_id, 0), order_data))

    candidates.sort(key=lambda row: (row[0], row[1]))

    scanned = len(candidates)
    updated = 0
    awarded = 0
    skipped_missing_customer = 0
    excluded_orders = 0

    for _sort_key, channel_id, order_data in candidates:
        customer_id = _as_int(order_data.get("customer_id"), 0)
        if customer_id <= 0:
            skipped_missing_customer += 1
            continue

        excluded = _is_wallet_point_excluded(order_data)
        amount = 0 if excluded else _order_amount(order_data)
        data = rewards.get_customer_reward_data(customer_id)
        earned = 0 if excluded else _award_wallet_spend_points(data, amount)
        if excluded:
            data["points"] = rewards.get_current_reward_points(data)
            excluded_orders += 1

        _mark_wallet_order(
            order_data,
            amount=amount,
            earned=earned,
            counted_at=rewards.get_taipei_now_iso(),
            excluded=excluded,
        )
        rewards._ORDER_SELECTIONS[channel_id] = order_data
        updated += 1
        awarded += earned

    if updated and rewards._SAVE_BOT_DATA is not None:
        rewards._SAVE_BOT_DATA()

    summary = {
        "scanned": scanned,
        "updated": updated,
        "awarded": awarded,
        "excluded": excluded_orders,
        "missing_customer": skipped_missing_customer,
    }
    if scanned:
        print(
            "[wallet-points] historical backfill "
            f"scanned={scanned} updated={updated} awarded={awarded} "
            f"excluded={excluded_orders} missing_customer={skipped_missing_customer}",
            flush=True,
        )
    return summary


def install_wallet_spend_rewards() -> dict[str, int]:
    """Install wallet-spend point rules into rewards and payment runtime."""

    global _ORIGINAL_ADD_REWARD

    already_installed = bool(getattr(rewards, _PATCH_INSTALLED_ATTR, False))
    if not already_installed:
        _ORIGINAL_ADD_REWARD = rewards.add_customer_reward_from_order
        rewards.add_customer_reward_from_order = _wallet_aware_add_customer_reward_from_order
        setattr(rewards, _PATCH_INSTALLED_ATTR, True)
    else:
        original = getattr(rewards, "_wallet_spend_rewards_original", None)
        if callable(original):
            _ORIGINAL_ADD_REWARD = original

    if not hasattr(rewards, "_wallet_spend_rewards_original"):
        setattr(rewards, "_wallet_spend_rewards_original", _ORIGINAL_ADD_REWARD)

    try:
        from services import order_payment_runtime

        # If runtime is already configured, replace the bound callable now.
        if getattr(order_payment_runtime, "_CONFIGURED", False):
            order_payment_runtime.add_customer_reward_from_order = _wallet_aware_add_customer_reward_from_order

        # Also guard a later configure call during startup.
        if not bool(getattr(order_payment_runtime, _RUNTIME_PATCH_INSTALLED_ATTR, False)):
            original_configure = order_payment_runtime.configure_order_payment_runtime

            def configure_with_wallet_points(*args, **kwargs):
                if "customer_reward_adder" in kwargs:
                    kwargs["customer_reward_adder"] = _wallet_aware_add_customer_reward_from_order
                result = original_configure(*args, **kwargs)
                order_payment_runtime.add_customer_reward_from_order = _wallet_aware_add_customer_reward_from_order
                return result

            order_payment_runtime.configure_order_payment_runtime = configure_with_wallet_points
            setattr(order_payment_runtime, _RUNTIME_PATCH_INSTALLED_ATTR, True)
    except Exception as exc:
        print(f"[wallet-points] runtime patch warning: {exc}", flush=True)

    return backfill_historical_wallet_spend_points()


# Set at install time so the wrapper can always delegate non-wallet orders to
# the exact pre-patch implementation.
_ORIGINAL_ADD_REWARD = rewards.add_customer_reward_from_order
