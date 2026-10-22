from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
import json

from sqlalchemy import inspect, select, text

from shared.db import SessionLocal
from shared.models import (
    OrderAssignment,
    PayoutStatus,
    WebOrder,
    WorkerPayout,
    WorkerPayoutOverride,
)
from shared.payout import WORKER_BASE_PAYOUT_RATE, WORKER_NAMED_BONUS_RATE


_INSTALLED = False


def _is_timer_order(order_id: int, db) -> bool:
    # The web process installs the payout guard during router bootstrap, which
    # can happen before the raw vip_timer_* tables have been created. Ordinary
    # order payout recalculation must remain usable in that window.
    try:
        row = db.execute(
            text("SELECT 1 FROM vip_timer_sessions WHERE order_id=:order_id LIMIT 1"),
            {"order_id": int(order_id)},
        ).first()
    except Exception:
        return False
    return row is not None


def _staff_names(order_id: int, db) -> dict[str, str | None]:
    rows = db.execute(
        text(
            """
            SELECT staff_discord_id, staff_display_name
            FROM order_acceptance_claims
            WHERE order_id=:order_id
            ORDER BY id ASC
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all()
    result: dict[str, str | None] = {}
    for row in rows:
        worker_id = str(row.get("staff_discord_id") or "").strip()
        if worker_id:
            result[worker_id] = str(row.get("staff_display_name") or "").strip() or result.get(worker_id)
    return result


def _staff_role_types(order_id: int, db) -> dict[str, str]:
    """Return the best persisted service-role classification for timer staff."""
    rows = db.scalars(
        select(OrderAssignment)
        .where(OrderAssignment.order_id == int(order_id))
        .order_by(OrderAssignment.assigned_at.asc())
    ).all()
    result: dict[str, str] = {}
    for row in rows:
        worker_id = str(row.worker_discord_id or "").strip()
        if not worker_id:
            continue
        role_type = str(row.role_type or "booster").strip().lower()
        result[worker_id] = "companion" if role_type == "companion" else "booster"
    return result


def _legacy_static_roster_staff_ids(order_id: int, db) -> list[str]:
    """Recover a provably-static roster for early timer segments with no snapshot.

    Some early production timer rows can have billable seconds while
    ``staff_ids_json`` is still ``[]``. We only recover those rows when the
    persisted acceptance ledger proves the roster stayed static: there must be
    active claims, no inactive historical claims, and no timer roster-change
    event. If assignments already exist, they must name the same workers.

    Any ambiguity fails closed so a changed roster can never be guessed during
    accounting reconciliation or safe repair.
    """
    try:
        event_row = db.execute(
            text(
                """
                SELECT 1
                FROM vip_timer_events
                WHERE order_id=:order_id
                  AND action IN ('roster_change', 'resume_after_roster_change')
                LIMIT 1
                """
            ),
            {"order_id": int(order_id)},
        ).first()
    except Exception:
        return []
    if event_row is not None:
        return []

    try:
        claim_columns = {
            str(column.get("name") or "")
            for column in inspect(db.get_bind()).get_columns("order_acceptance_claims")
        }
    except Exception:
        return []
    if "is_active" not in claim_columns:
        return []

    try:
        claim_rows = db.execute(
            text(
                """
                SELECT staff_discord_id, is_active
                FROM order_acceptance_claims
                WHERE order_id=:order_id
                ORDER BY id ASC
                """
            ),
            {"order_id": int(order_id)},
        ).mappings().all()
    except Exception:
        return []

    if not claim_rows or any(int(row.get("is_active") or 0) != 1 for row in claim_rows):
        return []

    staff_ids: list[str] = []
    for row in claim_rows:
        worker_id = str(row.get("staff_discord_id") or "").strip()
        if worker_id and worker_id not in staff_ids:
            staff_ids.append(worker_id)
    if not staff_ids:
        return []

    assignment_ids = {
        str(row.worker_discord_id or "").strip()
        for row in db.scalars(
            select(OrderAssignment).where(OrderAssignment.order_id == int(order_id))
        ).all()
        if str(row.worker_discord_id or "").strip()
    }
    if assignment_ids and assignment_ids != set(staff_ids):
        return []

    return staff_ids


def _raw_worker_shares(order_id: int, db) -> dict[str, Decimal]:
    # Early VIP-timer installations (and historical test fixtures) predate the
    # rule_key column. Keep those ledgers readable: without a rule key they use
    # the original equal-per-staff split, while current ledgers can still apply
    # rule-aware weighting such as one-companion-one-guard.
    try:
        segment_columns = {
            str(column.get("name") or "")
            for column in inspect(db.get_bind()).get_columns("vip_timer_segments")
        }
    except Exception:
        segment_columns = set()
    rule_key_select = "rule_key" if "rule_key" in segment_columns else "'' AS rule_key"

    rows = db.execute(
        text(
            f"""
            SELECT {rule_key_select}, hourly_rate, billable_seconds, staff_ids_json
            FROM vip_timer_segments
            WHERE order_id=:order_id
              AND billable_seconds > 0
            ORDER BY seq ASC
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all()
    shares: dict[str, Decimal] = defaultdict(Decimal)
    role_types = _staff_role_types(int(order_id), db)
    legacy_static_roster: list[str] | None = None

    from services.one_companion_one_guard_payout import (
        allocate_decimal_gross_shares,
    )

    for row in rows:
        try:
            staff = json.loads(str(row.get("staff_ids_json") or "[]"))
        except Exception:
            staff = []
        unique: list[str] = []
        for value in staff if isinstance(staff, list) else []:
            worker_id = str(value or "").strip()
            if worker_id and worker_id not in unique:
                unique.append(worker_id)
        if not unique:
            if legacy_static_roster is None:
                legacy_static_roster = _legacy_static_roster_staff_ids(int(order_id), db)
            unique = list(legacy_static_roster)
        if not unique:
            continue
        seconds = max(0, int(row.get("billable_seconds") or 0))
        rate = max(0, int(row.get("hourly_rate") or 0))
        segment_gross = Decimal(rate) * Decimal(seconds) / Decimal(3600)

        weighted = allocate_decimal_gross_shares(
            str(row.get("rule_key") or ""),
            [
                (worker_id, role_types.get(worker_id, "booster"))
                for worker_id in unique
            ],
            segment_gross,
        )
        if weighted is not None:
            for worker_id, amount in weighted.items():
                shares[worker_id] += amount
            continue

        per_worker = segment_gross / Decimal(len(unique))
        for worker_id in unique:
            shares[worker_id] += per_worker
    return dict(shares)


def _allocate_integer_shares(raw: dict[str, Decimal], target_total: int) -> dict[str, int]:
    target = max(0, int(target_total or 0))
    if target <= 0 or not raw:
        return {worker_id: 0 for worker_id in raw}
    raw_total = sum(raw.values(), Decimal(0))
    if raw_total <= 0:
        return {worker_id: 0 for worker_id in raw}

    exact = {worker_id: Decimal(target) * amount / raw_total for worker_id, amount in raw.items()}
    allocated = {
        worker_id: int(value.to_integral_value(rounding=ROUND_FLOOR))
        for worker_id, value in exact.items()
    }
    remainder = target - sum(allocated.values())
    order = sorted(
        exact,
        key=lambda worker_id: (
            -(exact[worker_id] - Decimal(allocated[worker_id])),
            worker_id,
        ),
    )
    for worker_id in order[:remainder]:
        allocated[worker_id] += 1
    return allocated


def _worker_payout_plan(db, order: WebOrder) -> dict[str, dict[str, int | float | bool | str]]:
    """Build the authoritative VIP timer worker payout plan without writing rows."""
    payout_base = max(
        0,
        int(order.payout_base_amount if order.payout_base_amount is not None else order.amount or 0),
    )
    raw = _raw_worker_shares(int(order.id), db)
    shares = _allocate_integer_shares(raw, payout_base)
    if not shares:
        return {}

    overrides = {
        str(row.worker_discord_id): row
        for row in db.scalars(
            select(WorkerPayoutOverride).where(WorkerPayoutOverride.order_id == int(order.id))
        ).all()
    }

    plan: dict[str, dict[str, int | float | bool | str]] = {}
    for worker_id in sorted(shares):
        gross_share = int(shares[worker_id])
        base_payout = int(gross_share * WORKER_BASE_PAYOUT_RATE)
        final_payout = base_payout
        note = "VIP 自由計時｜依各計時區段實際參與人員與單型分潤基準分帳"
        override = overrides.get(worker_id)
        if override is not None:
            final_payout = max(0, int(override.manual_final_payout or 0))
            reason = str(override.reason or "人工覆寫")
            note = f"{note}｜人工覆寫：{reason}"
        plan[worker_id] = {
            "gross_share": gross_share,
            "base_rate": float(WORKER_BASE_PAYOUT_RATE),
            "base_payout": base_payout,
            "named_bonus_rate": float(WORKER_NAMED_BONUS_RATE),
            "named_bonus_amount": 0,
            "has_named_bonus": False,
            "final_payout": final_payout,
            "note": note,
        }
    return plan


def get_vip_timer_worker_payout_plan(order_id: int) -> dict[str, dict[str, int | float | bool | str]]:
    """Return the persisted-ledger payout expectation used by settlement and auditing."""
    db = SessionLocal()
    try:
        if not _is_timer_order(int(order_id), db):
            return {}
        order = db.get(WebOrder, int(order_id))
        if order is None:
            return {}
        return _worker_payout_plan(db, order)
    finally:
        db.close()


def _rewrite_worker_payouts(db, order: WebOrder) -> int:
    plan = _worker_payout_plan(db, order)
    if not plan:
        return 0

    names = _staff_names(int(order.id), db)
    existing_assignments = {
        str(row.worker_discord_id): row
        for row in db.scalars(
            select(OrderAssignment).where(OrderAssignment.order_id == int(order.id))
        ).all()
    }
    for worker_id in plan:
        if worker_id not in existing_assignments:
            db.add(
                OrderAssignment(
                    order_id=int(order.id),
                    worker_discord_id=worker_id,
                    worker_display_name=names.get(worker_id),
                    role_type="booster",
                    is_active=False,
                    has_named_bonus=False,
                    removed_at=datetime.now(),
                )
            )

    db.query(WorkerPayout).filter(WorkerPayout.order_id == int(order.id)).delete(synchronize_session=False)
    for worker_id, item in plan.items():
        db.add(
            WorkerPayout(
                order_id=int(order.id),
                worker_discord_id=worker_id,
                worker_display_name=names.get(worker_id),
                gross_share=int(item["gross_share"]),
                base_rate=float(item["base_rate"]),
                base_payout=int(item["base_payout"]),
                named_bonus_rate=float(item["named_bonus_rate"]),
                named_bonus_amount=int(item["named_bonus_amount"]),
                has_named_bonus=bool(item["has_named_bonus"]),
                final_payout=int(item["final_payout"]),
                payout_status=PayoutStatus.UNPAID.value,
                note=str(item["note"]),
            )
        )
    return len(plan)


def _install_accounting_integrations(recalculate_with_timer_ledger) -> None:
    """Make reconciliation and safe repair use the same timer-ledger payout plan."""
    try:
        from web.app.services import accounting_reconciliation as reconciliation
        from web.app.services import accounting_repair as repair
    except Exception:
        # Bot-only processes do not import the web accounting stack.
        return

    # accounting_repair imports the order-service function by value. Replace that
    # captured reference so "安全修復" cannot bypass the timer-aware wrapper.
    repair.recalculate_order_payouts = recalculate_with_timer_ledger

    original_validate = repair._validate_recalculate_unpaid_payouts

    def validate_recalculate_unpaid_payouts(db, order):
        if not _is_timer_order(int(order.id), db):
            return original_validate(db, order)

        status = str(order.status or "").strip().lower()
        if status not in {"active", "stored", "closed"}:
            raise ValueError("只有 active / stored / closed 訂單可以重算未發放分潤。")

        plan = _worker_payout_plan(db, order)
        if not plan:
            raise ValueError("這張 VIP 計時單沒有可結算的歷史計時人員，不能自動重算分潤。")

        payout_base = int(
            getattr(order, "payout_base_amount", None)
            or getattr(order, "amount", 0)
            or 0
        )
        if payout_base <= 0:
            raise ValueError("這張訂單的分潤計算基礎金額不是正數，需人工確認。")

        cs_id = str(getattr(order, "customer_service_discord_id", None) or "").strip()
        if not cs_id or cs_id == "demo_customer_service":
            raise ValueError("這張訂單缺少真實客服 Discord ID，不能自動重算。")

        worker_rows, cs_rows = repair._load_payout_rows(db, int(order.id))
        if not repair._all_rows_unpaid_and_clear([*worker_rows, *cs_rows]):
            raise ValueError(
                "這張訂單已有 paid、void、未知狀態或 paid_at 資料，禁止自動重算分潤。"
            )

    repair._validate_recalculate_unpaid_payouts = validate_recalculate_unpaid_payouts

    original_check = reconciliation._check_payouts
    worker_issue_codes = {
        "worker_payout_missing",
        "worker_payout_duplicate",
        "worker_payout_amount_mismatch",
        "worker_payout_without_assignment",
    }

    def check_payouts_with_timer_ledger(web, issues):
        start = len(issues)
        original_check(web, issues)

        try:
            timer_rows = web.execute(
                """
                SELECT s.order_id
                FROM vip_timer_sessions AS s
                JOIN web_orders AS o ON o.id = s.order_id
                WHERE LOWER(COALESCE(o.status, '')) = 'closed'
                """
            ).fetchall()
        except Exception:
            return

        timer_order_ids = {int(row[0]) for row in timer_rows}
        if not timer_order_ids:
            return

        # Remove only the generic worker checks for timer orders. Customer-service
        # checks and every non-timer issue remain untouched; timer worker checks are
        # rebuilt immediately below from the persisted segment ledger.
        preserved = issues[:start]
        for issue in issues[start:]:
            if (
                int(issue.get("order_id") or 0) in timer_order_ids
                and str(issue.get("code") or "") in worker_issue_codes
            ):
                continue
            preserved.append(issue)
        issues[:] = preserved

        db = SessionLocal()
        try:
            for order_id in sorted(timer_order_ids):
                order = db.get(WebOrder, int(order_id))
                if order is None or not _is_timer_order(int(order_id), db):
                    continue

                expected_plan = _worker_payout_plan(db, order)
                expected_by_worker = {
                    worker_id: float(item["final_payout"])
                    for worker_id, item in expected_plan.items()
                }
                worker_ids = list(expected_by_worker)

                worker_payouts = [
                    dict(row)
                    for row in web.execute(
                        """
                        SELECT
                            id,
                            worker_discord_id,
                            final_payout,
                            payout_status,
                            paid_at
                        FROM worker_payouts
                        WHERE order_id = ?
                        ORDER BY id ASC
                        """,
                        (int(order_id),),
                    ).fetchall()
                ]
                cs_payouts = [
                    dict(row)
                    for row in web.execute(
                        """
                        SELECT
                            id,
                            customer_service_discord_id,
                            payout_amount,
                            payout_status,
                            paid_at
                        FROM customer_service_payouts
                        WHERE order_id = ?
                        ORDER BY id ASC
                        """,
                        (int(order_id),),
                    ).fetchall()
                ]

                payout_base = max(
                    0,
                    int(
                        order.payout_base_amount
                        if order.payout_base_amount is not None
                        else order.amount or 0
                    ),
                )
                historical_locked = reconciliation._payout_rows_are_historical_locked(
                    worker_payouts,
                    cs_payouts,
                )
                repair_block_reason = reconciliation._payout_repair_block_reason(
                    worker_ids=worker_ids,
                    payout_base=payout_base,
                    customer_service_discord_id=str(
                        order.customer_service_discord_id or ""
                    ).strip(),
                    worker_payouts=worker_payouts,
                    cs_payouts=cs_payouts,
                )
                repair_action = (
                    "recalculate_unpaid_payouts"
                    if repair_block_reason is None
                    else None
                )
                reference = str(order.bot_order_no or "").strip() or f"WEB-{int(order_id)}"

                actual_by_worker: dict[str, list[dict]] = defaultdict(list)
                for payout in worker_payouts:
                    actual_by_worker[
                        str(payout.get("worker_discord_id") or "").strip()
                    ].append(payout)

                for worker_id, expected_amount in expected_by_worker.items():
                    actual_rows = actual_by_worker.get(worker_id, [])
                    if not actual_rows:
                        reconciliation._issue(
                            issues,
                            category="payout",
                            code="worker_payout_missing",
                            severity="critical",
                            reference=reference,
                            title="接單人員缺少分潤資料",
                            detail=(
                                f"worker {worker_id} 有 VIP 計時區段紀錄，"
                                "但沒有 worker_payout。"
                            ),
                            expected=expected_amount,
                            actual=None,
                            order_id=int(order_id),
                            repair_action=repair_action,
                            repair_block_reason=repair_block_reason,
                        )
                        continue

                    if len(actual_rows) > 1:
                        reconciliation._issue(
                            issues,
                            category="payout",
                            code="worker_payout_duplicate",
                            severity="critical",
                            reference=reference,
                            title="同一接單人員有重複分潤資料",
                            detail=(
                                f"worker {worker_id} 在同一 VIP 計時訂單共有 "
                                f"{len(actual_rows)} 筆 worker_payout。"
                            ),
                            expected=1,
                            actual=len(actual_rows),
                            order_id=int(order_id),
                            repair_action=repair_action,
                            repair_block_reason=repair_block_reason,
                        )

                    actual_amount = float(actual_rows[0].get("final_payout") or 0)
                    if (
                        not historical_locked
                        and not reconciliation._money_equal(
                            expected_amount,
                            actual_amount,
                        )
                    ):
                        reconciliation._issue(
                            issues,
                            category="payout",
                            code="worker_payout_amount_mismatch",
                            severity="critical",
                            reference=reference,
                            title="接單人員分潤金額不一致",
                            detail=(
                                f"worker {worker_id} 的分潤與 VIP 計時區段歷史紀錄"
                                "重算結果不同。"
                            ),
                            expected=expected_amount,
                            actual=actual_amount,
                            order_id=int(order_id),
                            repair_action=repair_action,
                            repair_block_reason=repair_block_reason,
                        )

                for worker_id, actual_rows in actual_by_worker.items():
                    if worker_id not in expected_by_worker and not historical_locked:
                        reconciliation._issue(
                            issues,
                            category="payout",
                            code="worker_payout_without_assignment",
                            severity="critical",
                            reference=reference,
                            title="分潤存在但沒有對應 VIP 計時紀錄",
                            detail=(
                                f"worker {worker_id} 有 worker_payout，"
                                "但不在任何可計費 VIP 計時區段。"
                            ),
                            expected=None,
                            actual=sum(
                                float(row.get("final_payout") or 0)
                                for row in actual_rows
                            ),
                            order_id=int(order_id),
                            repair_action=repair_action,
                            repair_block_reason=repair_block_reason,
                        )
        finally:
            db.close()

    reconciliation._check_payouts = check_payouts_with_timer_ledger


def recalculate_vip_timer_worker_payouts(order_id: int) -> int:
    db = SessionLocal()
    try:
        if not _is_timer_order(int(order_id), db):
            return 0
        order = db.get(WebOrder, int(order_id))
        if order is None:
            return 0
        count = _rewrite_worker_payouts(db, order)
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def install_vip_timer_roster_payout() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from shared import order_acceptance as acceptance
    from web.app.services import order_service

    original_promote = acceptance.promote_acceptance_claims_to_assignments
    original_recalculate = order_service.recalculate_order_payouts

    def recalculate_with_timer_ledger(db, order_id: int):
        result = original_recalculate(db, int(order_id))

        # SessionLocal has autoflush disabled. The generic recalculation above
        # creates replacement WorkerPayout rows in session.new; flush them before
        # the timer-ledger rewrite so its bulk DELETE can actually see/remove
        # that first generation instead of committing both generations together.
        flush = getattr(db, "flush", None)
        if callable(flush):
            flush()

        order = db.get(WebOrder, int(order_id))
        if order is not None and _is_timer_order(int(order_id), db):
            _rewrite_worker_payouts(db, order)
            if callable(flush):
                flush()
        return result

    def promote_with_timer_ledger(*args, **kwargs):
        # original_promote dynamically imports order_service.recalculate_order_payouts,
        # which is replaced by recalculate_with_timer_ledger below. A second
        # SessionLocal recalculation here used to rebuild the same payout again
        # after payment promotion and was redundant/race-prone.
        return original_promote(*args, **kwargs)

    order_service.recalculate_order_payouts = recalculate_with_timer_ledger
    acceptance.promote_acceptance_claims_to_assignments = promote_with_timer_ledger
    _install_accounting_integrations(recalculate_with_timer_ledger)
    _INSTALLED = True


__all__ = [
    "get_vip_timer_worker_payout_plan",
    "install_vip_timer_roster_payout",
    "recalculate_vip_timer_worker_payouts",
]