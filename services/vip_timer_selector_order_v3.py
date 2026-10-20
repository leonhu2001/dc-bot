from __future__ import annotations

import re


_INSTALLED = False
_HEADCOUNT_LABELS = {
    1: "單陪",
    2: "雙陪",
    3: "三陪",
    4: "四陪",
}
_SERVICE_ORDER = {
    "單陪": 0,
    "雙陪": 1,
    "三陪": 2,
    "四陪": 3,
    "女單陪": 0,
    "男單陪": 1,
    "女雙陪": 2,
    "男雙陪": 3,
    "1對1教學": 0,
}


def _strip_headcount(text: str) -> str:
    value = str(text or "").strip()
    value = re.sub(r"(?:｜?陪玩[1-9]名)", "", value)
    value = re.sub(r"(?:單陪|雙陪|三陪|四陪|五陪|六陪|七陪|八陪|九陪|[1-9]陪)", "", value)
    return value.strip("｜ /-")


def _headcount_service_type(source_group: str, detail: dict, rule) -> str:
    """Return the fourth-layer label for VIP 自由計時.

    Normal gameplay uses pure headcount. Sweet orders preserve the companion
    gender package because that changes which roles may receive the order.
    Teaching is a single explicit 1-to-1 product instead of being disguised as
    an ordinary single-companion option.
    """
    from services import vip_timer_select_flow as flow

    detail_text = str(detail.get("label") or "")
    rule_text = str(getattr(rule, "label", "") or "")
    text = f"{source_group}｜{detail_text}｜{rule_text}"
    count = flow._staff_count(rule, detail)

    if "甜蜜" in text:
        for label in ("女單陪", "男單陪", "女雙陪", "男雙陪"):
            if label in text:
                return label
        # 不再提供舊的「雙陪(不限)」與泛用甜蜜規則；第四層必須明確選性別套餐。
        return "不支援"

    if "教學" in text or "導師" in text:
        return "1對1教學" if int(count) == 1 else "不支援"

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
    """Pick one canonical rule when catalog rows collapse to one service label."""
    from services.order_rules import ORDER_RULES

    key = str(detail.get("rule_key") or "")
    rule = ORDER_RULES.get(key)
    role_count = len(tuple(getattr(rule, "allowed_roles", ()) or ())) if rule is not None else 0
    any_label = 1 if "不限" in str(detail.get("item") or detail.get("label") or "") else 0
    return (role_count, any_label, -len(str(detail.get("value") or "")))


def _spec_groups(details: list[dict]) -> list[dict]:
    from services import vip_timer_select_flow as flow
    from services.vip_timer_selector_order_v2 import _spec_key

    grouped: dict[str, list[dict]] = {}
    for detail in details:
        service_type = str(detail.get("vip_timer_service_type") or "")
        if service_type not in _SERVICE_ORDER:
            continue
        label = str(detail.get("vip_timer_spec_label") or "技術").strip() or "技術"
        grouped.setdefault(label, []).append(detail)

    result: list[dict] = []
    for label, rows in grouped.items():
        by_service: dict[str, dict] = {}
        for detail in rows:
            service_type = str(detail.get("vip_timer_service_type") or "")
            current = by_service.get(service_type)
            if current is None or _detail_preference(detail) > _detail_preference(current):
                by_service[service_type] = detail

        canonical = sorted(
            by_service.values(),
            key=lambda row: _SERVICE_ORDER.get(str(row.get("vip_timer_service_type") or ""), 99),
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


def install_vip_timer_selector_order_v3() -> None:
    """Refine VIP timer selectors to game -> gameplay family -> service package."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer_select_flow as flow
    from services import vip_timer_self_service as bridge
    from services import vip_timer_selector_order_v2 as v2

    # Rebuild the timer catalog with concise third-layer labels. Normal gameplay
    # uses 1–4 companion headcount, while sweet/teaching retain their meaningful
    # package labels in the fourth layer.
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

    flow.refresh_vip_timer_self_service_catalog = refresh_vip_timer_self_service_catalog
    bridge.refresh_vip_timer_self_service_catalog = refresh_vip_timer_self_service_catalog

    refresh_vip_timer_self_service_catalog()
    _INSTALLED = True


__all__ = [
    "install_vip_timer_selector_order_v3",
]
