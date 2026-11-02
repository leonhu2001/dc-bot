from __future__ import annotations

from dataclasses import replace

from services.order_rule_store import get_active_override, reset_rule_override


RULE_KEY = "fun_eat_yourself"
PUBLIC_LABEL = "一命通關"
LEGACY_LABEL = "想吃自己打"
PRICE = 13888
CATEGORY = "delta_desktop_fun"


def _reset_stale_override() -> None:
    active = get_active_override(RULE_KEY)
    if not active:
        return

    reset_rule_override(
        rule_key=RULE_KEY,
        actor_discord_id="system",
        actor_display_name="2026-11-02 一命通關規則校正",
        expected_active_version=int(active.get("version") or 0),
    )


def _patch_rule() -> None:
    from services import order_rules

    base = order_rules._BASE_ORDER_RULES.get(RULE_KEY)
    if base is None:
        base = order_rules.ORDER_RULES.get(RULE_KEY)
    if base is None:
        raise RuntimeError(f"missing canonical rule: {RULE_KEY}")

    corrected = replace(
        base,
        label=PUBLIC_LABEL,
        price=PRICE,
        catalog_group_label=PUBLIC_LABEL,
    )
    order_rules.validate_rule_definition(RULE_KEY, corrected)
    order_rules._BASE_ORDER_RULES[RULE_KEY] = corrected
    dict.__setitem__(order_rules.ORDER_RULES, RULE_KEY, corrected)
    order_rules.ORDER_RULES._custom_cache.pop(RULE_KEY, None)
    order_rules.ORDER_RULES._override_cache.pop(RULE_KEY, None)


def _patch_catalog() -> None:
    from services import orders

    groups = orders.SELF_SERVICE_ORDER_CATALOG.setdefault(CATEGORY, [])
    for group in groups:
        details = list(group.get("details") or ())
        if not any(str(item.get("rule_key") or "") == RULE_KEY for item in details):
            continue
        group["label"] = PUBLIC_LABEL
        for detail in details:
            if str(detail.get("rule_key") or "") == RULE_KEY:
                detail["label"] = PUBLIC_LABEL

    # New orders use the corrected name. Keep the old name only as a resolver alias
    # so unfinished historical orders can still be opened safely.
    orders.ORDER_RULE_KEY_BY_LABEL[PUBLIC_LABEL] = RULE_KEY
    orders.ORDER_RULE_KEY_BY_LABEL[LEGACY_LABEL] = RULE_KEY
    orders.ORDER_ITEM_TO_CATEGORY[PUBLIC_LABEL] = CATEGORY
    orders.ORDER_ITEM_TO_CATEGORY[LEGACY_LABEL] = CATEGORY

    current = orders.ORDER_ITEMS_BY_CATEGORY.setdefault(CATEGORY, [])
    current[:] = [PUBLIC_LABEL if item == LEGACY_LABEL else item for item in current]
    if PUBLIC_LABEL not in current:
        current.append(PUBLIC_LABEL)


def _patch_price_list() -> None:
    # Import here so the services package can finish installing the canonical rule
    # first. The price-list module is then cached with the corrected owner-approved
    # copy for every later Discord interaction.
    from services import quick_order_v2_price_lists as price_lists

    price_lists.DELTA_FUN_PRICE_LISTS["eat_yourself"] = {
        "label": PUBLIC_LABEL,
        "text": f"""**{PUBLIC_LABEL}**
{price_lists._aligned_code_block((("價格", "13888T"),))}
📌 **規則**
需連續撤離 **5 把**，且每把帶出價值皆須達 **1000W**，本方案無保底。

若中途撤離失敗，連撤進度歸零，需重新開始。
連撤期間若成功撤離但帶出未達 **1000W**，需補足場次；補場不會中斷既有連撤進度。
補場期間若撤離失敗，累計場次歸零。

🔴 **大紅可折抵 1 個場次**""",
    }


def install_delta_fun_one_life_clear_20261102() -> None:
    """Apply the owner-approved name, price and copy for 一命通關."""
    _reset_stale_override()
    _patch_rule()
    _patch_catalog()
    _patch_price_list()


__all__ = [
    "CATEGORY",
    "LEGACY_LABEL",
    "PRICE",
    "PUBLIC_LABEL",
    "RULE_KEY",
    "install_delta_fun_one_life_clear_20261102",
]
