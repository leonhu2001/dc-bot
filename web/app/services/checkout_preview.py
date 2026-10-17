from __future__ import annotations

"""Checkout facade with unified coupon / benefit handling.

The pre-existing catalog, VIP, staff and point helpers are preserved in
``checkout_preview_legacy``.  This file owns only the financial/benefit layer so
Web and the persisted payout base agree on the 2026-10-17 policy:

* point cash and VIP monthly cash discounts are shared discounts;
* store-funded promo/compensation coupons never reduce worker/CS entitlement;
* loyalty and service gifts keep their existing store-funded semantics;
* all selectable benefits share the existing single "我的福利" selector.
"""

from typing import Any

from services import issued_benefits as issued_service
from services.benefit_selector import (
    SOURCE_ISSUED,
    SOURCE_LOYALTY,
    SOURCE_VIP_MONTHLY,
    decode_benefit_selector_id,
    encode_issued_benefit_id,
    encode_vip_monthly_benefit_id,
)
from services.order_discounts import FUNDING_SHARED, FUNDING_STORE
from services.vip_monthly_benefits import (
    get_available_cash_benefit,
    list_available_cash_benefits,
)
from services.vip_monthly_order_discount import (
    get_vip_monthly_cash_minimum_order_amount,
)
from web.app.services import checkout_preview_legacy as _legacy
from web.app.services.checkout_preview_legacy import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Benefit option adapters
# ---------------------------------------------------------------------------

def _issued_scope_matches(benefit: dict[str, Any], *, rule_key: str) -> bool:
    rule = _legacy.ORDER_RULES.get(str(rule_key))
    if rule is None:
        return False
    rules = dict(benefit.get("rules") or {})
    allowed_rules = set(rules.get("rule_keys") or [])
    allowed_categories = set(rules.get("categories") or [])
    excluded_rules = set(rules.get("excluded_rule_keys") or [])
    excluded_categories = set(rules.get("excluded_categories") or [])
    category = str(rule.category)
    if allowed_rules and str(rule_key) not in allowed_rules:
        return False
    if allowed_categories and category not in allowed_categories:
        return False
    if str(rule_key) in excluded_rules or category in excluded_categories:
        return False

    effect = str(rules.get("effect_type") or "fixed_cash")
    pricing_type = str(rule.pricing_type)
    if effect == issued_service.EFFECT_SERVICE_HOURS and pricing_type != "hourly":
        return False
    if effect == issued_service.EFFECT_SERVICE_GAMES and pricing_type != "game":
        return False
    if effect == issued_service.EFFECT_WAIVE_FEE and not bool(rule.allow_specify):
        return False
    return True


def _issued_option(benefit: dict[str, Any]) -> dict[str, Any]:
    rules = dict(benefit.get("rules") or {})
    summary = issued_service.describe_rules(rules)
    title = str(benefit.get("title") or "會員福利")
    minimum = int(rules.get("minimum_order_amount") or 0)
    suffix = f"｜滿 {minimum:,}T 可用" if minimum > 0 else ""
    return {
        "id": encode_issued_benefit_id(int(benefit["id"])),
        "title": f"{title}｜{summary}{suffix}",
        "benefit_kind": str(rules.get("effect_type") or "fixed_cash"),
        "benefit_units": float(
            rules.get("service_hours")
            or rules.get("service_games")
            or rules.get("amount")
            or 0
        ),
        "source": SOURCE_ISSUED,
        "issued_benefit_id": int(benefit["id"]),
    }


def _vip_monthly_option(item: dict[str, Any]) -> dict[str, Any]:
    real_id = int(item["id"])
    amount = int(item.get("amount") or 0)
    benefit_key = str(item.get("benefit_key") or "")
    minimum = get_vip_monthly_cash_minimum_order_amount(benefit_key)
    return {
        "id": encode_vip_monthly_benefit_id(real_id),
        "title": (
            f"{str(item.get('title') or 'VIP 每月折現券')}"
            + (f"｜單筆滿 {minimum:,}T" if minimum > 0 else "")
        ),
        "benefit_kind": "fixed_cash",
        "benefit_units": float(amount),
        "source": SOURCE_VIP_MONTHLY,
        "vip_monthly_benefit_id": real_id,
        "benefit_key": benefit_key,
    }


