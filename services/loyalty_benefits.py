from __future__ import annotations

"""Compatibility facade for loyalty coupons plus newer benefit sources.

The loyalty accumulation implementation is preserved in
``loyalty_benefits_legacy``.  This facade keeps every existing public function
while routing the shared checkout reservation lifecycle for three selector
namespaces: legacy loyalty, admin-issued benefits, and VIP monthly cash
benefits.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from core.time_utils import get_taipei_now_iso
from services import loyalty_benefits_legacy as _legacy
from services.loyalty_benefits_legacy import *  # noqa: F401,F403
from services.benefit_selector import (
    SOURCE_ISSUED,
    SOURCE_LOYALTY,
    SOURCE_VIP_MONTHLY,
    decode_benefit_selector_id,
)
from shared.db import engine


def _audit_issued_in_session(
    db: Session,
    *,
    action: str,
    benefit_id: int,
    customer_id: str,
    detail: dict[str, Any] | None = None,
) -> None:
    now = get_taipei_now_iso()
    try:
        db.execute(
            text(
                """
                INSERT INTO benefit_audit_log (
                    action, actor_id, template_id, benefit_id, customer_id,
                    detail_json, created_at
                ) VALUES (
                    :action, 'system:checkout', NULL, :benefit_id, :customer_id,
                    :detail_json, :created_at
                )
                """
            ),
            {
                "action": str(action),
                "benefit_id": int(benefit_id),
                "customer_id": str(customer_id),
                "detail_json": __import__("json").dumps(
                    detail or {}, ensure_ascii=False, sort_keys=True
                ),
                "created_at": now,
            },
        )
    except Exception:
        # Audit rows must never make a valid reservation fail. The core state
        # mutation below remains transactional with the order.
        pass


def reserve_coupon_in_session(
    db: Session,
    *,
    coupon_id: int,
    customer_id: str | int,
    order_id: int,
    rule_key: str,
    player_count: int = 1,
) -> None:
    source, real_id = decode_benefit_selector_id(coupon_id)
    if real_id is None:
        raise ValueError("缺少福利券編號。")

    if source == SOURCE_LOYALTY:
        return _legacy.reserve_coupon_in_session(
            db,
            coupon_id=int(real_id),
            customer_id=customer_id,
            order_id=int(order_id),
            rule_key=rule_key,
            player_count=player_count,
        )

    now = get_taipei_now_iso()
    customer = str(customer_id)

    if source == SOURCE_ISSUED:
        result = db.execute(
            text(
                """
                UPDATE issued_benefits
                SET status='reserved',
                    reserved_order_key=:order_key,
                    reserved_at=:now,
                    updated_at=:now
                WHERE id=:benefit_id
                  AND customer_id=:customer_id
                  AND status='available'
                  AND (expires_at IS NULL OR expires_at > :now)
                """
            ),
            {
                "order_key": str(int(order_id)),
                "now": now,
                "benefit_id": int(real_id),
                "customer_id": customer,
            },
        )
        if int(result.rowcount or 0) != 1:
            raise ValueError("這張福利券已被使用、保留或失效。")
        _audit_issued_in_session(
            db,
            action="reserve_benefit",
            benefit_id=int(real_id),
            customer_id=customer,
            detail={"order_key": str(int(order_id))},
        )
        return None

    if source == SOURCE_VIP_MONTHLY:
        marker = f"web_order:{int(order_id)}"
        result = db.execute(
            text(
                """
                UPDATE vip_monthly_benefits
                SET status='reserved',
                    reserved_at=:now,
                    reserved_channel_id=:marker,
                    updated_at=:now
                WHERE id=:benefit_id
                  AND customer_id=:customer_id
                  AND status='available'
                """
            ),
            {
                "now": now,
                "marker": marker,
                "benefit_id": int(real_id),
                "customer_id": customer,
            },
        )
        if int(result.rowcount or 0) != 1:
            raise ValueError("這張 VIP 月券已被使用、保留或失效。")
        return None

    raise ValueError("不支援的福利券來源。")


def reserve_coupon(
    coupon_id: int,
    *,
    customer_id: str | int,
    order_id: int,
    rule_key: str,
    player_count: int = 1,
) -> None:
    from shared.db import SessionLocal

    db = SessionLocal()
    try:
        reserve_coupon_in_session(
            db,
            coupon_id=int(coupon_id),
            customer_id=customer_id,
            order_id=int(order_id),
            rule_key=rule_key,
            player_count=player_count,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _release_extended_for_order(conn, order_id: int, now: str) -> int:
    released = 0
    try:
        result = conn.execute(
            text(
                """
                UPDATE issued_benefits
                SET status='available',
                    reserved_order_key=NULL,
                    reserved_at=NULL,
                    updated_at=:now
                WHERE status='reserved'
                  AND reserved_order_key=:order_key
                  AND (expires_at IS NULL OR expires_at > :now)
                """
            ),
            {"order_key": str(int(order_id)), "now": now},
        )
        released += int(result.rowcount or 0)
        # Expired while reserved: do not put it back into circulation.
        conn.execute(
            text(
                """
                UPDATE issued_benefits
                SET status='expired',
                    reserved_order_key=NULL,
                    reserved_at=NULL,
                    updated_at=:now
                WHERE status='reserved'
                  AND reserved_order_key=:order_key
                  AND expires_at IS NOT NULL
                  AND expires_at <= :now
                """
            ),
            {"order_key": str(int(order_id)), "now": now},
        )
    except Exception:
        pass

    try:
        marker = f"web_order:{int(order_id)}"
        result = conn.execute(
            text(
                """
                UPDATE vip_monthly_benefits
                SET status='available',
                    reserved_at=NULL,
                    reserved_channel_id=NULL,
                    updated_at=:now
                WHERE status='reserved'
                  AND reserved_channel_id=:marker
                """
            ),
            {"marker": marker, "now": now},
        )
        released += int(result.rowcount or 0)
    except Exception:
        pass
    return released


def release_coupon_for_order(order_id: int) -> int:
    released = int(_legacy.release_coupon_for_order(int(order_id)) or 0)
    now = get_taipei_now_iso()
    with engine.begin() as conn:
        released += _release_extended_for_order(conn, int(order_id), now)
    return released


def _redeem_extended_for_order(conn, order_id: int, now: str) -> int:
    redeemed = 0
    order_key = str(int(order_id))
    try:
        rows = conn.execute(
            text(
                """
                SELECT id, customer_id, remaining_uses
                FROM issued_benefits
                WHERE status='reserved' AND reserved_order_key=:order_key
                """
            ),
            {"order_key": order_key},
        ).mappings().all()
        for row in rows:
            remaining_before = max(1, int(row.get("remaining_uses") or 1))
            remaining_after = remaining_before - 1
            next_status = "available" if remaining_after > 0 else "redeemed"
            conn.execute(
                text(
                    """
                    UPDATE issued_benefits
                    SET status=:status,
                        remaining_uses=:remaining,
                        reserved_order_key=NULL,
                        reserved_at=NULL,
                        redeemed_order_key=:redeemed_order_key,
                        redeemed_at=:redeemed_at,
                        updated_at=:now
                    WHERE id=:benefit_id AND status='reserved'
                    """
                ),
                {
                    "status": next_status,
                    "remaining": remaining_after,
                    "redeemed_order_key": order_key if remaining_after <= 0 else None,
                    "redeemed_at": now if remaining_after <= 0 else None,
                    "now": now,
                    "benefit_id": int(row["id"]),
                },
            )
            redeemed += 1
    except Exception:
        pass

    try:
        marker = f"web_order:{int(order_id)}"
        result = conn.execute(
            text(
                """
                UPDATE vip_monthly_benefits
                SET status='redeemed',
                    redeemed_at=:now,
                    reserved_at=NULL,
                    reserved_channel_id=NULL,
                    updated_at=:now
                WHERE status='reserved'
                  AND reserved_channel_id=:marker
                """
            ),
            {"marker": marker, "now": now},
        )
        redeemed += int(result.rowcount or 0)
    except Exception:
        pass
    return redeemed


def redeem_coupon_for_order(order_id: int) -> int:
    redeemed = int(_legacy.redeem_coupon_for_order(int(order_id)) or 0)
    now = get_taipei_now_iso()
    with engine.begin() as conn:
        redeemed += _redeem_extended_for_order(conn, int(order_id), now)
    return redeemed


def reconcile_reserved_coupons(limit: int = 200) -> dict[str, int]:
    base = _legacy.reconcile_reserved_coupons(limit=limit)
    released = int((base or {}).get("released") or 0)
    redeemed = int((base or {}).get("redeemed") or 0)

    candidates: dict[int, str] = {}
    try:
        with engine.connect() as conn:
            issued_rows = conn.execute(
                text(
                    """
                    SELECT CAST(i.reserved_order_key AS INTEGER) AS order_id,
                           LOWER(COALESCE(o.status, '')) AS order_status
                    FROM issued_benefits i
                    LEFT JOIN web_orders o
                      ON o.id = CAST(i.reserved_order_key AS INTEGER)
                    WHERE i.status='reserved'
                      AND i.reserved_order_key IS NOT NULL
                    ORDER BY i.id ASC
                    LIMIT :limit
                    """
                ),
                {"limit": max(1, int(limit or 200))},
            ).mappings().all()
            for row in issued_rows:
                if row.get("order_id"):
                    candidates[int(row["order_id"])] = str(row.get("order_status") or "")

            vip_rows = conn.execute(
                text(
                    """
                    SELECT CAST(SUBSTR(v.reserved_channel_id, 11) AS INTEGER) AS order_id,
                           LOWER(COALESCE(o.status, '')) AS order_status
                    FROM vip_monthly_benefits v
                    LEFT JOIN web_orders o
                      ON o.id = CAST(SUBSTR(v.reserved_channel_id, 11) AS INTEGER)
                    WHERE v.status='reserved'
                      AND v.reserved_channel_id LIKE 'web_order:%'
                    ORDER BY v.id ASC
                    LIMIT :limit
                    """
                ),
                {"limit": max(1, int(limit or 200))},
            ).mappings().all()
            for row in vip_rows:
                if row.get("order_id"):
                    candidates[int(row["order_id"])] = str(row.get("order_status") or "")
    except Exception:
        return {"released": released, "redeemed": redeemed}

    for order_id, status in candidates.items():
        if status == "closed":
            # Only count the extended rows here; legacy was already reconciled.
            now = get_taipei_now_iso()
            with engine.begin() as conn:
                redeemed += _redeem_extended_for_order(conn, order_id, now)
        elif status == "cancelled" or not status:
            now = get_taipei_now_iso()
            with engine.begin() as conn:
                released += _release_extended_for_order(conn, order_id, now)

    return {"released": released, "redeemed": redeemed}
