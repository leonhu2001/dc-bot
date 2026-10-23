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


def _ensure_vip_snapshot_table(db) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS vip_timer_vip_snapshots (
                order_id INTEGER PRIMARY KEY,
                customer_discord_id TEXT NOT NULL,
                vip_name TEXT NOT NULL,
                vip_discount_pay_rate INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
    )


def _current_vip_level_and_rate(customer_id: str) -> tuple[str, int]:
    from core.vip_levels import get_vip_discount_pay_rate
    from services.rewards import get_customer_reward_data, get_effective_member_level

    try:
        reward_data = get_customer_reward_data(int(customer_id))
        level = get_effective_member_level(reward_data) or {}
    except Exception as exc:
        raise ValueError("暫時無法確認目前 VIP 等級，請稍後再建立自由計時單。") from exc

    vip_name = str(level.get("name") or "普通魔丸")
    pay_rate = int(get_vip_discount_pay_rate(vip_name))
    return vip_name, max(0, min(100, pay_rate))


def _ensure_vip_discount_snapshot(
    order_id: int,
    customer_id: str,
    *,
    db=None,
    legacy: bool = False,
) -> tuple[str, int]:
    """Persist and return the order-opening VIP percentage exactly once."""
    from services import vip_timer as timer

    owns = db is None
    if owns:
        db = timer.SessionLocal()
    try:
        _ensure_vip_snapshot_table(db)
        existing = db.execute(
            text(
                "SELECT vip_name, vip_discount_pay_rate FROM vip_timer_vip_snapshots "
                "WHERE order_id=:order_id LIMIT 1"
            ),
            {"order_id": int(order_id)},
        ).mappings().first()
        if existing is not None:
            return (
                str(existing.get("vip_name") or "普通魔丸"),
                max(0, min(100, int(existing.get("vip_discount_pay_rate") or 100))),
            )

        vip_name, pay_rate = _current_vip_level_and_rate(str(customer_id))
        created_at = timer.utc_iso()
        db.execute(
            text(
                "INSERT INTO vip_timer_vip_snapshots("
                "order_id, customer_discord_id, vip_name, vip_discount_pay_rate, created_at"
                ") VALUES ("
                ":order_id, :customer_id, :vip_name, :pay_rate, :created_at"
                ")"
            ),
            {
                "order_id": int(order_id),
                "customer_id": str(customer_id),
                "vip_name": vip_name,
                "pay_rate": int(pay_rate),
                "created_at": created_at,
            },
        )

        row = db.execute(
            text(
                "SELECT price_snapshot_json FROM web_orders "
                "WHERE id=:order_id LIMIT 1"
            ),
            {"order_id": int(order_id)},
        ).mappings().first()
        if row is not None:
            try:
                snapshot = json.loads(str(row.get("price_snapshot_json") or "{}"))
            except Exception:
                snapshot = {}
            if not isinstance(snapshot, dict):
                snapshot = {}
            snapshot.update(
                {
                    "vip_timer": True,
                    "vip_name": vip_name,
                    "vip_discount_pay_rate": int(pay_rate),
                    "vip_discount_locked_at": created_at,
                    "vip_discount_locked_on_create": not legacy,
                }
            )
            db.execute(
                text(
                    "UPDATE web_orders SET price_snapshot_json=:snapshot, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=:order_id"
                ),
                {
                    "snapshot": json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    "order_id": int(order_id),
                },
            )

        timer._event(
            db,
            int(order_id),
            "vip_discount_snapshot_locked" if not legacy else "vip_discount_snapshot_legacy_locked",
            None,
            {
                "vip_name": vip_name,
                "pay_rate": int(pay_rate),
                "locked_at": created_at,
            },
        )
        if owns:
            db.commit()
        return vip_name, int(pay_rate)
    except Exception:
        if owns:
            db.rollback()
        raise
    finally:
        if owns:
            db.close()


def _vip_level_and_rate(order_id: int) -> tuple[str, int]:
    """Return the order-opening VIP snapshot, never the customer's later level."""
    from services import vip_timer as timer

    session = timer.get_session(int(order_id)) or {}
    customer_id = str(session.get("customer_discord_id") or "").strip()
    if not customer_id:
        raise ValueError("找不到 VIP 自由計時單的會員資料，暫時無法結算。")

    db = timer.SessionLocal()
    try:
        _ensure_vip_snapshot_table(db)
        row = db.execute(
            text(
                "SELECT vip_name, vip_discount_pay_rate FROM vip_timer_vip_snapshots "
                "WHERE order_id=:order_id LIMIT 1"
            ),
            {"order_id": int(order_id)},
        ).mappings().first()
        if row is not None:
            return (
                str(row.get("vip_name") or "普通魔丸"),
                max(0, min(100, int(row.get("vip_discount_pay_rate") or 100))),
            )

        # Compatibility for a timer order that was already open before this
        # deployment. It cannot reconstruct the historical opening tier, so lock
        # the first post-deploy observation once and never re-read it afterward.
        result = _ensure_vip_discount_snapshot(
            int(order_id),
            customer_id,
            db=db,
            legacy=True,
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


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
    from services import vip_timer_self_service as self_service

    timer.calculate_total = calculate_total_with_minimum
    timer.VIP_TIMER_MINIMUM_SECONDS = VIP_TIMER_MINIMUM_SECONDS

    original_create_vip_timer_session = timer.create_vip_timer_session

    def create_vip_timer_session(db, *, order_id: int, customer_id: str, initial_rule_key: str):
        result = original_create_vip_timer_session(
            db,
            order_id=int(order_id),
            customer_id=str(customer_id),
            initial_rule_key=str(initial_rule_key),
        )
        _ensure_vip_discount_snapshot(
            int(order_id),
            str(customer_id),
            db=db,
            legacy=False,
        )
        return result

    timer.create_vip_timer_session = create_vip_timer_session
    # vip_timer_self_service imports this function directly at module import time,
    # so update that bound reference as well as the canonical timer module.
    self_service.create_vip_timer_session = create_vip_timer_session

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
