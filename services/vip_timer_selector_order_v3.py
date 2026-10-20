from __future__ import annotations

from dataclasses import replace
import re


_INSTALLED = False
_VIRTUAL_SWEET_SINGLE_KEY = "vip_timer_sweet_single_any"
_HEADCOUNT_LABELS = {
    1: "單陪",
    2: "雙陪",
    3: "三陪",
    4: "四陪",
}
_HEADCOUNT_ORDER = {label: index for index, label in enumerate(_HEADCOUNT_LABELS.values())}


def _strip_headcount(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"(?:｜?陪玩[1-9]名)", "", value)
    value = re.sub(r"(?:單陪|雙陪|三陪|四陪|五陪|六陪|七陪|八陪|九陪|[1-9]陪)", "", value)
    return value.strip("｜ /-")


def _headcount_service_type(source_group: str, detail: dict, rule) -> str:
    from services import vip_timer_select_flow as flow

    count = flow._staff_count(rule, detail)
    return _HEADCOUNT_LABELS.get(int(count), "不支援")


def _technical_qualifier(group_text: str, detail_text: str) -> str:
    group = _strip_headcount(group_text)
    detail = _strip_headcount(detail_text)

    for token in ("技術陪", "技術單", "技術"):
        group = group.replace(token, "").strip("｜ /-")
        detail = detail.replace(token, "").strip("｜ /-")

    # 技術陪的規格（例如機密／絕密）優先；段位型商品則通常把
    # 段位放在上一層 group（例如超凡陪、神話陪）。
    generic_detail = {"", "NG", "積分", "一般", "基礎"}
    if detail not in generic_detail:
        return detail

    group = re.sub(r"陪$", "", group).strip("｜ /-")
    if group and group not in {"娛樂", "甜蜜", "教學", "一般", "基礎", "後台新增商品"}:
        return group
    return ""


def _gameplay_label(*, source_group: str, detail_label: str, variant: str, service_type: str) -> str:
    group_text = str(source_group or "").strip()
    detail_text = str(detail_label or "").strip()
    text = f"{group_text}｜{detail_text}"

    if "甜蜜" in text:
        return "甜蜜"
    if "教學" in text or "導師" in text:
        return "教學"
    if "娛樂" in text:
        return "娛樂"

    qualifier = _technical_qualifier(group_text, detail_text)
    if qualifier:
        return f"技術｜{qualifier}"[:100]
    return "技術"


def _group_sort_key(group: dict) -> tuple:
    label = str(group.get("label") or "")
    if label == "娛樂":
        return (0, 0, label)
    if label.startswith("技術"):
        # 同一遊戲內依參考時薪由低到高排列，讓機密→絕密、低段位→高段位
        # 自然跟著目前價目走；同價時再用常見難度順序與文字穩定排序。
        qualifier = label.split("｜", 1)[1] if "｜" in label else ""
        known = {
            "機密": 10,
            "絕密": 20,
            "絕巴": 30,
        }.get(qualifier, 100)
        return (1, int(group.get("min_rate") or 0), known, label)
    if label == "甜蜜":
        return (2, 0, label)
    if label == "教學":
        return (3, 0, label)
    return (4, 0, label)


def _detail_preference(detail: dict) -> tuple:
    """Pick one canonical rule when old catalog rows collapse to one headcount."""
    from services.order_rules import ORDER_RULES

    key = str(detail.get("rule_key") or "")
    rule = ORDER_RULES.get(key)
    role_count = len(tuple(getattr(rule, "allowed_roles", ()) or ())) if rule is not None else 0
    virtual = 1 if key == _VIRTUAL_SWEET_SINGLE_KEY else 0
    any_label = 1 if "不限" in str(detail.get("item") or detail.get("label") or "") else 0
    return (virtual, role_count, any_label, -len(str(detail.get("value") or "")))


