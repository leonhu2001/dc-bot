"""Shared services package.

Current storefront business values live in services.order_rules, while Discord catalog
presentation metadata lives in services.orders. Importing this package validates the
final rule registry and installs the centralized benefit lifecycle integration.
"""

from . import order_rules as _order_rules


_order_rules.validate_rules()

# Register system-owned catalog extensions before the remaining runtime wrappers are
# installed. The extension injects its rules before services.orders builds label maps,
# then adds the matching storefront groups for desktop and mobile Delta Force.
from .one_companion_one_guard_catalog import (
    install_one_companion_one_guard_catalog as _install_one_companion_one_guard_catalog,
)

_install_one_companion_one_guard_catalog()

# The legacy Black Diamond monthly free-choice benefit has been retired. Install
# this before monthly-benefit integration so both Web and Discord read the same
# current entitlement source while historical benefit rows remain auditable.
from .retired_black_diamond_benefit import (
    install_retired_black_diamond_benefit_policy as _install_retired_black_diamond_benefit_policy,
)

_install_retired_black_diamond_benefit_policy()

# Keep coupon reservation / release / redemption and the VIP monthly entitlement
# policy centralized for both Discord and Web entry points.
from .benefit_runtime_integration import install_root_benefit_integrations as _install_benefits

_install_benefits()

# User-facing checkout copy must describe the same funding policy as the actual
# payroll calculation. Install after benefit integration so wrappers see the
# final calculation/runtime hooks.
from .self_service_financial_copy import (
    install_self_service_financial_copy_policy as _install_financial_copy,
)

_install_financial_copy()
