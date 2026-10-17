"""Shared services package.

Current storefront business values live in services.order_rules, while Discord catalog
presentation metadata lives in services.orders. Importing this package validates the
final rule registry and installs the centralized benefit lifecycle integration.
"""

from . import order_rules as _order_rules


_order_rules.validate_rules()

# Keep coupon reservation / release / redemption and the VIP monthly entitlement
# policy centralized for both Discord and Web entry points.
from .benefit_runtime_integration import install_root_benefit_integrations as _install_benefits

_install_benefits()
