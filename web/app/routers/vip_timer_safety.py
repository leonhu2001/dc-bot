from __future__ import annotations

from functools import wraps

from services.vip_timer import is_vip_timer_rule_key


_INSTALLED = False


def install(vip_timer_module) -> None:
    """Keep v1 timer billing free of untracked one-time specify fees.

    VIP timer v1 settles only metered hourly segments. Until fixed-fee segments
    are explicitly modeled, hide staff specification and reject crafted create
    requests that try to add specified staff for free.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_group = vip_timer_module._vip_group

    def safe_group(original_catalog):
        group = original_group(original_catalog)
        variants = []
        for source in group.get("variants") or []:
            item = dict(source)
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
    def safe_create(db, *, customer_id: str, customer_display_name: str, payload: dict, request_key: str):
        rule_key = str((payload or {}).get("rule_key") or "")
        if is_vip_timer_rule_key(rule_key):
            specified = [
                str(value).strip()
                for value in ((payload or {}).get("specified_staff_ids") or [])
                if str(value).strip()
            ]
            if specified:
                raise ValueError("VIP 自由計時第一版不支援指定人員，請改用一般訂單指定。")
        return current_create(
            db,
            customer_id=customer_id,
            customer_display_name=customer_display_name,
            payload=payload,
            request_key=request_key,
        )

    create_module.create_public_order = safe_create


__all__ = ["install"]
