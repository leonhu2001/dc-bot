from __future__ import annotations


AW_COLLISION_RECEIVER_ROLE_ID = "1565369317929918554"
HALFCOIN_RECEIVER_ROLE_ID = "1565369029005287595"


def install_aw_collision_business_policy() -> None:
    """Install the owner-approved special receiver role mapping.

    AW and HALFCOIN use distinct receiver roles.  Keep the canonical order-rules
    lookup tables synchronized because Discord dispatch resolves the role key to
    its concrete Discord role ID at runtime.
    """
    from services import order_rules

    order_rules.AW_COLLISION_RECEIVER_ROLE_ID = AW_COLLISION_RECEIVER_ROLE_ID
    order_rules.HALFCOIN_RECEIVER_ROLE_ID = HALFCOIN_RECEIVER_ROLE_ID

    order_rules.SPECIAL_RECEIVER_ROLE_IDS_BY_KEY[
        order_rules.AW_COLLISION_RECEIVER_ROLE_KEY
    ] = AW_COLLISION_RECEIVER_ROLE_ID
    order_rules.SPECIAL_RECEIVER_ROLE_IDS_BY_KEY[
        order_rules.HALFCOIN_RECEIVER_ROLE_KEY
    ] = HALFCOIN_RECEIVER_ROLE_ID

    order_rules.ALL_ROLE_IDS[
        order_rules.AW_COLLISION_RECEIVER_ROLE_KEY
    ] = AW_COLLISION_RECEIVER_ROLE_ID
    order_rules.ALL_ROLE_IDS[
        order_rules.HALFCOIN_RECEIVER_ROLE_KEY
    ] = HALFCOIN_RECEIVER_ROLE_ID


__all__ = [
    "AW_COLLISION_RECEIVER_ROLE_ID",
    "HALFCOIN_RECEIVER_ROLE_ID",
    "install_aw_collision_business_policy",
]
