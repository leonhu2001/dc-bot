"""Router package bootstrap hooks."""

# The website main module imports routers individually. Installing the VIP timer
# integration here lets the existing /order router keep ownership of the public
# storefront while adding one special category without duplicating the catalog.
from services.vip_timer_catalog_guard import install_vip_timer_catalog_guard
from services.vip_timer_lifecycle import install_vip_timer_lifecycle_guard
from services.vip_timer_roster_payout import install_vip_timer_roster_payout
from web.app.routers import site as _site
from web.app.routers import vip_timer as _vip_timer_module
from web.app.routers.vip_timer import install as _install_vip_timer
from web.app.routers.vip_timer_safety import install as _install_vip_timer_safety

# Web order creation and the Discord runtime must use the same source-product,
# terminal-order and timer segment payout policies. Installing the payout guard
# in the web process prevents a later admin recalculation from flattening a
# mid-session replacement back into equal shares among only the final roster.
install_vip_timer_catalog_guard()
install_vip_timer_lifecycle_guard()
install_vip_timer_roster_payout()
_install_vip_timer(_site)
_install_vip_timer_safety(_vip_timer_module)

__all__ = []
