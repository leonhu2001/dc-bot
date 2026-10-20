from __future__ import annotations

import json
from functools import wraps
from typing import Any

from services.vip_timer import (
    VIP_TIMER_CATEGORY,
    VIP_TIMER_CATEGORY_LABEL,
    VIP_TIMER_MARKER,
    VIP_TIMER_PREFIX,
    create_vip_timer_session,
    has_open_vip_timer,
    is_vip_timer_rule_key,
    strip_vip_timer_rule_key,
)
from web.app.services.site_data import get_member_summary


_INSTALLED = False
_GOLD_OR_ABOVE = {
    "金級魔丸",
    "白金魔丸",
    "鑽石魔丸",
    "白鑽魔丸",
    "黑鑽魔丸",
}


def _is_gold_or_above(customer_id: str) -> bool:
    if not str(customer_id or "").strip():
        return False
    try:
        summary = get_member_summary(str(customer_id))
    except Exception:
        return False
    return str(summary.get("vip_name") or "") in _GOLD_OR_ABOVE


def _vip_group(original_catalog) -> dict[str, Any]:
    variants: list[dict[str, Any]] = []
    seen: set[str] = set()

    for group in original_catalog("all"):
        category_label = str(group.get("category_label") or group.get("category") or "")
        group_label = str(group.get("label") or "")
        for raw in group.get("variants") or []:
            if str(raw.get("pricing_type") or "") != "hourly":
                continue
            real_key = str(raw.get("rule_key") or "").strip()
            if not real_key or real_key in seen:
                continue
            seen.add(real_key)
            item = dict(raw)
            item["rule_key"] = VIP_TIMER_PREFIX + real_key
            variant_label = str(raw.get("label") or group_label or real_key)
            prefix_parts = [part for part in (category_label, group_label) if part]
            prefix = "｜".join(prefix_parts)
            item["label"] = f"{prefix}｜{variant_label}" if prefix and variant_label not in prefix else (prefix or variant_label)
            item["quantity_enabled"] = False
            item["min_quantity"] = 1
            item["max_quantity"] = 1
            item["point_benefits_allowed"] = False
            item["loyalty_benefits_enabled"] = False
            item["vip_timer"] = True
            variants.append(item)

    variants.sort(key=lambda row: str(row.get("label") or ""))
    return {
        "key": "vip_timer_order",
        "category": VIP_TIMER_CATEGORY,
        "category_label": VIP_TIMER_CATEGORY_LABEL,
        "label": "VIP 自由計時單",
        "selector_label": "開始玩的遊戲／玩法",
        "description": "金級會員以上限定。先玩後付，只計實際遊玩時間；開始後可在票口隨時暫停或切換遊戲／玩法。",
        "starting_price": 0,
        "starting_price_text": "依實際時間結算",
        "vip_timer": True,
        "variants": variants,
    }


