from __future__ import annotations

"""VIP monthly benefits with tier-only issuance policy.

The original implementation is preserved in ``vip_monthly_benefits_legacy`` so
old rows, migrations and reservation semantics stay compatible.  From this
policy version onward, monthly benefits are granted by the member's current VIP
tier only; the former trailing-30-day spend gate is disabled.  Per-order usage
minimums for the 200T / 500T cash vouchers are enforced in
``services.vip_monthly_order_discount`` and checkout validation instead.
"""

from services import vip_monthly_benefits_legacy as _legacy
from services.vip_monthly_benefits_legacy import *  # noqa: F401,F403


# The legacy synchronizer resolves activity through this dictionary at runtime.
# Empty thresholds keep the synchronizer, downgrade/revoke behavior and old data
# migration intact while removing the recent-spend requirement.
_legacy.VIP_MONTHLY_RECENT_SPEND_MINIMUM = {}
VIP_MONTHLY_RECENT_SPEND_MINIMUM = _legacy.VIP_MONTHLY_RECENT_SPEND_MINIMUM


def get_vip_monthly_recent_spend_minimum(level_name: str | None) -> int:
    _ = level_name
    return 0


# Patch the function used by the preserved synchronizer as well as the public
# export above.  This makes all code paths agree on the new tier-only policy.
_legacy.get_vip_monthly_recent_spend_minimum = get_vip_monthly_recent_spend_minimum
