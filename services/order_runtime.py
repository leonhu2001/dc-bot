"""Stable import facade for the extracted legacy order runtime.

The implementation is intentionally isolated in ``order_runtime_legacy`` while
existing callers keep importing ``services.order_runtime``.  Replacing the
module object (rather than copying symbols with ``import *``) preserves runtime
monkeypatching/configuration semantics during the strangler refactor.

New order behavior must be added to focused services/views, not to the legacy
implementation.  Existing behavior can then be extracted incrementally behind
this stable import path.
"""

from __future__ import annotations

import sys

from services import order_runtime_legacy as _legacy


sys.modules[__name__] = _legacy
