from __future__ import annotations


# 內部／對外「幣號、代洗、AW 代撞」使用同一 Discord 接單身分組。
COIN_WASH_AW_RECEIVER_ROLE_ID = "1565369317929918554"
AW_COLLISION_RECEIVER_ROLE_ID = COIN_WASH_AW_RECEIVER_ROLE_ID
HALFCOIN_RECEIVER_ROLE_ID = COIN_WASH_AW_RECEIVER_ROLE_ID


def install_special_receiver_roles_20261103() -> None:
    """Install one shared role for coin wash and AW orders.

    Keep legacy rule keys for existing tickets, but do not revive retired IDs.
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
    "COIN_WASH_AW_RECEIVER_ROLE_ID",
    "AW_COLLISION_RECEIVER_ROLE_ID",
    "HALFCOIN_RECEIVER_ROLE_ID",
    "install_special_receiver_roles_20261103",
]