def build_checkout_options(
    *,
    customer_id: str,
    rule_key: str,
    quantity: int = 1,
    player_count: int = 1,
    customer_adjustments: Any = None,
    preselected_staff_id: str | None = None,
) -> dict:
    data = _legacy.build_checkout_options(
        customer_id=customer_id,
        rule_key=rule_key,
        quantity=quantity,
        player_count=player_count,
        customer_adjustments=customer_adjustments,
        preselected_staff_id=preselected_staff_id,
    )

    combined = list(data.get("benefit_coupons") or [])

    try:
        for item in list_available_cash_benefits(customer_id):
            combined.append(_vip_monthly_option(item))
    except Exception:
        # A benefit-list failure must not make the order catalog unusable.
        pass

    try:
        for benefit in issued_service.list_available_benefits_for_customer(customer_id):
            if _issued_scope_matches(benefit, rule_key=rule_key):
                combined.append(_issued_option(benefit))
    except Exception:
        pass

    data["benefit_coupons"] = combined
    return data


# ---------------------------------------------------------------------------
# Financial helpers
# ---------------------------------------------------------------------------

def _service_unit_cash_value(
    *,
    service_after_vip: int,
    quote: dict[str, Any],
    units: float,
    service_scope: str,
) -> int:
    if units <= 0:
        return 0
    quantity = max(1.0, float(quote.get("quantity") or 1))
    staff_count = max(1, int(quote.get("required_staff_count") or 1))
    per_order_unit = max(0.0, float(service_after_vip)) / quantity
    if str(service_scope or "one_seat") == "whole_order":
        return max(0, int(round(per_order_unit * units)))
    return max(0, int(round((per_order_unit / staff_count) * units)))


def _generic_benefit_descriptor(
    *,
    benefit: dict[str, Any],
    customer_id: str,
    rule_key: str,
    quote: dict[str, Any],
    service_after_vip: int,
    specify_fee: int,
) -> dict[str, Any]:
    if str(benefit.get("customer_id") or "") != str(customer_id):
        raise ValueError("這張福利券不屬於目前會員。")
    if str(benefit.get("status") or "") != issued_service.STATUS_AVAILABLE:
        raise ValueError("這張福利券已使用、已保留或已失效。")
    if not _issued_scope_matches(benefit, rule_key=rule_key):
        raise ValueError("這張福利券不適用這個方案。")

    rules = issued_service.normalize_rules(benefit.get("rules") or {})
    original_service = max(0, int(quote.get("customer_pay_amount") or 0))
    minimum = max(0, int(rules.get("minimum_order_amount") or 0))
    if original_service < minimum:
        raise ValueError(f"這張福利券需單筆原始服務金額滿 {minimum:,}T 才能使用。")

    effect = str(rules.get("effect_type") or issued_service.EFFECT_FIXED_CASH)
    funding = str(rules.get("funding") or FUNDING_STORE)
    include_specify = bool(rules.get("include_specify_fee"))
    service_discount = 0
    specify_discount = 0
    note = str(benefit.get("title") or "會員福利")

    if effect == issued_service.EFFECT_FIXED_CASH:
        amount = max(0, int(rules.get("amount") or 0))
        service_discount = min(service_after_vip, amount)
        remainder = max(0, amount - service_discount)
        if include_specify:
            specify_discount = min(specify_fee, remainder)
    elif effect == issued_service.EFFECT_PERCENT:
        percent = max(0.0, min(100.0, float(rules.get("percent_off") or 0)))
        service_discount = int(round(service_after_vip * percent / 100))
        if include_specify:
            specify_discount = int(round(specify_fee * percent / 100))
    elif effect == issued_service.EFFECT_FULL_ORDER:
        service_discount = service_after_vip
        specify_discount = specify_fee if include_specify else 0
    elif effect == issued_service.EFFECT_WAIVE_FEE:
        specify_discount = specify_fee
    elif effect in {issued_service.EFFECT_SERVICE_HOURS, issued_service.EFFECT_SERVICE_GAMES}:
        units = float(
            rules.get("service_hours")
            if effect == issued_service.EFFECT_SERVICE_HOURS
            else rules.get("service_games")
            or 0
        )
        service_discount = _service_unit_cash_value(
            service_after_vip=service_after_vip,
            quote=quote,
            units=units,
            service_scope=str(rules.get("service_scope") or "one_seat"),
        )

    maximum = max(0, int(rules.get("maximum_discount_amount") or 0))
    total = service_discount + specify_discount
    if maximum > 0 and total > maximum:
        overflow = total - maximum
        # Preserve specify waiver first for explicit fee-waiver benefits;
        # otherwise reduce the specify portion before the service discount.
        if effect == issued_service.EFFECT_WAIVE_FEE:
            specify_discount = max(0, specify_discount - overflow)
        else:
            reduce_specify = min(specify_discount, overflow)
            specify_discount -= reduce_specify
            overflow -= reduce_specify
            service_discount = max(0, service_discount - overflow)

    return {
        "selector_id": encode_issued_benefit_id(int(benefit["id"])),
        "real_id": int(benefit["id"]),
        "title": str(benefit.get("title") or "會員福利"),
        "source": SOURCE_ISSUED,
        "funding": funding,
        "service_discount": max(0, int(service_discount)),
        "specify_discount": max(0, int(specify_discount)),
        "note": note,
        "benefit_kind": effect,
        "benefit_units": float(
            rules.get("service_hours")
            or rules.get("service_games")
            or rules.get("amount")
            or 0
        ),
        "rules": rules,
    }


