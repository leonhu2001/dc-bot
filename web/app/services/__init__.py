"""Web-service package initialization.

Keep public checkout copy aligned with the shared pricing rules applied by the
root services package and install the centralized promotion-benefit adapter.
"""

from __future__ import annotations

from dataclasses import replace

import services.order_rules as _order_rules_module

from . import order_groups as _order_groups
from . import staff_service as _staff_service
from .order_catalog_read_cache import (
    install_order_catalog_read_cache as _install_order_catalog_read_cache,
)
from .public_staff_refresh import (
    install_nonblocking_public_staff_refresh as _install_public_staff_refresh,
)


def _catalog_group_for_admin(category: str, label: str) -> str:
    """Return the real second-column label without repeating the top-level game."""
    value = str(label or "").strip()
    prefixes = {
        "valorant": "特戰英豪｜",
        "lol": "英雄聯盟｜",
        "apex": "APEX｜",
    }
    prefix = prefixes.get(str(category or ""), "")
    if prefix and value.startswith(prefix):
        value = value[len(prefix):].strip()
    return value


def _install_builtin_catalog_columns() -> None:
    """Backfill code-defined rules with explicit second/third catalog columns.

    GROUP_SPECS is already the authoritative Web catalog definition: ``label`` is
    the second-level group and every variant tuple contains the third-level
    product label. Older code rules predate ``catalog_group_label`` and therefore
    stored both pieces inside ``OrderRule.label``. Normalize the immutable code
    defaults here so admin editing, previews and all Web consumers see the same
    two columns without guessing from legacy separators.
    """
    base_rules = getattr(_order_rules_module, "_BASE_ORDER_RULES", {})
    effective_rules = _order_rules_module.ORDER_RULES
    mapped_keys: set[str] = set()

    for spec in _order_groups.GROUP_SPECS:
        category = str(spec.get("category") or "").strip()
        group_label = _catalog_group_for_admin(category, spec.get("label") or "")
        if not group_label:
            continue

        for variant in spec.get("variants") or []:
            if not isinstance(variant, (list, tuple)) or len(variant) < 2:
                continue
            rule_key = str(variant[0] or "").strip()
            product_label = str(variant[1] or "").strip()
            if not rule_key or not product_label:
                continue

            base_rule = base_rules.get(rule_key)
            if base_rule is None:
                continue

            normalized = replace(
                base_rule,
                catalog_group_label=group_label,
                label=product_label,
            )
            base_rules[rule_key] = normalized
            if isinstance(effective_rules, dict) and dict.__contains__(effective_rules, rule_key):
                dict.__setitem__(effective_rules, rule_key, normalized)
            mapped_keys.add(rule_key)

    # Compatibility fallback for any built-in rule that has not yet been added
    # to GROUP_SPECS. This only handles the old unambiguous "第二欄｜第三欄"
    # storage shape and never swaps the two sides.
    for rule_key, base_rule in list(base_rules.items()):
        if rule_key in mapped_keys or str(base_rule.catalog_group_label or "").strip():
            continue
        legacy_label = str(base_rule.label or "").strip()
        if "｜" not in legacy_label:
            continue
        group_label, product_label = legacy_label.split("｜", 1)
        group_label = group_label.strip()
        product_label = product_label.strip()
        if not group_label or not product_label:
            continue

        normalized = replace(
            base_rule,
            catalog_group_label=group_label,
            label=product_label,
        )
        base_rules[rule_key] = normalized
        if isinstance(effective_rules, dict) and dict.__contains__(effective_rules, rule_key):
            dict.__setitem__(effective_rules, rule_key, normalized)


# Public storefront presentation uses a short shared snapshot/cache so normal
# navigation does not repeatedly rebuild the catalog or reopen SQLite. Pricing,
# checkout and formal order creation still revalidate against authoritative
# rules before any money-affecting action.
_install_order_catalog_read_cache(_order_groups)

# Public pages should never wait for a full Discord guild-member sync. The last
# successful DB snapshot is rendered immediately while stale data is refreshed
# by one coalesced background worker.
_install_public_staff_refresh(_staff_service)


for _spec in _order_groups.GROUP_SPECS:
    _category = str(_spec.get("category") or "")
    _key = str(_spec.get("key") or "")

    # Keep selector copy aligned with the new storefront prices / guarantees.
    if _key == "exbar_tech":
        _spec["description"] = (
            "絕巴技術陪服務。保底三選一："
            "800w / 500w + 2 沙色保險 / 4 沙色保險。"
        )
    elif _key == "bet":
        _spec["variants"] = [
            ("basic_bet_1000", "800w"),
            ("basic_bet_1500", "1000w"),
            ("basic_bet_2500", "1200w"),
        ]
    elif _key == "trial":
        _spec["variants"] = [
            ("basic_trial_500", "777w"),
            ("basic_trial_1000", "1688w"),
        ]

    _description = str(_spec.get("description") or "")
    if not _description:
        continue

    # Shared specify fee is now 100T.
    _description = _description.replace("+150T", "+100T")

    if _category == "valorant":
        _description = _description.replace(
            "2 局以上免指定費。",
            "NG 2 小時 / 積分 2 局以上免指定費。",
        )
    elif _category == "lol":
        if _key == "lol_entertain":
            _description = _description.replace(
                "2 小時 / 2 局以上免指定費。",
                "ARAM / NG 2 小時，積分 2 局以上免指定費。",
            )
        else:
            _description = _description.replace(
                "2 局以上免指定費。",
                "NG 2 小時 / 積分 2 局以上免指定費。",
            )

    _spec["description"] = _description


del _spec, _description, _category, _key

# Normalize code rules only after all storefront copy/variant adjustments above
# have finished, otherwise the admin page could inherit stale legacy labels.
_install_builtin_catalog_columns()

# Load the established checkout module once, then attach the promotion-benefit
# policy adapter. All public-order entry points import the same module object, so
# preview and formal-create revalidation cannot drift apart.
from .benefit_checkout_integration import (
    install_checkout_benefit_integration as _install_checkout_benefits,
)

_install_checkout_benefits()

# Point-benefit eligibility is shared with Discord. This removes the historical
# second Web-only deny-list so manager-published 商品與規則 settings are authoritative.
from .point_benefit_policy_bridge import (
    install_shared_point_benefit_policy as _install_shared_point_benefit_policy,
)

_install_shared_point_benefit_policy()
