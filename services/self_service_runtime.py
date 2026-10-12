"""Stable import facade for the extracted legacy self-service runtime.

The implementation lives in ``self_service_runtime_legacy`` while existing
callers keep importing ``services.self_service_runtime``.  The module object is
replaced directly so configuration hooks, globals and monkeypatches retain the
same semantics during incremental extraction.

New self-service behavior belongs in focused services/views rather than the
legacy implementation.
"""

from __future__ import annotations

import sys

from services import self_service_runtime_legacy as _legacy


sys.modules[__name__] = _legacy
