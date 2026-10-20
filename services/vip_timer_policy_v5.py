from __future__ import annotations

from dataclasses import replace
import json


_INSTALLED = False
_MOBILE_EXBAR_KEY = "basic_mobile_exbar_tech"
_GAME_LABELS = {
    "delta_desktop_basic": "三角洲端遊",
    "delta_mobile_basic": "三角洲手遊",
    "valorant": "特戰英豪",
    "lol": "英雄聯盟",
    "apex": "APEX",
    "steam": "STEAM",
}
_GAME_ORDER = tuple(_GAME_LABELS.values())


def _rule_text(rule) -> str:
    return "｜".join(
        str(value or "")
        for value in (
            getattr(rule, "label", ""),
            getattr(rule, "catalog_group_label", ""),
        )
    )


def _install_mobile_exbar_rule() -> None:
    from services.order_rules import (
        DELTA_MOBILE_GAME_ROLE,
        ORDER_RULES,
    )

    if ORDER_RULES.get(_MOBILE_EXBAR_KEY) is not None:
        return
    desktop = ORDER_RULES.get("basic_exbar_tech")
    if desktop is None:
        return
    ORDER_RULES[_MOBILE_EXBAR_KEY] = replace(
        desktop,
        key=_MOBILE_EXBAR_KEY,
        category="delta_mobile_basic",
        label="絕巴技術陪〈手遊〉",
        required_game_roles=DELTA_MOBILE_GAME_ROLE,
    )


def _install_catalog_guard_policy() -> None:
    from services import vip_timer_catalog_guard as guard
    from services.order_rules import ORDER_RULES

    if getattr(guard, "_vip_timer_v5_policy_installed", False):
        return

    original_public_keys = guard.public_timer_rule_keys

    def public_timer_rule_keys() -> set[str]:
        result = set(original_public_keys())
        if ORDER_RULES.get(_MOBILE_EXBAR_KEY) is not None:
            result.add(_MOBILE_EXBAR_KEY)

        filtered: set[str] = set()
        for key in result:
            rule = ORDER_RULES.get(str(key))
            if rule is None:
                continue
            category = str(getattr(rule, "category", "") or "")
            if category not in _GAME_LABELS:
                continue
            text_value = _rule_text(rule)
            if "甜蜜" in text_value or "教學" in text_value or "導師" in text_value:
                continue
            if category == "delta_mobile_basic" and "黑潮爆破" in text_value:
                continue
            # VIP 自由計時整張單會套 VIP 百分比折扣，因此不收錄原本
            # 明確標示「不適用 VIP 折扣」的來源商品。
            if not bool(getattr(rule, "vip_discount_allowed", True)):
                continue
            filtered.add(str(key))
        return filtered

    def is_public_timer_rule(rule_key) -> bool:
        key = str(rule_key or "").strip()
        return bool(key) and key in public_timer_rule_keys()

    guard.public_timer_rule_keys = public_timer_rule_keys
    guard.is_public_timer_rule = is_public_timer_rule
    guard._vip_timer_v5_policy_installed = True


def _special_gameplay_label(*, source_group: str, detail_label: str, variant: str, service_type: str) -> str:
    from services import vip_timer_selector_order_v3 as v3

    original = getattr(v3, "_vip_timer_v5_original_gameplay_label", None)
    if original is None:
        original = v3._gameplay_label
        v3._vip_timer_v5_original_gameplay_label = original

    text_value = f"{source_group}｜{detail_label}"
    if "黑潮爆破" in text_value:
        return "黑潮爆破"
    if "絕巴技術陪" in text_value or ("絕巴" in text_value and "技術" in text_value):
        return "絕巴技術陪"
    return original(
        source_group=source_group,
        detail_label=detail_label,
        variant=variant,
        service_type=service_type,
    )


def _gameplay_sort_key(group: dict) -> tuple:
    from services import vip_timer_selector_order_v3 as v3

    label = str(group.get("label") or "")
    fixed = {
        "娛樂": 0,
        "技術｜機密": 10,
        "技術｜絕密": 20,
        "絕巴技術陪": 30,
        "黑潮爆破": 40,
    }
    if label in fixed:
        return (fixed[label], int(group.get("min_rate") or 0), label)

    original = getattr(v3, "_vip_timer_v5_original_group_sort_key", None)
    if original is None:
        original = v3._group_sort_key
        v3._vip_timer_v5_original_group_sort_key = original
    old = original(group)
    return (50, *old)