def _vip_monthly_descriptor(
    *,
    benefit: dict[str, Any],
    quote: dict[str, Any],
    service_after_vip: int,
) -> dict[str, Any]:
    benefit_key = str(benefit.get("benefit_key") or "")
    minimum = get_vip_monthly_cash_minimum_order_amount(benefit_key)
    original_service = max(0, int(quote.get("customer_pay_amount") or 0))
    if original_service < minimum:
        raise ValueError(
            f"{int(benefit.get('amount') or 0)}T VIP 月券需單筆原始服務金額滿 {minimum:,}T 才能使用。"
        )
    amount = min(service_after_vip, max(0, int(benefit.get("amount") or 0)))
    return {
        "selector_id": encode_vip_monthly_benefit_id(int(benefit["id"])),
        "real_id": int(benefit["id"]),
        "title": str(benefit.get("title") or "VIP 每月折現券"),
        "source": SOURCE_VIP_MONTHLY,
        "funding": FUNDING_SHARED,
        "service_discount": amount,
        "specify_discount": 0,
        "note": f"{str(benefit.get('title') or 'VIP 每月折現券')} -{amount:,}T",
        "benefit_kind": "fixed_cash",
        "benefit_units": float(amount),
        "benefit_key": benefit_key,
    }


def _loyalty_descriptor(
    *,
    coupon: dict[str, Any],
    rule_key: str,
    player_count: int,
    service_after_vip: int,
) -> dict[str, Any]:
    value = _legacy.calculate_coupon_service_value(
        rule_key=rule_key,
        player_count=player_count,
        coupon=coupon,
    )
    value = min(max(0, int(value)), max(0, int(service_after_vip)))
    return {
        "selector_id": (
            int(coupon.get("id")) if coupon.get("id") not in (None, "") else None
        ),
        "real_id": int(coupon.get("id")) if coupon.get("id") not in (None, "") else None,
        "title": str(coupon.get("title") or "跨單累積福利"),
        "source": str(coupon.get("source") or SOURCE_LOYALTY),
        "funding": FUNDING_STORE,
        "service_discount": value,
        "specify_discount": 0,
        "note": _legacy.coupon_service_note(coupon),
        "benefit_kind": str(coupon.get("benefit_kind") or ""),
        "benefit_units": float(coupon.get("benefit_units") or 0),
        "same_order": bool(coupon.get("same_order")),
        "earned_count": int(coupon.get("earned_count") or 0),
        "scope_key": str(coupon.get("scope_key") or ""),
        "rule_key": str(coupon.get("rule_key") or ""),
        "player_count": int(coupon.get("player_count") or player_count or 1),
        # Existing loyalty benefit policy intentionally excludes the free unit
        # from CS commission base.
        "exclude_from_cs_base": value,
    }


