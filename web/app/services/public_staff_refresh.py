from __future__ import annotations

import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any


_state_lock = threading.Lock()
_refresh_in_flight = False
_next_check_at = 0.0


def install_nonblocking_public_staff_refresh(staff_service: ModuleType) -> None:
    """Keep the public roster fresh without blocking a page request on Discord.

    The home page calls ``refresh_staff_members_if_stale`` during rendering.  A
    stale snapshot used to make that visitor wait while the whole Discord guild
    member list was downloaded, with a 30-second HTTP timeout per Discord page.
    This wrapper turns that maintenance call into a coalesced background refresh
    while the request continues using the last successful database snapshot.
    """
    original = staff_service.refresh_staff_members_if_stale

    if getattr(original, "_mw_nonblocking_public_refresh", False):
        return

    @wraps(original)
    def nonblocking_refresh(max_age_seconds: int = 60) -> dict[str, Any]:
        global _refresh_in_flight, _next_check_at

        threshold = max(10, int(max_age_seconds or 60))
        now = time.monotonic()

        with _state_lock:
            if _refresh_in_flight:
                return {
                    "refreshed": False,
                    "scheduled": False,
                    "in_flight": True,
                }

            if now < _next_check_at:
                return {
                    "refreshed": False,
                    "scheduled": False,
                }

            _refresh_in_flight = True
            # Do not let a traffic burst create one thread per request while the
            # worker is being started. The worker refines this after it checks DB.
            _next_check_at = now + threshold

        def run_refresh() -> None:
            global _refresh_in_flight, _next_check_at

            try:
                result = original(max_age_seconds=threshold)

                next_delay = threshold
                if isinstance(result, dict) and not result.get("refreshed"):
                    try:
                        age_seconds = max(0, int(result.get("age_seconds") or 0))
                    except (TypeError, ValueError):
                        age_seconds = 0

                    # If the DB snapshot was still fresh, wake up close to the
                    # exact time it becomes stale rather than waiting a full
                    # second interval again.
                    next_delay = max(10, threshold - age_seconds)

                with _state_lock:
                    _next_check_at = time.monotonic() + next_delay
            except Exception as exc:
                print(
                    "[public_staff_refresh] background refresh failed:",
                    repr(exc),
                    flush=True,
                )
                with _state_lock:
                    # Retry soon, but still avoid hammering Discord on every hit.
                    _next_check_at = time.monotonic() + 10
            finally:
                with _state_lock:
                    _refresh_in_flight = False

        threading.Thread(
            target=run_refresh,
            name="public-staff-refresh",
            daemon=True,
        ).start()

        return {
            "refreshed": False,
            "scheduled": True,
        }

    nonblocking_refresh._mw_nonblocking_public_refresh = True  # type: ignore[attr-defined]
    nonblocking_refresh._mw_sync_refresh = original  # type: ignore[attr-defined]
    staff_service.refresh_staff_members_if_stale = nonblocking_refresh


def clear_public_staff_refresh_state() -> None:
    global _refresh_in_flight, _next_check_at

    with _state_lock:
        _refresh_in_flight = False
        _next_check_at = 0.0
