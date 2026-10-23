from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import json

from sqlalchemy import text


_INSTALLED = False
VIP_TIMER_MINIMUM_SECONDS = 15 * 60


def calculate_total_with_minimum(order_id: int, db=None) -> tuple[int, int]:
    """Return final amount with a whole-order 15 minute minimum.

    Once actual billable time reaches 15 minutes, billing remains exact by
    second. For a shorter mixed-rate order, scale the actual mixed-rate amount
    proportionally to 15 minutes so no single segment is arbitrarily favored.
    """
    from services import vip_timer as timer

    owns = db is None
    if owns:
        db = timer.SessionLocal()
    try:
        rows = db.execute(
            text(
                "SELECT hourly_rate, billable_seconds "
                "FROM vip_timer_segments WHERE order_id=:order_id"
            ),
            {"order_id": int(order_id)},
        ).mappings().all()

        total_seconds = sum(
            max(0, int(row.get("billable_seconds") or 0))
            for row in rows
        )
        amount = sum(
            Decimal(int(row.get("hourly_rate") or 0))
            * Decimal(max(0, int(row.get("billable_seconds") or 0)))
            / Decimal(3600)
            for row in rows
        )

        if 0 < total_seconds < VIP_TIMER_MINIMUM_SECONDS:
            amount *= Decimal(VIP_TIMER_MINIMUM_SECONDS) / Decimal(total_seconds)

        rounded = int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return rounded, total_seconds
    finally:
        if owns:
            db.close()


def _vip_level_and_rate(order_id: int) -> tuple[str, int]:
    """Resolve the canonical VIP snapshot locked when this timer order opened."""
    from services.vip_timer_ops import get_vip_snapshot

    vip_name, pay_rate = get_vip_snapshot(int(order_id))
    return str(vip_name or "普通魔丸"), max(0, min(100, int(pay_rate or 100)))


def _discount_amount(amount: int, pay_rate: int) -> int:
    value = (
        Decimal(max(0, int(amount or 0)))
        * Decimal(max(0, min(100, int(pay_rate or 100))))
        / Decimal(100)
    )
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _apply_vip_discount_to_result(order_id: int, result: dict) -> dict:
    """Apply only the locked VIP percentage discount to a finished timer.

    VIP percentage discounts use the same shared funding policy as ordinary
    orders: customer payment and payout base are reduced together. Monthly
    vouchers, points, loyalty coupons and manual discounts are intentionally not
    part of this settlement path.
    """
    from services import vip_timer as timer

    original_amount = max(0, int(result.get("final_amount") or 0))
    vip_name, pay_rate = _vip_level_and_rate(int(order_id))
    customer_pay = _discount_amount(original_amount, pay_rate)
    discount_amount = max(0, original_amount - customer_pay)

    db = timer.SessionLocal()
    try:
        row = db.execute(
            text(
                "SELECT price_snapshot_json FROM web_orders "
                "WHERE id=:order_id LIMIT 1"
            ),
            {"order_id": int(order_id)},
        ).mappings().first()
        try:
            snapshot = json.loads(str((row or {}).get("price_snapshot_json") or "{}"))
        except Exception:
            snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {}

        snapshot.update(
            {
                "vip_timer": True,
                "original_amount": original_amount,
                "final_amount": customer_pay,
                "customer_pay_amount": customer_pay,
                "payout_base_amount": customer_pay,
                "vip_name": vip_name,
                "vip_discount_pay_rate": pay_rate,
                "vip_discount_amount": discount_amount,
                "discount_source": "vip_percent" if pay_rate < 100 else None,
                "excluded_benefits": [
                    "vip_monthly_voucher",
                    "point_benefit",
                    "loyalty_coupon",
                    "entertainment_loyalty_progress",
                    "manual_discount",
                    "other_promotions",
                ],
            }
        )
        snapshot_text = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)

        db.execute(
            text(
                "UPDATE vip_timer_sessions SET final_amount=:customer_pay, updated_at=:now "
                "WHERE order_id=:order_id"
            ),
            {
                "customer_pay": customer_pay,
                "now": timer.utc_iso(),
                "order_id": int(order_id),
            },
        )
        db.execute(
            text(
                "UPDATE web_orders SET amount=:customer_pay, original_amount=:original_amount, "
                "payout_base_amount=:customer_pay, customer_pay_amount=:customer_pay, "
                "price_snapshot_json=:snapshot, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=:order_id"
            ),
            {
                "customer_pay": customer_pay,
                "original_amount": original_amount,
                "snapshot": snapshot_text,
                "order_id": int(order_id),
            },
        )
        db.execute(
            text(
                "UPDATE order_acceptance_meta SET price_snapshot_json=:snapshot, "
                "updated_at=CURRENT_TIMESTAMP WHERE order_id=:order_id"
            ),
            {"snapshot": snapshot_text, "order_id": int(order_id)},
        )
        timer._event(
            db,
            int(order_id),
            "vip_discount_applied",
            None,
            {
                "vip_name": vip_name,
                "pay_rate": pay_rate,
                "original_amount": original_amount,
                "customer_pay_amount": customer_pay,
                "discount_amount": discount_amount,
            },
        )
        db.commit()
    finally:
        db.close()

    updated = dict(result)
    updated.update(
        {
            "original_amount": original_amount,
            "final_amount": customer_pay,
            "amount": customer_pay,
            "customer_pay_amount": customer_pay,
            "payout_base_amount": customer_pay,
            "vip_name": vip_name,
            "vip_discount_pay_rate": pay_rate,
            "vip_discount_amount": discount_amount,
        }
    )
    return updated


