"""Web-service package initialization.

Keep public checkout copy aligned with the shared pricing rules applied by the
root services package and install the centralized promotion-benefit adapter.
"""

from __future__ import annotations

import services.order_rules as _order_rules_module

from . import order_groups as _order_groups
from . import staff_service as _staff_service
from .order_catalog_read_cache import (
    install_order_catalog_read_cache as _install_order_catalog_read_cache,
)
from .public_staff_refresh import (
    install_nonblocking_public_staff_refresh as _install_public_staff_refresh,
)


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

# Built-in rule identity now comes directly from services/order_rules.py.

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
