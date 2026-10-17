from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from services import vip_monthly_benefits as vip
from services.vip_review_store import build_vip_review_snapshot


CASH_KEYS = (vip.MONTHLY_COUPON_200, vip.MONTHLY_COUPON_500)


def ensure_current_month_cash_entitlements(
    *,
    now: datetime | None = None,
    web_db: str | Path | None = None,
    bot_db: str | Path | None = None,
) -> dict[str, int]:
    """Issue/reactivate tier cash coupons without changing Black Diamond service gating."""
    current = vip._normalize_now(now)
    month = vip._month_key(current)
    now_text = current.isoformat(timespec="seconds")
    path = vip._web_db_path(web_db)
    vip.ensure_vip_monthly_tables(path)
    snapshot = build_vip_review_snapshot(
        db_file=vip._bot_db_path(bot_db),
        view="all",
        now=current,
    )
    issued = 0
    reactivated = 0
    revoked = 0
    tier_by_customer: dict[str, set[str]] = {}

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        for row in list(snapshot.get("rows") or []):
            customer_id = str(row.get("customer_id") or "").strip()
            if not customer_id:
                continue
            level_name = str(row.get("current_level") or "普通魔丸")
            tier_keys = vip._benefit_keys_for_level(level_name)
            tier_by_customer[customer_id] = tier_keys
            if bool(row.get("is_due")):
                continue

            for benefit_key in CASH_KEYS:
                if benefit_key not in tier_keys:
                    continue
                existing = conn.execute(
                    """SELECT id, status FROM vip_monthly_benefits
                       WHERE customer_id=? AND month_key=? AND benefit_key=? LIMIT 1""",
                    (customer_id, month, benefit_key),
                ).fetchone()
                if existing is None:
                    cur = conn.execute(
                        """INSERT INTO vip_monthly_benefits (
                               customer_id, month_key, benefit_key, benefit_label, status,
                               issued_at, updated_at, source
                           ) VALUES (?, ?, ?, ?, 'available', ?, ?, 'system')""",
                        (
                            customer_id,
                            month,
                            benefit_key,
                            vip.BENEFIT_LABELS[benefit_key],
                            now_text,
                            now_text,
                        ),
                    )
                    issued += int(cur.rowcount or 0)
                elif str(existing["status"] or "") == vip.REVOKED:
                    cur = conn.execute(
                        """UPDATE vip_monthly_benefits
                           SET status='available', choice_key=NULL, reserved_at=NULL,
                               reserved_channel_id=NULL, redeemed_at=NULL, updated_at=?
                           WHERE id=? AND status='revoked'""",
                        (now_text, int(existing["id"])),
                    )
                    reactivated += int(cur.rowcount or 0)

        rows = conn.execute(
            """SELECT id, customer_id, benefit_key FROM vip_monthly_benefits
               WHERE month_key=? AND status='available'
                 AND benefit_key IN (?, ?)""",
            (month, *CASH_KEYS),
        ).fetchall()
        for benefit in rows:
            customer_id = str(benefit["customer_id"] or "")
            if str(benefit["benefit_key"] or "") in tier_by_customer.get(customer_id, set()):
                continue
            cur = conn.execute(
                """UPDATE vip_monthly_benefits
                   SET status='revoked', choice_key=NULL, reserved_at=NULL,
                       reserved_channel_id=NULL, updated_at=?
                   WHERE id=? AND status='available'""",
                (now_text, int(benefit["id"])),
            )
            revoked += int(cur.rowcount or 0)
        conn.commit()

    return {"issued": issued, "reactivated": reactivated, "revoked": revoked}


def install_cash_entitlement_wrapper() -> None:
    if hasattr(vip, "_cash_policy_original_sync_current_month_vip_benefits"):
        return
    original = vip.sync_current_month_vip_benefits
    vip._cash_policy_original_sync_current_month_vip_benefits = original

    def wrapped(*args, **kwargs):
        result = original(*args, **kwargs)
        cash = ensure_current_month_cash_entitlements(
            now=kwargs.get("now"),
            web_db=kwargs.get("web_db"),
            bot_db=kwargs.get("bot_db"),
        )
        if isinstance(result, dict):
            result = dict(result)
            result["cash_policy"] = cash
        return result

    vip.sync_current_month_vip_benefits = wrapped