def calculate_checkout_financials(
    *,
    service_amount: int,
    vip_pay_rate: int,
    specify_fee: int,
    point_item: dict | None,
    wallet_balance: int,
    use_wallet: bool,
    point_service_value: int = 0,
    benefit: dict[str, Any] | None = None,
) -> dict:
    service_amount = max(0, int(service_amount or 0))
    vip_pay_rate = max(0, min(100, int(vip_pay_rate or 100)))
    specify_fee = max(0, int(specify_fee or 0))
    wallet_balance = max(0, int(wallet_balance or 0))
    point_service_value = max(0, int(point_service_value or 0))

    after_vip = int(round(service_amount * vip_pay_rate / 100))
    vip_discount_amount = max(0, service_amount - after_vip)

    point_cash_discount = 0
    point_waived_specify = 0
    point_service_note = ""
    if point_item:
        kind = str(point_item.get("kind") or "")
        if kind == "cash_discount":
            point_cash_discount = min(after_vip, max(0, int(point_item.get("amount") or 0)))
        elif kind == "free_specify_fee":
            point_waived_specify = specify_fee
        elif kind == "extra_hours":
            hours = float(point_item.get("hours") or 0)
            point_service_note = (
                "服務時間 +30 分鐘（1 位陪玩）"
                if abs(hours - 0.5) < 0.001
                else f"服務時間 +{hours:g} 小時（1 位陪玩）"
            )
        elif kind == "extra_games":
            games = int(point_item.get("games") or 0)
            point_service_note = f"服務局數 +{games} 局（1 位陪玩）"

    # Cash point coupons are normal shared discounts under the new policy.
    service_after_point = max(0, after_vip - point_cash_discount)

    benefit_service_discount = max(0, int((benefit or {}).get("service_discount") or 0))
    benefit_specify_discount = max(0, int((benefit or {}).get("specify_discount") or 0))
    benefit_funding = str((benefit or {}).get("funding") or FUNDING_STORE)
    benefit_service_discount = min(service_after_point, benefit_service_discount)
    benefit_specify_discount = min(
        max(0, specify_fee - point_waived_specify),
        benefit_specify_discount,
    )

    service_after_benefit = max(0, service_after_point - benefit_service_discount)
    effective_specify_fee = max(
        0,
        specify_fee - point_waived_specify - benefit_specify_discount,
    )
    subtotal = max(0, service_after_benefit + effective_specify_fee)
    wallet_use = min(wallet_balance, subtotal) if use_wallet else 0
    remaining = max(0, subtotal - wallet_use)

    payout_base = after_vip + specify_fee + point_service_value
    payout_base -= point_cash_discount
    if benefit_funding == FUNDING_SHARED:
        payout_base -= benefit_service_discount + benefit_specify_discount
    payout_base = max(0, int(payout_base))

    # Store absorption only contains benefits that truly do not reduce worker/CS
    # entitlement. Shared discounts are represented by the lower payout base.
    point_store_absorbed = max(0, point_waived_specify + point_service_value)
    benefit_store_absorbed = (
        benefit_service_discount + benefit_specify_discount
        if benefit and benefit_funding == FUNDING_STORE
        else 0
    )
    loyalty_cs_exclusion = max(0, int((benefit or {}).get("exclude_from_cs_base") or 0))

    benefit_id = (benefit or {}).get("selector_id")
    return {
        "service_amount": service_amount,
        "original_amount": service_amount,
        "vip_pay_rate": vip_pay_rate,
        "manual_discount_percent": vip_pay_rate,
        "discount_rate_percent": vip_pay_rate,
        "vip_discount_amount": vip_discount_amount,
        "manual_discount_amount": vip_discount_amount,
        "percent_discount_amount": vip_discount_amount,
        "service_after_vip": after_vip,
        "specify_fee": specify_fee,
        "cash_coupon_amount": benefit_service_discount + benefit_specify_discount,
        "fixed_discount_amount": (
            benefit_service_discount + benefit_specify_discount
            if benefit and benefit_funding == FUNDING_SHARED
            else 0
        ),
        "point_cash_discount": point_cash_discount,
        "point_discount_coupon_amount": point_cash_discount,
        "point_waived_specify_fee": point_waived_specify,
        "effective_specify_fee": effective_specify_fee,
        "point_service_note": point_service_note,
        "point_service_value": point_service_value,
        "point_store_absorbed_amount": point_store_absorbed,
        "benefit_coupon_id": int(benefit_id) if benefit_id not in (None, "") else None,
        "benefit_coupon_title": str((benefit or {}).get("title") or ""),
        "benefit_service_note": str((benefit or {}).get("note") or ""),
        # Only legacy loyalty free service is excluded from CS base. Admin promo
        # coupons marked store-funded still pay CS from the normal entitlement.
        "benefit_service_value": loyalty_cs_exclusion,
        "issued_benefit_service_value": (
            benefit_service_discount
            if benefit and str(benefit.get("source") or "") == SOURCE_ISSUED
            else 0
        ),
        "benefit_discount_amount": benefit_service_discount + benefit_specify_discount,
        "benefit_store_absorbed_amount": benefit_store_absorbed,
        "subtotal_before_wallet": subtotal,
        "customer_pay_amount": subtotal,
        "wallet_use_amount": wallet_use,
        "remaining_pay_amount": remaining,
        "payout_base_amount": payout_base,
        "payout_base_preview": payout_base,
        "store_absorbed_amount": point_store_absorbed + benefit_store_absorbed,
        "store_absorbed_preview": point_store_absorbed + benefit_store_absorbed,
    }


