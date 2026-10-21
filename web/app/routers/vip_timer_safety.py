from __future__ import annotations

from functools import wraps

from services.vip_timer import (
    is_vip_timer_rule_key,
    strip_vip_timer_rule_key,
)


_INSTALLED = False


def _is_public_timer_rule(rule_key) -> bool:
    """Resolve the live shared policy instead of freezing the pre-policy function.

    services.vip_timer_policy_v5 replaces catalog_guard.is_public_timer_rule at
    runtime to exclude sweet/teaching, mobile-only forbidden modes and products
    that reject VIP discounts. Importing the function once at module import time
    would bypass those later policy refinements on the website.
    """
    from services import vip_timer_catalog_guard as catalog_guard

    return bool(catalog_guard.is_public_timer_rule(rule_key))


def install(vip_timer_module) -> None:
    """Keep the public website inside the same timer contract as Discord.

    Every UI list and every crafted quote/create request resolves the live shared
    catalog guard, so website and Discord cannot drift on which products are
    eligible for VIP timing.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_group = vip_timer_module._vip_group
    original_timer_key_check = vip_timer_module.is_vip_timer_rule_key

    def safe_timer_key_check(rule_key) -> bool:
        if not original_timer_key_check(rule_key):
            return False
        return _is_public_timer_rule(strip_vip_timer_rule_key(rule_key))

    # quote/options/preview/create wrappers in vip_timer.py resolve this module
    # global at call time, so one replacement protects every public endpoint.
    vip_timer_module.is_vip_timer_rule_key = safe_timer_key_check

    def safe_group(original_catalog):
        group = original_group(original_catalog)
        variants = []
        for source in group.get("variants") or []:
            item = dict(source)
            real_key = strip_vip_timer_rule_key(item.get("rule_key"))
            if not _is_public_timer_rule(real_key):
                continue
            item["allow_specify"] = False
            item["max_specified_count"] = 0
            variants.append(item)
        group = dict(group)
        group["variants"] = variants
        return group

    vip_timer_module._vip_group = safe_group

    from web.app.services import public_order_create as create_module

    current_create = create_module.create_public_order

    @wraps(current_create)
    def safe_create(
        db,
        *,
        customer_id: str,
        customer_display_name: str,
        payload: dict,
        request_key: str,
    ):
        rule_key = str((payload or {}).get("rule_key") or "")
        if is_vip_timer_rule_key(rule_key):
            real_key = strip_vip_timer_rule_key(rule_key)
            if not _is_public_timer_rule(real_key):
                raise ValueError(
                    "這個玩法目前不能用於 VIP 自由計時，請重新選擇玩法。"
                )

            specified = [
                str(value).strip()
                for value in ((payload or {}).get("specified_staff_ids") or [])
                if str(value).strip()
            ]
            if specified:
                raise ValueError(
                    "VIP 自由計時第一版不支援指定人員，請改用一般訂單指定。"
                )

        return current_create(
            db,
            customer_id=customer_id,
            customer_display_name=customer_display_name,
            payload=payload,
            request_key=request_key,
        )

    create_module.create_public_order = safe_create


__all__ = ["install"]
