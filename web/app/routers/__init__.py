"""Router package bootstrap hooks."""

# The website main module imports routers individually. Installing the VIP timer
# integration here lets the existing /order router keep ownership of the public
# storefront while adding one special category without duplicating the catalog.
from services.vip_timer_catalog_guard import install_vip_timer_catalog_guard
from services.vip_timer_integrity import (
    cleanup_stale_vip_timer_rows,
    install_vip_timer_accounting_integrity_guard,
)
from services.vip_timer_lifecycle import install_vip_timer_lifecycle_guard
from services.vip_timer_ops import (
    ensure_vip_timer_ops_tables,
    install_vip_timer_snapshot_guard,
)
from services.vip_timer_pending_order_guard import install_web_pending_order_guard
from services.vip_timer_roster_payout import install_vip_timer_roster_payout
from web.app.services import accounting_reconciliation as _accounting_reconciliation

install_vip_timer_catalog_guard()
install_vip_timer_lifecycle_guard()
install_vip_timer_snapshot_guard()
ensure_vip_timer_ops_tables()
_stale_timer_order_ids = cleanup_stale_vip_timer_rows()
if _stale_timer_order_ids:
    print(
        "[vip-timer-integrity] removed stale timer metadata for order_ids="
        + ",".join(str(order_id) for order_id in _stale_timer_order_ids),
        flush=True,
    )
_generic_payout_checker = _accounting_reconciliation._check_payouts
install_vip_timer_roster_payout()
install_vip_timer_accounting_integrity_guard(_generic_payout_checker)
# Patch the canonical public-order creation service before any request handler
# imports it locally. A pending VIP timer payment blocks every new website order.
install_web_pending_order_guard()

from services import vip_timer as _timer_service
from web.app.routers import site as _site
from web.app.routers import vip_timer as _vip_timer_module
from web.app.routers.vip_timer import install as _install_vip_timer
from web.app.routers.vip_timer_safety import install as _install_vip_timer_safety
from web.app.routers.vip_timer_ops import router as _vip_timer_ops_router
from web.app.routers.member_vip_timer import (
    install as _install_member_vip_timer,
    router as _member_vip_timer_router,
)

# vip_timer.py imports create_vip_timer_session by name. Rebind it after the
# snapshot guard so website-created timers lock the VIP tier at order creation.
_vip_timer_module.create_vip_timer_session = _timer_service.create_vip_timer_session

_install_vip_timer(_site)
# VIP timer remains fully functional, but its storefront exposure is restricted
# to the authenticated member area after the base integration is installed.
_install_member_vip_timer(_site)
_install_vip_timer_safety(_vip_timer_module)
_site.router.include_router(_vip_timer_ops_router)
_site.router.include_router(_member_vip_timer_router)

# Finance Center used the raw reconciliation count while System Operations used
# the policy-aware view, so historical/known-safe differences could show as a red
# number in one page while the maintenance page correctly said everything was
# normal. Rebind only the Finance Center's imported builder so both surfaces use
# the same policy without changing low-level reconciliation diagnostics.
from web.app.routers import admin_centers as _admin_centers
from web.app.services.accounting_reconciliation_policy import (
    build_policy_aware_accounting_reconciliation_snapshot as _build_policy_aware_accounting_reconciliation_snapshot,
)

_admin_centers.build_accounting_reconciliation_snapshot = (
    _build_policy_aware_accounting_reconciliation_snapshot
)

# Payroll totals and business performance are separate ledgers. Internal payroll
# transfers may move salary between employees but must never move the underlying
# companion performance. The same policy also merges dual-role staff into one row
# and normalizes all visible role labels to 陪玩 / 客服.
from web.app.services.payout_summary_policy import install_payout_summary_policy

install_payout_summary_policy()

# APEX used to price new orders by the customer's current rank. Those legacy
# rule keys must remain resolvable for historical orders, but they are not live
# products and must not appear as editable/on-shelf items in 商品與規則.
from web.app.routers import admin_order_rules as _admin_order_rules
from web.app.services.admin_order_rules_policy import (
    install_admin_order_rules_policy as _install_admin_order_rules_policy,
)

_install_admin_order_rules_policy(_admin_order_rules)

# Roulette identity must follow the live product catalog. The original module
# accidentally hard-coded a 2026-10-07 historical fun-order key (說都不會話),
# which made that old order appear in roulette operations. Install the identity
# correction before the roulette router imports its service functions by name.
from web.app.services.roulette_identity_policy import (
    install_roulette_identity_policy as _install_roulette_identity_policy,
)

_install_roulette_identity_policy()

# Lottery operations belong to the shared admin shell. Mount the small admin
# router through site.router so main.py does not need another bootstrap import.
from web.app.routers.admin_lottery import router as _admin_lottery_router

_site.router.include_router(_admin_lottery_router)

# Reviews are implemented in their own admin router. Mount them through the same
# shared site router so /admin/reviews/ is registered before main.py includes it.
from web.app.routers.admin_reviews import router as _admin_reviews_router

_site.router.include_router(_admin_reviews_router)

# Benefits must be issuable to every real member in the Discord guild, including
# people who have never placed an order. Keep the existing order-derived picker
# only as a temporary fallback if Discord's member endpoint is unavailable.
from web.app.routers import admin_benefits as _admin_benefits
from web.app.services.benefit_member_source import (
    install_benefit_member_source as _install_benefit_member_source,
)

_install_benefit_member_source(_admin_benefits)

__all__ = []