from __future__ import annotations

from services import vip_timer_selector_order_v3 as v3


_INSTALLED = False

_GENERAL_ORDER = {
    "單陪": 0,
    "雙陪": 1,
    "三陪": 2,
    "四陪": 3,
}
_SWEET_ORDER = {
    "女單陪": 0,
    "男單陪": 1,
    "女雙陪": 2,
    "男雙陪": 3,
}
_TEACHING_ORDER = {
    "1對1教學": 0,
}


def _service_order(gameplay_label: str) -> dict[str, int]:
    label = str(gameplay_label or "")
    if label == "甜蜜":
        return _SWEET_ORDER
    if label == "教學":
        return _TEACHING_ORDER
    return _GENERAL_ORDER


def _sweet_gender(rule, text: str) -> str:
    value = str(text or "")
    if "女單陪" in value or "女雙陪" in value:
        return "女"
    if "男單陪" in value or "男雙陪" in value:
        return "男"

    roles = set(tuple(getattr(rule, "allowed_roles", ()) or ()))
    if roles and roles <= {"female_companion"}:
        return "女"
    if roles and roles <= {"male_companion"}:
        return "男"
    return ""


def _service_type(source_group: str, detail: dict, rule) -> str:
    from services import vip_timer_select_flow as flow

    group_text = str(source_group or "")
    detail_text = str(detail.get("label") or "")
    rule_text = str(getattr(rule, "label", "") or "")
    text = f"{group_text}｜{detail_text}｜{rule_text}"
    count = int(flow._staff_count(rule, detail))

    if "甜蜜" in text:
        # VIP 自由計時的甜蜜單只讓顧客選明確性別配置；舊的「雙陪(不限)」
        # 仍保留給一般下單，但不出現在這個第四層。
        if "不限" in text:
            return "不支援"
        gender = _sweet_gender(rule, text)
        if gender == "女" and count == 1:
            return "女單陪"
        if gender == "男" and count == 1:
            return "男單陪"
        if gender == "女" and count == 2:
            return "女雙陪"
        if gender == "男" and count == 2:
            return "男雙陪"
        return "不支援"

    if "教學" in text or "導師" in text:
        return "1對1教學" if count == 1 else "不支援"

    return v3._HEADCOUNT_LABELS.get(count, "不支援")


def _spec_groups(details: list[dict]) -> list[dict]:
    from services import vip_timer_select_flow as flow
    from services.vip_timer_selector_order_v2 import _spec_key

    grouped: dict[str, list[dict]] = {}
    for detail in details:
        label = str(detail.get("vip_timer_spec_label") or "技術").strip() or "技術"
        service_type = str(detail.get("vip_timer_service_type") or "")
        if service_type not in _service_order(label):
            continue
        grouped.setdefault(label, []).append(detail)

    result: list[dict] = []
    for label, rows in grouped.items():
        order = _service_order(label)
        by_service: dict[str, dict] = {}
        for detail in rows:
            service_type = str(detail.get("vip_timer_service_type") or "")
            current = by_service.get(service_type)
            if current is None or v3._detail_preference(detail) > v3._detail_preference(current):
                by_service[service_type] = detail

        canonical = sorted(
            by_service.values(),
            key=lambda row: order.get(str(row.get("vip_timer_service_type") or ""), 99),
        )
        if not canonical:
            continue
        rates = [flow._effective_rate(row) for row in canonical if flow._effective_rate(row) > 0]
        result.append(
            {
                "key": _spec_key(label),
                "label": label[:100],
                "details": canonical,
                "min_rate": min(rates) if rates else 0,
            }
        )

    result.sort(key=v3._group_sort_key)
    return result


def _is_teaching_rule(key: str, rule) -> bool:
    if rule is None:
        return False
    if str(getattr(rule, "pricing_type", "") or "") != "hourly":
        return False
    if int(getattr(rule, "price", 0) or 0) <= 0:
        return False
    label = str(getattr(rule, "label", "") or "")
    return "教學" in label or "導師" in label or str(key or "").endswith("_teaching_one")


def _install_timer_public_rule_guard() -> None:
    from services import vip_timer_catalog_guard as guard
    from services.order_product_status import is_order_product_active
    from services.order_rules import ORDER_RULES

    if getattr(guard, "_vip_timer_v4_public_guard_installed", False):
        return

    previous_public_keys = guard.public_timer_rule_keys

    def public_timer_rule_keys() -> set[str]:
        result = set(previous_public_keys())
        result.discard(v3._VIRTUAL_SWEET_SINGLE_KEY)
        for key, rule in ORDER_RULES.items():
            key = str(key or "").strip()
            if not key or not _is_teaching_rule(key, rule):
                continue
            if not is_order_product_active(key):
                continue
            result.add(key)
        return result

    def is_public_timer_rule(rule_key) -> bool:
        key = str(rule_key or "").strip()
        return bool(key) and key in public_timer_rule_keys()

    guard.public_timer_rule_keys = public_timer_rule_keys
    guard.is_public_timer_rule = is_public_timer_rule
    guard._vip_timer_v4_public_guard_installed = True


def _remove_virtual_sweet_rows() -> None:
    from services import orders
    from services.vip_timer import VIP_TIMER_CATEGORY

    groups = orders.SELF_SERVICE_ORDER_CATALOG.get(VIP_TIMER_CATEGORY) or []
    for group in groups:
        group["details"] = [
            row for row in list(group.get("details") or [])
            if str(row.get("rule_key") or "") != v3._VIRTUAL_SWEET_SINGLE_KEY
        ]


def install_vip_timer_selector_order_v4() -> None:
    """Use family-specific fourth-layer labels for VIP free-timer orders."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer_select_flow as flow
    from services import vip_timer_self_service as bridge
    from services import vip_timer_selector_order_v2 as v2

    _install_timer_public_rule_guard()

    flow._service_type = _service_type
    v2._service_type = _service_type
    v2._spec_groups = _spec_groups

    previous_refresh = flow.refresh_vip_timer_self_service_catalog

    def refresh_vip_timer_self_service_catalog() -> None:
        flow._CATALOG_CACHE = None
        flow._CATALOG_CACHE_AT = 0.0
        previous_refresh()
        _remove_virtual_sweet_rows()

    flow.refresh_vip_timer_self_service_catalog = refresh_vip_timer_self_service_catalog
    bridge.refresh_vip_timer_self_service_catalog = refresh_vip_timer_self_service_catalog

    refresh_vip_timer_self_service_catalog()
    _INSTALLED = True


__all__ = [
    "install_vip_timer_selector_order_v4",
]
