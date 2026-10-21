"""Router package bootstrap hooks."""

# The website main module imports routers individually. Installing the VIP timer
# integration here lets the existing /order router keep ownership of the public
# storefront while adding one special category without duplicating the catalog.
from services.vip_timer_catalog_guard import install_vip_timer_catalog_guard
from services.vip_timer_lifecycle import install_vip_timer_lifecycle_guard
from services.vip_timer_ops import (
    ensure_vip_timer_ops_tables,
    install_vip_timer_snapshot_guard,
)
from services.vip_timer_roster_payout import install_vip_timer_roster_payout

install_vip_timer_catalog_guard()
install_vip_timer_lifecycle_guard()
install_vip_timer_snapshot_guard()
ensure_vip_timer_ops_tables()
install_vip_timer_roster_payout()

from services import vip_timer as _timer_service
from web.app.routers import site as _site
from web.app.routers import vip_timer as _vip_timer_module
from web.app.routers.vip_timer import install as _install_vip_timer
from web.app.routers.vip_timer_safety import install as _install_vip_timer_safety
from web.app.routers.vip_timer_ops import router as _vip_timer_ops_router

# vip_timer.py imports create_vip_timer_session by name. Rebind it after the
# snapshot guard so website-created timers lock the VIP tier at order creation.
_vip_timer_module.create_vip_timer_session = _timer_service.create_vip_timer_session

_install_vip_timer(_site)
_install_vip_timer_safety(_vip_timer_module)
_site.router.include_router(_vip_timer_ops_router)

__all__ = []
