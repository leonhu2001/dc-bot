from __future__ import annotations


# 洗幣身分組沿用舊 ID；AW 使用新的獨立身分組。
# Legacy COIN_WASH_AW_* 仍可查到洗幣身分組，不能用來檢查 AW。
COIN_WASH_AW_RECEIVER_ROLE_ID = "1565369317929918554"
AW_COLLISION_RECEIVER_ROLE_ID = "1571080769407942787"
HALFCOIN_RECEIVER_ROLE_ID = COIN_WASH_AW_RECEIVER_ROLE_ID


def install_special_receiver_roles_20261103() -> None:
    """Install separate coin-wash and AW qualifications, idempotently.

    Existing tickets keep their rule keys and price snapshots. At the
    claim-time boundary, their current required roles are re-evaluated.
    """
    from services import order_rules

    ids = {
        order_rules.AW_COLLISION_RECEIVER_ROLE_KEY: AW_COLLISION_RECEIVER_ROLE_ID,
        order_rules.HALFCOIN_RECEIVER_ROLE_KEY: HALFCOIN_RECEIVER_ROLE_ID,
    }
    labels = {
        order_rules.AW_COLLISION_RECEIVER_ROLE_KEY: "AW",
        order_rules.HALFCOIN_RECEIVER_ROLE_KEY: "洗幣",
    }

    order_rules.AW_COLLISION_RECEIVER_ROLE_ID = AW_COLLISION_RECEIVER_ROLE_ID
    order_rules.HALFCOIN_RECEIVER_ROLE_ID = HALFCOIN_RECEIVER_ROLE_ID

    order_rules.SPECIAL_RECEIVER_ROLE_IDS_BY_KEY.clear()
    order_rules.SPECIAL_RECEIVER_ROLE_IDS_BY_KEY.update(ids)
    order_rules.SPECIAL_RECEIVER_ROLE_LABELS_BY_KEY.clear()
    order_rules.SPECIAL_RECEIVER_ROLE_LABELS_BY_KEY.update(labels)

    order_rules.ALL_ROLE_IDS.update(ids)
    order_rules.ALL_ROLE_LABELS.update(labels)


__all__ = [
    "COIN_WASH_AW_RECEIVER_ROLE_ID",
    "AW_COLLISION_RECEIVER_ROLE_ID",
    "HALFCOIN_RECEIVER_ROLE_ID",
    "install_special_receiver_roles_20261103",
]