def _spec_groups(details: list[dict]) -> list[dict]:
    from services import vip_timer_select_flow as flow
    from services.vip_timer_selector_order_v2 import _spec_key

    grouped: dict[str, list[dict]] = {}
    for detail in details:
        service_type = str(detail.get("vip_timer_service_type") or "")
        if service_type not in _HEADCOUNT_ORDER:
            continue
        label = str(detail.get("vip_timer_spec_label") or "技術").strip() or "技術"
        grouped.setdefault(label, []).append(detail)

    result: list[dict] = []
    for label, rows in grouped.items():
        by_headcount: dict[str, dict] = {}
        for detail in rows:
            service_type = str(detail.get("vip_timer_service_type") or "")
            current = by_headcount.get(service_type)
            if current is None or _detail_preference(detail) > _detail_preference(current):
                by_headcount[service_type] = detail

        canonical = sorted(
            by_headcount.values(),
            key=lambda row: _HEADCOUNT_ORDER.get(str(row.get("vip_timer_service_type") or ""), 99),
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

    result.sort(key=_group_sort_key)
    return result


def _install_virtual_sweet_single_rule() -> None:
    from services.order_rules import COMPANION_ROLES, ORDER_RULES

    if ORDER_RULES.get(_VIRTUAL_SWEET_SINGLE_KEY) is not None:
        return

    base = ORDER_RULES.get("basic_sweet_female_single") or ORDER_RULES.get("basic_sweet_male_single")
    if base is None:
        return

    ORDER_RULES[_VIRTUAL_SWEET_SINGLE_KEY] = replace(
        base,
        key=_VIRTUAL_SWEET_SINGLE_KEY,
        label="甜蜜單｜單陪",
        allowed_roles=tuple(COMPANION_ROLES),
        required_staff_count=1,
    )


def _install_virtual_rule_guard() -> None:
    from services import vip_timer_catalog_guard as guard

    if getattr(guard, "_vip_timer_v3_virtual_guard_installed", False):
        return

    original_public_keys = guard.public_timer_rule_keys

    def public_timer_rule_keys() -> set[str]:
        result = set(original_public_keys())
        from services.order_rules import ORDER_RULES

        if ORDER_RULES.get(_VIRTUAL_SWEET_SINGLE_KEY) is not None:
            result.add(_VIRTUAL_SWEET_SINGLE_KEY)
        return result

    def is_public_timer_rule(rule_key) -> bool:
        key = str(rule_key or "").strip()
        return bool(key) and key in public_timer_rule_keys()

    guard.public_timer_rule_keys = public_timer_rule_keys
    guard.is_public_timer_rule = is_public_timer_rule
    guard._vip_timer_v3_virtual_guard_installed = True


def _inject_virtual_sweet_single_detail() -> None:
    from services import orders
    from services.vip_timer import VIP_TIMER_CATEGORY
    from services import vip_timer_select_flow as flow

    groups = orders.SELF_SERVICE_ORDER_CATALOG.get(VIP_TIMER_CATEGORY) or []
    for group in groups:
        details = list(group.get("details") or [])
        if not any(str(row.get("vip_timer_spec_label") or "") == "甜蜜" for row in details):
            continue
        if any(str(row.get("rule_key") or "") == _VIRTUAL_SWEET_SINGLE_KEY for row in details):
            continue
        base = next(
            (
                row for row in details
                if str(row.get("vip_timer_spec_label") or "") == "甜蜜"
                and str(row.get("vip_timer_service_type") or "") == "單陪"
            ),
            None,
        )
        if base is None:
            continue
        virtual = dict(base)
        virtual.update(
            {
                "label": "甜蜜",
                "value": flow._timer_detail_value(_VIRTUAL_SWEET_SINGLE_KEY, 0),
                "rule_key": _VIRTUAL_SWEET_SINGLE_KEY,
                "item": "甜蜜單｜單陪",
                "vip_timer_service_type": "單陪",
                "vip_timer_spec_label": "甜蜜",
            }
        )
        virtual.pop("player_count", None)
        details.append(virtual)
        group["details"] = details


def install_vip_timer_selector_order_v3() -> None:
    """Refine VIP timer selectors to game -> gameplay family -> 1/2/3/4 companions."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer_select_flow as flow
    from services import vip_timer_self_service as bridge
    from services import vip_timer_selector_order_v2 as v2

    _install_virtual_sweet_single_rule()
    _install_virtual_rule_guard()

    # Rebuild the timer catalog with the concise third-layer labels and pure
    # headcount fourth layer requested by the storefront UX.
    flow._service_type = _headcount_service_type
    flow._spec_label = _gameplay_label
    v2._service_type = _headcount_service_type
    v2._spec_label = _gameplay_label
    v2._spec_groups = _spec_groups

    original_refresh = flow.refresh_vip_timer_self_service_catalog

    def refresh_vip_timer_self_service_catalog() -> None:
        flow._CATALOG_CACHE = None
        flow._CATALOG_CACHE_AT = 0.0
        original_refresh()
        _inject_virtual_sweet_single_detail()

    flow.refresh_vip_timer_self_service_catalog = refresh_vip_timer_self_service_catalog
    bridge.refresh_vip_timer_self_service_catalog = refresh_vip_timer_self_service_catalog

    refresh_vip_timer_self_service_catalog()
    _INSTALLED = True


__all__ = [
    "install_vip_timer_selector_order_v3",
]
