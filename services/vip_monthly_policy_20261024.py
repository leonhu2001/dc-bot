from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


_INSTALLED = False
_BLACK_DIAMOND_LEVEL = "黑鑽魔丸"
_BLACK_DIAMOND_MIN_SPEND = 8000


def _restore_canonical_entitlement() -> None:
    from core import vip_levels

    key = "free_secret_space"
    vip_levels.VIP_BENEFIT_ITEMS[key] = "・每月一次免費「機密航天保底1000w」或娛樂陪 2H"

    for level in vip_levels.VIP_LEVELS:
        if str(level.get("name") or "") != _BLACK_DIAMOND_LEVEL:
            continue
        benefits = level.setdefault("benefit_keys", [])
        if key not in benefits:
            benefits.append(key)

    vip_levels.VIP_LEVEL_BENEFITS.clear()
    vip_levels.VIP_LEVEL_BENEFITS.update(vip_levels.build_vip_level_benefits())


def _install_monthly_sync_policy() -> None:
    from services import vip_monthly_benefits as monthly

    if getattr(monthly, "_current_monthly_policy_20261024_installed", False):
        return

    # Cash monthly vouchers are tier entitlements. The recent-spend gate belongs
    # only to the Black Diamond free-choice benefit, not to the 200T/500T vouchers.
    monthly.VIP_MONTHLY_RECENT_SPEND_MINIMUM.clear()

    original_sync = monthly.sync_current_month_vip_benefits
    original_snapshot = monthly.get_customer_vip_monthly_snapshot

    def _black_activity(
        customer_id: str,
        *,
        now: datetime,
        bot_db: str | Path | None,
    ) -> dict[str, Any]:
        spend_map = monthly._recent_closed_spend_map(
            [str(customer_id)],
            now=now,
            bot_db=bot_db,
        )
        recent = max(0, int(spend_map.get(str(customer_id), 0) or 0))
        return {
            "recent_spend": recent,
            "required_spend": _BLACK_DIAMOND_MIN_SPEND,
            "eligible": recent >= _BLACK_DIAMOND_MIN_SPEND,
        }

    def sync_current_month_vip_benefits(
        *,
        now: datetime | None = None,
        web_db: str | Path | None = None,
        bot_db: str | Path | None = None,
    ) -> dict[str, Any]:
        current = monthly._normalize_now(now)
        result = original_sync(now=current, web_db=web_db, bot_db=bot_db)
        month = monthly._month_key(current)
        now_text = current.isoformat(timespec="seconds")

        snapshot = monthly.build_vip_review_snapshot(
            db_file=monthly._bot_db_path(bot_db),
            view="all",
            now=current,
        )
        member_rows = list(snapshot.get("rows") or [])
        black_customers = {
            str(row.get("customer_id") or "").strip(): dict(row)
            for row in member_rows
            if str(row.get("customer_id") or "").strip()
            and str(row.get("current_level") or "") == _BLACK_DIAMOND_LEVEL
        }
        spend_map = monthly._recent_closed_spend_map(
            list(black_customers),
            now=current,
            bot_db=bot_db,
        )

        path = monthly._web_db_path(web_db)
        monthly.ensure_vip_monthly_tables(path)
        extra_revoked = 0
        extra_reactivated = 0

        with sqlite3.connect(path, timeout=15) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, customer_id, status, issued_at
                FROM vip_monthly_benefits
                WHERE month_key=? AND benefit_key=?
                """,
                (month, monthly.BLACK_DIAMOND_CHOICE),
            ).fetchall()

            for benefit in rows:
                customer_id = str(benefit["customer_id"] or "").strip()
                member = black_customers.get(customer_id)
                status = str(benefit["status"] or "")
                eligible = bool(
                    member
                    and not bool(member.get("is_due"))
                    and int(spend_map.get(customer_id, 0) or 0) >= _BLACK_DIAMOND_MIN_SPEND
                )

                # Do not interrupt a benefit already reserved/redeemed. The gate
                # controls new/current availability; active historical use remains auditable.
                if status in {monthly.RESERVED, monthly.REDEEMED}:
                    continue

                if eligible and status == monthly.REVOKED:
                    cur = conn.execute(
                        """
                        UPDATE vip_monthly_benefits
                        SET status='available', choice_key=NULL, reserved_at=NULL,
                            reserved_channel_id=NULL, redeemed_at=NULL, updated_at=?
                        WHERE id=? AND status='revoked'
                        """,
                        (now_text, int(benefit["id"])),
                    )
                    extra_reactivated += int(cur.rowcount or 0)
                    continue

                if not eligible and status == monthly.AVAILABLE:
                    if monthly._issued_before_activity_policy(benefit["issued_at"]):
                        continue
                    cur = conn.execute(
                        """
                        UPDATE vip_monthly_benefits
                        SET status='revoked', choice_key=NULL, reserved_at=NULL,
                            reserved_channel_id=NULL, updated_at=?
                        WHERE id=? AND status='available'
                        """,
                        (now_text, int(benefit["id"])),
                    )
                    extra_revoked += int(cur.rowcount or 0)

            conn.commit()

        result = dict(result)
        result["revoked_count"] = int(result.get("revoked_count") or 0) + extra_revoked
        result["reactivated_count"] = int(result.get("reactivated_count") or 0) + extra_reactivated
        return result

    def get_customer_vip_monthly_snapshot(
        customer_id: str | int,
        *,
        now: datetime | None = None,
        web_db: str | Path | None = None,
        bot_db: str | Path | None = None,
        ensure_synced: bool = True,
    ) -> dict[str, Any]:
        current = monthly._normalize_now(now)
        result = original_snapshot(
            customer_id,
            now=current,
            web_db=web_db,
            bot_db=bot_db,
            ensure_synced=ensure_synced,
        )
        if str(result.get("current_level") or "") != _BLACK_DIAMOND_LEVEL:
            result["recent_spend_required"] = 0
            result["monthly_spend_eligible"] = True
            result["monthly_activity_policy_active"] = True
            return result

        activity = _black_activity(
            str(customer_id),
            now=current,
            bot_db=bot_db,
        )
        result["recent_spend"] = int(activity["recent_spend"])
        result["recent_spend_required"] = _BLACK_DIAMOND_MIN_SPEND
        result["monthly_spend_eligible"] = bool(activity["eligible"])
        result["monthly_activity_policy_active"] = True
        result["black_diamond_suspended"] = bool(
            result.get("black_diamond_entitled")
            and not activity["eligible"]
            and not result.get("black_diamond")
        )
        result["black_diamond_available"] = bool(
            activity["eligible"]
            and result.get("black_diamond")
            and str(result["black_diamond"].get("status") or "") == monthly.AVAILABLE
        )
        return result

    monthly.sync_current_month_vip_benefits = sync_current_month_vip_benefits
    monthly.get_customer_vip_monthly_snapshot = get_customer_vip_monthly_snapshot
    monthly._current_monthly_policy_20261024_installed = True


def install_vip_monthly_policy_20261024() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _restore_canonical_entitlement()
    _install_monthly_sync_policy()
    _INSTALLED = True


__all__ = ["install_vip_monthly_policy_20261024"]