# ---------------------------------------------------------------------------
# Verified preview
# ---------------------------------------------------------------------------

def build_checkout_preview(
    *,
    customer_id: str,
    rule_key: str,
    quantity: int = 1,
    player_count: int = 1,
    customer_adjustments: Any = None,
    specified_staff_ids: Any = None,
    point_item_key: str | None = None,
    benefit_coupon_id: int | str | None = None,
    use_wallet: bool = False,
    payment_method: str | None = None,
) -> dict:
    quote = _legacy.build_public_quote(
        rule_key=rule_key,
        quantity=quantity,
        player_count=player_count,
        customer_adjustments=customer_adjustments,
        specified_staff_id=None,
    )
    customer = _legacy.load_customer_state(customer_id)
    rule = _legacy.ORDER_RULES.get(str(rule_key))
    if rule is None:
        raise ValueError("找不到商品規則。")

    selected_staff, role_keys = _legacy.resolve_selected_staff(
        rule_key=rule_key,
        selected_ids=specified_staff_ids,
    )

    specify_fee = 0
    free_specify_by_rule = False
    if role_keys:
        price = _legacy.calculate_price(
            rule,
            quantity=int(quote["quantity"]),
            player_count=(int(quote["player_count"]) if rule.player_count_enabled else None),
            specified_roles=role_keys,
            staff_adjustments=[],
        )
        specify_fee = max(0, int(price.specify_fee))
        free_specify_by_rule = bool(price.free_specify_fee)

    vip = _legacy.vip_discount_policy(
        vip_name=customer["vip_name"],
        rule_key=rule_key,
    )
    vip_rate = int(vip["pay_rate"]) if vip["eligible"] else 100

    source, real_benefit_id = decode_benefit_selector_id(benefit_coupon_id)
    issued_benefit = None
    if benefit_coupon_id not in (None, "") and source == SOURCE_ISSUED:
        issued_benefit = issued_service.get_issued_benefit(int(real_benefit_id or 0))
        if issued_benefit is None:
            raise ValueError("找不到這張福利券。")
        rules = issued_service.normalize_rules(issued_benefit.get("rules") or {})
        if not bool(rules.get("allow_vip_percent", True)):
            vip_rate = 100
            vip = dict(vip)
            vip["eligible"] = False
            vip["pay_rate"] = 100
            vip["reason"] = "此福利券不可與 VIP 百分比折扣併用。"

    selected_point_item = None
    point_item_key = str(point_item_key or "").strip()
    if point_item_key:
        if benefit_coupon_id not in (None, ""):
            raise ValueError("福利券與點數福利同張訂單只能擇一使用。")
        item = _legacy.POINT_ITEM_MAP.get(point_item_key)
        if item is None:
            raise ValueError("找不到這個點數福利。")
        status = _legacy.point_item_status(
            rule_key=rule_key,
            point_item_key=point_item_key,
            point_balance=customer["points"],
            quantity=int(quote["quantity"]),
            has_specified_staff=bool(selected_staff),
        )
        if not status.get("allowed"):
            raise ValueError(str(status.get("reason") or "目前不能使用這個點數福利。"))
        selected_point_item = _legacy._point_item_for_rule(rule, item)

    service_amount = max(0, int(quote.get("customer_pay_amount") or 0))
    service_after_vip = int(round(service_amount * vip_rate / 100))
    selected_benefit = None
    selected_coupon_raw = None

    if benefit_coupon_id not in (None, ""):
        if selected_point_item is not None:
            raise ValueError("福利券與點數福利同張訂單只能擇一使用。")

        if source == SOURCE_LOYALTY:
            selected_coupon_raw = _legacy.get_applicable_coupon(
                int(real_benefit_id or 0),
                customer_id=customer_id,
                rule_key=rule_key,
                player_count=int(quote.get("player_count") or player_count or 1),
            )
            if selected_coupon_raw is None:
                raise ValueError("這張福利券已使用、已保留，或不適用這個方案。")
            selected_benefit = _loyalty_descriptor(
                coupon=selected_coupon_raw,
                rule_key=rule_key,
                player_count=int(quote.get("player_count") or player_count or 1),
                service_after_vip=service_after_vip,
            )

        elif source == SOURCE_VIP_MONTHLY:
            selected_coupon_raw = get_available_cash_benefit(
                int(real_benefit_id or 0),
                customer_id=customer_id,
            )
            if selected_coupon_raw is None:
                raise ValueError("這張 VIP 月券已使用、已保留或已失效。")
            selected_benefit = _vip_monthly_descriptor(
                benefit=selected_coupon_raw,
                quote=quote,
                service_after_vip=service_after_vip,
            )

        elif source == SOURCE_ISSUED:
            selected_benefit = _generic_benefit_descriptor(
                benefit=issued_benefit or {},
                customer_id=customer_id,
                rule_key=rule_key,
                quote=quote,
                service_after_vip=service_after_vip,
                specify_fee=specify_fee,
            )

    if selected_point_item is None and selected_benefit is None:
        selected_coupon_raw = _legacy.preview_same_order_benefit(
            customer_id,
            rule_key=rule_key,
            quantity=int(quote.get("quantity") or quantity or 1),
            player_count=int(quote.get("player_count") or player_count or 1),
        )
        if selected_coupon_raw:
            selected_benefit = _loyalty_descriptor(
                coupon=selected_coupon_raw,
                rule_key=rule_key,
                player_count=int(quote.get("player_count") or player_count or 1),
                service_after_vip=service_after_vip,
            )

    finance = calculate_checkout_financials(
        service_amount=service_amount,
        vip_pay_rate=vip_rate,
        specify_fee=specify_fee,
        point_item=selected_point_item,
        point_service_value=_legacy.calculate_point_service_value(
            quote=quote,
            vip_pay_rate=vip_rate,
            point_item=selected_point_item,
        ),
        benefit=selected_benefit,
        wallet_balance=customer["wallet_balance"],
        use_wallet=bool(use_wallet),
    )

    remaining = int(finance["remaining_pay_amount"])
    payment_method = str(payment_method or "").strip()
    if remaining > 0:
        if payment_method and payment_method not in _legacy.PAYMENT_METHODS:
            raise ValueError("付款方式格式錯誤。")
        if payment_method:
            payment_display = payment_method
            payment_info = _legacy.get_payment_method_info(payment_method) or ""
        else:
            payment_display = "接單滿人後於 Discord 選擇"
            payment_info = ""
    else:
        payment_display = "錢包全額" if finance["wallet_use_amount"] > 0 else "無需額外付款"
        payment_info = ""

    point_cost = int(selected_point_item["cost"]) if selected_point_item else 0
    point_name = str(selected_point_item["name"]) if selected_point_item else ""

    benefit_payload = None
    if selected_benefit:
        benefit_payload = {
            "id": selected_benefit.get("selector_id"),
            "real_id": selected_benefit.get("real_id"),
            "title": str(selected_benefit.get("title") or ""),
            "benefit_kind": str(selected_benefit.get("benefit_kind") or ""),
            "benefit_units": float(selected_benefit.get("benefit_units") or 0),
            "source": str(selected_benefit.get("source") or SOURCE_LOYALTY),
            "funding": str(selected_benefit.get("funding") or FUNDING_STORE),
            "same_order": bool(selected_benefit.get("same_order")),
            "earned_count": int(selected_benefit.get("earned_count") or 0),
            "scope_key": str(selected_benefit.get("scope_key") or ""),
            "rule_key": str(selected_benefit.get("rule_key") or ""),
            "player_count": int(selected_benefit.get("player_count") or quote.get("player_count") or 1),
        }

    return {
        "quote": quote,
        "customer": customer,
        "vip": vip,
        "selected_staff": selected_staff,
        "selected_staff_ids": [item["staff_id"] for item in selected_staff],
        "selected_role_keys": role_keys,
        "free_specify_by_rule": free_specify_by_rule,
        "point": {
            "key": selected_point_item["key"] if selected_point_item else None,
            "name": point_name,
            "cost": point_cost,
            "balance_before": customer["points"],
            "balance_after_preview": max(0, customer["points"] - point_cost),
        },
        "benefit_coupon": benefit_payload,
        "finance": finance,
        "payment": {
            "method": payment_display,
            "external_method": payment_method if remaining > 0 else None,
            "info": payment_info,
        },
        "wallet_after_preview": max(0, customer["wallet_balance"] - int(finance["wallet_use_amount"])),
        "read_only_preview": True,
        "server_verified": True,
    }