def _install_selector_policy() -> None:
    from services import vip_timer_select_flow as flow
    from services import vip_timer_selector_order_v2 as v2
    from services import vip_timer_selector_order_v3 as v3
    from services.order_rules import ORDER_RULES

    if getattr(flow, "_vip_timer_v5_policy_installed", False):
        return

    # Exact second-layer names. The wrapper below regroups by source category,
    # so old aliases such as 「三角洲行動｜端遊」 cannot leak back into the UI.
    flow._GAME_META.update({key: (label, "") for key, label in _GAME_LABELS.items()})

    v3._vip_timer_v5_original_gameplay_label = v3._gameplay_label
    v3._vip_timer_v5_original_group_sort_key = v3._group_sort_key
    v3._gameplay_label = _special_gameplay_label
    v3._group_sort_key = _gameplay_sort_key
    flow._spec_label = _special_gameplay_label
    v2._spec_label = _special_gameplay_label
    v2._spec_groups = v3._spec_groups

    original_build = flow._build_catalog_uncached

    def build_catalog_uncached() -> list[dict]:
        raw_groups = original_build()
        regrouped: dict[str, list[dict]] = {label: [] for label in _GAME_ORDER}
        seen: set[tuple[str, int]] = set()

        for group in raw_groups:
            for raw in group.get("details", []) or []:
                detail = dict(raw)
                category = str(detail.get("vip_timer_source_category") or "")
                game_label = _GAME_LABELS.get(category)
                if not game_label:
                    continue
                rule_key = str(detail.get("rule_key") or "").strip()
                rule = ORDER_RULES.get(rule_key)
                if rule is None:
                    continue
                text_value = f"{_rule_text(rule)}｜{detail.get('label') or ''}｜{detail.get('item') or ''}"
                if "甜蜜" in text_value or "教學" in text_value or "導師" in text_value:
                    continue
                if category == "delta_mobile_basic" and "黑潮爆破" in text_value:
                    continue
                try:
                    player_count = int(detail.get("player_count") or 0)
                except (TypeError, ValueError):
                    player_count = 0
                unique = (rule_key, player_count)
                if unique in seen:
                    continue
                seen.add(unique)
                regrouped[game_label].append(detail)

        # 絕巴技術陪在一般價目目前只有端遊 canonical rule；VIP timer
        # 需要手遊入口，因此建立一個只供 timer 使用的手遊 rule snapshot。
        mobile_rule = ORDER_RULES.get(_MOBILE_EXBAR_KEY)
        if mobile_rule is not None and (_MOBILE_EXBAR_KEY, 0) not in seen:
            regrouped["三角洲手遊"].append(
                {
                    "label": "絕巴技術陪",
                    "value": f"vt:{_MOBILE_EXBAR_KEY}:0",
                    "rule_key": _MOBILE_EXBAR_KEY,
                    "item": str(getattr(mobile_rule, "label", "絕巴技術陪")),
                    "quantity_unit": "計時",
                    "min_quantity": 1,
                    "max_quantity": 1,
                    "vip_timer": True,
                    "vip_timer_source_category": "delta_mobile_basic",
                    "vip_timer_service_type": "雙陪",
                    "vip_timer_spec_label": "絕巴技術陪",
                }
            )

        result: list[dict] = []
        for label in _GAME_ORDER:
            rows = regrouped[label]
            if rows:
                result.append({"label": label, "details": rows})
        return result

    flow._build_catalog_uncached = build_catalog_uncached
    flow._CATALOG_CACHE = None
    flow._CATALOG_CACHE_AT = 0.0
    flow._vip_timer_v5_policy_installed = True
    flow.refresh_vip_timer_self_service_catalog()


