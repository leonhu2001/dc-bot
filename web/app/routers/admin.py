"""Stable import facade for the extracted legacy admin router.

The existing admin implementation is isolated in ``admin_legacy``.  Keeping
this canonical module path as a facade lets the app and tests retain their
current imports while new admin features move into focused routers/services.
The module object is replaced directly so helper monkeypatching and router
identity remain unchanged.
"""

from __future__ import annotations

import sys

from web.app.routers import admin_legacy as _legacy


sys.modules[__name__] = _legacy
