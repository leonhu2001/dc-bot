from __future__ import annotations

from core.vip_levels import (
    VIP_BENEFIT_ITEMS,
    VIP_LEVELS,
    VIP_LEVEL_BENEFITS,
    build_vip_level_benefits,
)


RETIRED_BLACK_DIAMOND_BENEFIT_KEY = "free_secret_space"


def install_retired_black_diamond_benefit_policy() -> None:
    """Retire the legacy Black Diamond monthly free-choice benefit.

    Existing database rows remain available as historical records, but the
    benefit is removed from the current tier entitlement source. Monthly sync
    therefore cannot issue or reactivate it, and redemption checks no longer
    consider current Black Diamond members entitled to it.
    """

    VIP_BENEFIT_ITEMS.pop(RETIRED_BLACK_DIAMOND_BENEFIT_KEY, None)

    for level in VIP_LEVELS:
        if str(level.get("name") or "") != "黑鑽魔丸":
            continue
        level["benefit_keys"] = [
            str(key)
            for key in level.get("benefit_keys", [])
            if str(key) != RETIRED_BLACK_DIAMOND_BENEFIT_KEY
        ]

    VIP_LEVEL_BENEFITS.clear()
    VIP_LEVEL_BENEFITS.update(build_vip_level_benefits())


__all__ = [
    "RETIRED_BLACK_DIAMOND_BENEFIT_KEY",
    "install_retired_black_diamond_benefit_policy",
]
