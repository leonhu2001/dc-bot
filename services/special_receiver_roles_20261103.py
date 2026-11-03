from __future__ import annotations


AW_COLLISION_RECEIVER_ROLE_ID = "1565369317929918554"
HALFCOIN_RECEIVER_ROLE_ID = "1565369029005287595"


def install_special_receiver_roles_20261103() -> None:
    """Install the only active special receiver roles.

    The retired AW role is intentionally not preserved as an alias or fallback.
    AW collision and halfcoin each resolve to exactly one current Discord role.
    """
    from services import order_rules

    current_ids = {
        order_rules.AW_COLLISION_RECEIVER_ROLE_KEY: AW_COLLISION_RECEIVER_ROLE_ID,
        order_rules.HALFCOIN_RECEIVER_ROLE_KEY: HALFCOIN_RECEIVER_ROLE_ID,
    }

    order_rules.AW_COLLISION_RECEIVER_ROLE_ID = AW_COLLISION_RECEIVER_ROLE_ID
    order_rules.HALFCOIN_RECEIVER_ROLE_ID = HALFCOIN_RECEIVER_ROLE_ID

    # Replace the special-role map instead of merging so retired aliases cannot
    # survive from an older import/runtime state.
    order_rules.SPECIAL_RECEIVER_ROLE_IDS_BY_KEY.clear()
    order_rules.SPECIAL_RECEIVER_ROLE_IDS_BY_KEY.update(current_ids)

    for role_key in tuple(order_rules.ALL_ROLE_IDS):
        if role_key in {
            order_rules.AW_COLLISION_RECEIVER_ROLE_KEY,
            order_rules.HALFCOIN_RECEIVER_ROLE_KEY,
        }:
            order_rules.ALL_ROLE_IDS.pop(role_key, None)
    order_rules.ALL_ROLE_IDS.update(current_ids)


__all__ = [
    "AW_COLLISION_RECEIVER_ROLE_ID",
    "HALFCOIN_RECEIVER_ROLE_ID",
    "install_special_receiver_roles_20261103",
]