def install_vip_timer_billing_guard() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer as timer
    from services import vip_timer_runtime as runtime

    timer.calculate_total = calculate_total_with_minimum
    timer.VIP_TIMER_MINIMUM_SECONDS = VIP_TIMER_MINIMUM_SECONDS

    original_end_timer = timer.end_timer

    def end_timer(order_id: int, actor_id):
        # Read the order-opening snapshot before closing. A later VIP upgrade or
        # downgrade must never change this order's percentage.
        _vip_level_and_rate(int(order_id))
        result = original_end_timer(int(order_id), actor_id)
        return _apply_vip_discount_to_result(int(order_id), result)

    timer.end_timer = end_timer
    runtime.end_timer = end_timer

    original_build_embed = runtime.build_vip_timer_embed

    def build_vip_timer_embed(order_id: int):
        embed = original_build_embed(int(order_id))
        embed.add_field(
            name="最低計費",
            value="整張單最低計費 15 分鐘；超過後依實際計時秒數換算。",
            inline=False,
        )
        embed.add_field(
            name="VIP 優惠",
            value=(
                "依開單當下的 VIP 等級鎖定百分比折扣；之後升級或降級不回溯本單。\n"
                "不適用月券、點數福利、跨單累積福利券、娛樂陪累積送時數與其他活動／折扣。"
            ),
            inline=False,
        )
        return embed

    runtime.build_vip_timer_embed = build_vip_timer_embed

    original_finish = runtime._finish_to_payment

    async def finish_to_payment(interaction, order_id: int, result: dict) -> None:
        await original_finish(interaction, int(order_id), result)
        try:
            from core.database import remember_order_data, save_bot_data
            from services.acceptance import dispatch_refresh as dispatch_module
            from services.vip_timer_self_service import (
                _CLEAR_BENEFIT_KEYS,
                _TIMER_DRAFT_CLEAR_KEYS,
            )

            channel = interaction.channel
            channel_id = int(getattr(channel, "id", 0) or 0)
            if channel_id <= 0:
                return
            data = dispatch_module.SELF_SERVICE_ORDER_SELECTIONS.setdefault(channel_id, {})
            for key in _TIMER_DRAFT_CLEAR_KEYS:
                data.pop(key, None)
            for key in _CLEAR_BENEFIT_KEYS:
                data.pop(key, None)

            original_amount = max(0, int(result.get("original_amount") or result.get("final_amount") or 0))
            customer_pay = max(0, int(result.get("final_amount") or 0))
            pay_rate = max(0, min(100, int(result.get("vip_discount_pay_rate") or 100)))
            data.update(
                {
                    "vip_timer_order": True,
                    "vip_timer_pending_payment": True,
                    "original_amount": original_amount,
                    "service_original_amount": original_amount,
                    "rule_original_amount": original_amount,
                    "priced_amount": original_amount,
                    "amount": customer_pay,
                    "total_amount": customer_pay,
                    "customer_pay_amount": customer_pay,
                    "payout_base_amount": customer_pay,
                    "amount_text": runtime._format_plain_amount(customer_pay),
                    "vip_name": result.get("vip_name"),
                    "vip_discount_rate_percent": pay_rate,
                    "discount_rate_percent": pay_rate,
                    "vip_discount_amount": max(0, original_amount - customer_pay),
                    "percent_discount_amount": max(0, original_amount - customer_pay),
                    "manual_discount_percent": 100,
                    "manual_discount_reason": None,
                    "cash_coupon_amount": 0,
                    "fixed_discount_amount": 0,
                    "point_discount_coupon_amount": 0,
                    "vip_monthly_cash_amount": 0,
                    "benefit_discount_amount": 0,
                    "store_absorbed_amount": 0,
                    "payment_method": None,
                }
            )
            remember_order_data(channel_id, data)
            save_bot_data()
        except Exception as exc:
            print(
                f"[vip-timer] benefit policy persistence failed order_id={order_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    runtime._finish_to_payment = finish_to_payment
    _INSTALLED = True


__all__ = [
    "VIP_TIMER_MINIMUM_SECONDS",
    "calculate_total_with_minimum",
    "install_vip_timer_billing_guard",
]
