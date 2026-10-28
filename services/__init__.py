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

# 2026-10-28 entertainment companion split:
# - keep the existing single/double rules as unrestricted-gender variants,
# - add female/male single and double rules without splitting loyalty progress,
# - replace selectable service point rewards with seat-aware single/double rewards.
from .entertainment_companion_policy_20261028 import (
    install_entertainment_companion_policy_20261028 as _install_entertainment_companion_policy_20261028,
    install_point_service_financial_runtime_20261028 as _install_point_service_financial_runtime_20261028,
)

_install_entertainment_companion_policy_20261028()

# Shared companion-count policy:
# - third field is gameplay / companion type only,
# - companion count is selected independently,
# - explicit 1-4 price tables are used where prices are not safely linear,
# - service point rewards remain seat-aware and game categories can disable only
#   service-type point rewards without disabling the other point products.
from .multi_seat_order_policy_20261028 import (
    install_multi_seat_order_policy_20261028 as _install_multi_seat_order_policy_20261028,
)

_install_multi_seat_order_policy_20261028()
_order_rules.validate_rules()

# Old manager overrides can still carry the pre-migration fixed-single structural
# fields. Normalize only those structural fields on effective reads while retaining
# the manager's price/label/role/benefit settings.
from .multi_seat_effective_rule_runtime import (
    install_multi_seat_effective_rule_runtime as _install_multi_seat_effective_rule_runtime,
)

_install_multi_seat_effective_rule_runtime()

# Finish the independent companion-count migration for Delta technical and sweet
# orders. Historical single/double keys stay resolvable, but new self-service specs
# no longer duplicate headcount that already has its own selector.
from .companion_count_catalog_cleanup_20261028 import (
    install_companion_count_catalog_cleanup_20261028 as _install_companion_count_catalog_cleanup_20261028,
)

_install_companion_count_catalog_cleanup_20261028()
_order_rules.validate_rules()

# Sweet orders require the normal service/game qualification AND the dedicated
# 甜蜜陪 role. The same matcher feeds smart-dispatch reminders, specified-staff
# validation and final acceptance claims.
from .sweet_companion_policy_20261028 import (
    install_sweet_companion_policy_20261028 as _install_sweet_companion_policy_20261028,
)

_install_sweet_companion_policy_20261028()
_order_rules.validate_rules()

# Changing customer-facing companion choices must not delete historical selector
# values saved by already-created tickets/orders.
from .entertainment_companion_compat_20261028 import (
    install_entertainment_companion_selector_compat_20261028 as _install_entertainment_companion_selector_compat_20261028,
)

_install_entertainment_companion_selector_compat_20261028()

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

# Multi-companion point rewards extend every selected companion and therefore must
# fund every seat. The shared financial wrapper is seat-count generic (1-4).
_install_point_service_financial_runtime_20261028()

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

# Quick-order entry must explicitly confirm the customer read the order notice before
# the ticket is created. This policy intentionally does not change the ticket's
# original locked-service self-service layout.
from .quick_order_ticket_policy_20261028 import (
    install_quick_order_ticket_policy_20261028 as _install_quick_order_ticket_policy_20261028,
)

_install_quick_order_ticket_policy_20261028()

# Install the Discord shared player-count control after core benefit policies are
# ready. Importing this patches the UI class before bot.py imports self_service_runtime.
from .self_service_companion_count_runtime import (
    install_self_service_companion_count_runtime as _install_self_service_companion_count_runtime,
)

_install_self_service_companion_count_runtime()
