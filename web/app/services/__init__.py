"""Web-service package initialization.

Keep public checkout behavior aligned with the shared pricing rules applied by the
root services package while avoiding import-time rewrites of storefront catalog
metadata. GROUP_SPECS is authored directly in order_groups.py.
"""

from __future__ import annotations

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
