"""Router package bootstrap hooks."""

# The website main module imports routers individually. Installing the VIP timer
# integration here lets the existing /order router keep ownership of the public
# storefront while adding one special category without duplicating the catalog.
from web.app.routers import site as _site
from web.app.routers import vip_timer as _vip_timer_module
from web.app.routers.vip_timer import install as _install_vip_timer
from web.app.routers.vip_timer_safety import install as _install_vip_timer_safety

_install_vip_timer(_site)
_install_vip_timer_safety(_vip_timer_module)

__all__ = []