def _zero_preview_money(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    result = dict(data)
    quote = result.get("quote")
    if isinstance(quote, dict):
        quote = dict(quote)
        for key in ("customer_pay_amount", "remaining_pay_amount", "total_amount"):
            if key in quote:
                quote[key] = 0
        result["quote"] = quote
    finance = result.get("finance")
    if isinstance(finance, dict):
        finance = dict(finance)
        for key in (
            "remaining_pay_amount",
            "customer_pay_amount",
            "final_pay_amount",
            "pay_amount",
            "wallet_amount",
            "wallet_used",
        ):
            if key in finance:
                finance[key] = 0
        result["finance"] = finance
    payment = result.get("payment")
    if isinstance(payment, dict):
        payment = dict(payment)
        payment["method"] = "遊玩結束後付款"
        result["payment"] = payment
    result["vip_timer"] = True
    result["vip_timer_note"] = "本單先玩後付；此處僅確認起始玩法，實際金額依票口計時區段結算。"
    return result


def _clear_timer_benefits(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    result = dict(data)
    for key in (
        "point_items",
        "point_benefits",
        "benefit_coupons",
        "coupons",
        "available_coupons",
    ):
        if key in result and isinstance(result[key], list):
            result[key] = []
    result["vip_timer"] = True
    return result


def install(site_module) -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_categories = site_module.get_public_order_categories
    original_catalog = site_module.get_grouped_order_catalog
    original_quote = site_module.build_public_quote
    original_options = site_module.build_checkout_options
    original_preview = site_module.build_checkout_preview

    def categories_wrapper():
        rows = list(original_categories())
        if not any(str(row.get("key") or "") == VIP_TIMER_CATEGORY for row in rows):
            rows.append({"key": VIP_TIMER_CATEGORY, "label": VIP_TIMER_CATEGORY_LABEL})
        return rows

    def catalog_wrapper(category: str = "all"):
        key = str(category or "all")
        if key == VIP_TIMER_CATEGORY:
            return [_vip_group(original_catalog)]
        rows = list(original_catalog(key))
        if key == "all":
            rows.append(_vip_group(original_catalog))
        return rows

    @wraps(original_quote)
    def quote_wrapper(*args, **kwargs):
        rule_key = kwargs.get("rule_key")
        if rule_key is None and args:
            rule_key = args[0]
        if not is_vip_timer_rule_key(rule_key):
            return original_quote(*args, **kwargs)
        real_key = strip_vip_timer_rule_key(rule_key)
        if "rule_key" in kwargs:
            kwargs = dict(kwargs); kwargs["rule_key"] = real_key
            result = original_quote(*args, **kwargs)
        else:
            new_args = list(args); new_args[0] = real_key
            result = original_quote(*new_args, **kwargs)
        if isinstance(result, dict):
            result = dict(result)
            result["vip_timer"] = True
            result["customer_pay_amount"] = 0
            result["total_amount"] = 0
            result["note"] = "VIP 自由計時｜遊玩結束後依實際秒數結算"
        return result

    @wraps(original_options)
    def options_wrapper(*args, **kwargs):
        rule_key = kwargs.get("rule_key")
        if not is_vip_timer_rule_key(rule_key):
            return original_options(*args, **kwargs)
        customer_id = str(kwargs.get("customer_id") or "")
        if not _is_gold_or_above(customer_id):
            raise ValueError("VIP 自由計時單僅限金級會員以上使用。")
        kwargs = dict(kwargs)
        kwargs["rule_key"] = strip_vip_timer_rule_key(rule_key)
        kwargs["quantity"] = 1
        return _clear_timer_benefits(original_options(*args, **kwargs))

    @wraps(original_preview)
    def preview_wrapper(*args, **kwargs):
        rule_key = kwargs.get("rule_key")
        if not is_vip_timer_rule_key(rule_key):
            return original_preview(*args, **kwargs)
        customer_id = str(kwargs.get("customer_id") or "")
        if not _is_gold_or_above(customer_id):
            raise ValueError("VIP 自由計時單僅限金級會員以上使用。")
        kwargs = dict(kwargs)
        kwargs["rule_key"] = strip_vip_timer_rule_key(rule_key)
        kwargs["quantity"] = 1
        kwargs["point_item_key"] = None
        kwargs["benefit_coupon_id"] = None
        kwargs["use_wallet"] = False
        return _zero_preview_money(original_preview(*args, **kwargs))

    site_module.get_public_order_categories = categories_wrapper
    site_module.get_grouped_order_catalog = catalog_wrapper
    site_module.build_public_quote = quote_wrapper
    site_module.build_checkout_options = options_wrapper
    site_module.build_checkout_preview = preview_wrapper

    # /order/create imports this function lazily, so patch the service module itself.
    from web.app.services import public_order_create as create_module
    original_create = create_module.create_public_order

    @wraps(original_create)
    def create_wrapper(db, *, customer_id: str, customer_display_name: str, payload: dict, request_key: str):
        incoming_key = str((payload or {}).get("rule_key") or "")
        if not is_vip_timer_rule_key(incoming_key):
            return original_create(
                db,
                customer_id=customer_id,
                customer_display_name=customer_display_name,
                payload=payload,
                request_key=request_key,
            )
        if not _is_gold_or_above(str(customer_id)):
            raise ValueError("VIP 自由計時單僅限金級會員以上使用。")
        if has_open_vip_timer(str(customer_id)):
            raise ValueError("你目前已有一張進行中或待付款的 VIP 自由計時單，請先完成上一張。")

        real_key = strip_vip_timer_rule_key(incoming_key)
        clean_payload = dict(payload or {})
        clean_payload["rule_key"] = real_key
        clean_payload["quantity"] = 1
        clean_payload["point_item_key"] = None
        clean_payload["benefit_coupon_id"] = None
        clean_payload["use_wallet"] = False
        clean_payload["payment_method"] = "轉帳"

        order = original_create(
            db,
            customer_id=str(customer_id),
            customer_display_name=customer_display_name,
            payload=clean_payload,
            request_key=request_key,
        )

        from services.order_rules import ORDER_RULES
        rule = ORDER_RULES.get(real_key)
        initial_label = str(getattr(rule, "label", real_key) or real_key)
        player_count = max(1, int(clean_payload.get("player_count") or 1))
        zero_snapshot = {
            "vip_timer": True,
            "initial_rule_key": real_key,
            "initial_rule_label": initial_label,
            "player_count": player_count,
            "customer_pay_amount": 0,
            "remaining_pay_amount": 0,
            "original_amount": 0,
            "payout_base_amount": 0,
            "note": "遊玩結束後依實際計時區段結算",
        }
        snapshot_text = json.dumps(zero_snapshot, ensure_ascii=False, sort_keys=True)

        order.item = f"自由計時｜{initial_label}"
        order.amount = 0
        order.original_amount = 0
        order.payout_base_amount = 0
        order.customer_pay_amount = 0
        order.manual_discount_amount = 0
        order.cash_coupon_amount = 0
        order.store_absorbed_amount = 0
        order.payment_method = "待後付"
        order.price_snapshot_json = snapshot_text
        order.note = f"{VIP_TIMER_MARKER}｜initial_rule={real_key}｜先玩後付"

        db.execute(create_module.text("""
            UPDATE order_acceptance_meta
            SET price_snapshot_json=:snapshot,
                point_benefits_allowed=0,
                updated_at=CURRENT_TIMESTAMP
            WHERE order_id=:order_id
        """), {"snapshot": snapshot_text, "order_id": int(order.id)})

        create_vip_timer_session(
            db,
            order_id=int(order.id),
            customer_id=str(customer_id),
            initial_rule_key=real_key,
        )
        db.flush()
        return order

    create_module.create_public_order = create_wrapper