def _install_switch_catalog_policy() -> None:
    from services import vip_timer as timer

    if getattr(timer, "_vip_timer_v5_public_rules_installed", False):
        return
    original = timer.public_hourly_rules
    order_index = {category: index for index, category in enumerate(_GAME_LABELS)}

    def public_hourly_rules() -> list[dict]:
        rows: list[dict] = []
        for raw in original():
            row = dict(raw)
            category = str(row.get("category") or "")
            label = _GAME_LABELS.get(category)
            if not label:
                continue
            row["category_label"] = label
            rows.append(row)
        rows.sort(
            key=lambda row: (
                order_index.get(str(row.get("category") or ""), 99),
                str(row.get("label") or ""),
                str(row.get("rule_key") or ""),
            )
        )
        return rows

    timer.public_hourly_rules = public_hourly_rules
    timer._vip_timer_v5_public_rules_installed = True


def _is_vip_timer_snapshot(row: dict) -> bool:
    try:
        snapshot = json.loads(str(row.get("price_snapshot_json") or "{}"))
    except Exception:
        return False
    return isinstance(snapshot, dict) and bool(snapshot.get("vip_timer"))


def _install_loyalty_exclusion() -> None:
    from sqlalchemy import text
    from services import loyalty_benefits as loyalty

    if getattr(loyalty, "_vip_timer_exclusion_installed", False):
        return
    original_bucket = loyalty._loyalty_bucket_from_order
    original_process_closed_order = loyalty.process_closed_order

    def loyalty_bucket_from_order(row: dict):
        if _is_vip_timer_snapshot(row):
            return None
        return original_bucket(row)

    def process_closed_order(order_id: int):
        """Mark VIP timer orders processed without adding entertainment progress."""
        loyalty.ensure_loyalty_tables()
        with loyalty.engine.begin() as conn:
            existing = conn.execute(
                text(
                    "SELECT order_id FROM loyalty_order_events "
                    "WHERE order_id=:order_id LIMIT 1"
                ),
                {"order_id": int(order_id)},
            ).first()
            if existing is not None:
                return None

            row = conn.execute(
                text(
                    "SELECT id, customer_discord_id, status, price_snapshot_json, "
                    "ticket_channel_id FROM web_orders WHERE id=:order_id LIMIT 1"
                ),
                {"order_id": int(order_id)},
            ).mappings().first()
            data = dict(row) if row is not None else {}
            if (
                not data
                or str(data.get("status") or "").strip().lower() != "closed"
                or not _is_vip_timer_snapshot(data)
            ):
                data = {}
            else:
                conn.execute(
                    text(
                        "INSERT INTO loyalty_order_events ("
                        "order_id, customer_discord_id, scope_key, paid_units, "
                        "issued_coupon_count, processed_at, note"
                        ") VALUES ("
                        ":order_id, :customer_id, NULL, 0, 0, :processed_at, 'vip_timer_excluded'"
                        ")"
                    ),
                    {
                        "order_id": int(order_id),
                        "customer_id": str(data.get("customer_discord_id") or "").strip() or None,
                        "processed_at": loyalty.get_taipei_now_iso(),
                    },
                )

        if data:
            return {
                "order_id": int(order_id),
                "customer_id": str(data.get("customer_discord_id") or "").strip(),
                "ticket_channel_id": data.get("ticket_channel_id"),
                "paid_units": 0.0,
                "issued_coupon_count": 0,
                "issued_coupons": [],
                "note": "vip_timer_excluded",
            }
        return original_process_closed_order(int(order_id))

    loyalty._loyalty_bucket_from_order = loyalty_bucket_from_order
    loyalty.process_closed_order = process_closed_order
    loyalty._vip_timer_exclusion_installed = True


def _install_vip_benefit_text() -> None:
    from core import vip_levels

    key = "vip_timer"
    vip_levels.VIP_BENEFIT_ITEMS[key] = "・可使用 VIP 自由計時"
    for level in vip_levels.VIP_LEVELS:
        if int(level.get("threshold") or 0) < 6000:
            continue
        benefit_keys = level.setdefault("benefit_keys", [])
        if key not in benefit_keys:
            benefit_keys.append(key)
    vip_levels.VIP_LEVEL_BENEFITS.clear()
    vip_levels.VIP_LEVEL_BENEFITS.update(vip_levels.build_vip_level_benefits())


def install_vip_timer_policy_v5() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _install_mobile_exbar_rule()
    _install_catalog_guard_policy()
    _install_selector_policy()
    _install_switch_catalog_policy()
    _install_loyalty_exclusion()
    _install_vip_benefit_text()
    _INSTALLED = True


__all__ = [
    "install_vip_timer_policy_v5",
]