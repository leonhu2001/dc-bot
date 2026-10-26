"""Shared services package.

Current storefront business values live in services.order_rules, while Discord catalog
presentation metadata lives in services.orders. Importing this package validates the
final rule registry and installs the centralized benefit lifecycle integration.
"""

from . import order_rules as _order_rules


_order_rules.validate_rules()

# Keep the 2026-10-23 owner-approved game price list authoritative for both Web
# checkout and Discord self-service before any catalog presentation modules read it.
from .game_price_policy_20261023 import (
    install_game_price_policy_20261023 as _install_game_price_policy_20261023,
)

_install_game_price_policy_20261023()
_order_rules.validate_rules()

# Register system-owned catalog extensions before the remaining runtime wrappers are
# installed. The extension injects its rules before services.orders builds label maps,
# then adds the matching storefront groups for desktop and mobile Delta Force.
from .one_companion_one_guard_catalog import (
    install_one_companion_one_guard_catalog as _install_one_companion_one_guard_catalog,
)

_install_one_companion_one_guard_catalog()

# AW 代撞沿用台服代肝代解分類，但需要分段單價與 Modal 發數輸入，
# 因此集中由一個 system-owned extension 安裝，避免價格/UI 各自硬編碼。
from .aw_collision_catalog import install_aw_collision_catalog as _install_aw_collision_catalog

_install_aw_collision_catalog()

# AW is a pass-through service: no member/point discounts or specification,
# optional CSR internal pricing, and 100% of the payout basis to the worker.
from .aw_collision_business_policy import (
    install_aw_collision_business_policy as _install_aw_collision_business_policy,
)

_install_aw_collision_business_policy()

# The legacy Black Diamond monthly free-choice benefit has been retired. Install
# this before monthly-benefit integration so both Web and Discord read the same
# current entitlement source while historical benefit rows remain auditable.
from .retired_black_diamond_benefit import (
    install_retired_black_diamond_benefit_policy as _install_retired_black_diamond_benefit_policy,
)

_install_retired_black_diamond_benefit_policy()

# Owner-approved entertainment loyalty policy: hourly remains 10H -> 1H, while
# game-based entertainment is 15 games -> 1 game. The installer also reconciles
# existing stored game progress once after the new policy reaches production.
from .loyalty_policy_20261023 import (
    install_loyalty_policy_20261023 as _install_loyalty_policy_20261023,
)

_install_loyalty_policy_20261023()

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

# A VIP timer session row alone is not enough to redefine an order's accounting
# semantics. Install the shared identity/deletion guard for both Discord and Web
# processes so retracted timer metadata cannot later attach to a normal order ID.
from .vip_timer_integrity import (
    install_vip_timer_integrity_guard as _install_vip_timer_integrity_guard,
)

_install_vip_timer_integrity_guard()

# Keep the customer-service re-dispatch action on the original four-selector UI,
# while paid quick-order tickets use 訂單-... instead of staying 下單-....
from .order_ticket_ui_policy import (
    install_order_ticket_ui_policy as _install_order_ticket_ui_policy,
)

_install_order_ticket_ui_policy()
