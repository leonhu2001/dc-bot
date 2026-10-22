from __future__ import annotations

import json
from functools import wraps
from typing import Any, Callable

from sqlalchemy import inspect, or_, select, text

from services.vip_timer import VIP_TIMER_CATEGORY_LABEL, VIP_TIMER_MARKER
from shared.db import SessionLocal
from shared.models import WebOrder


_INSTALLED = False
_ACCOUNTING_INSTALLED = False
_TIMER_WORKER_ISSUE_CODES = {
    "worker_payout_missing",
    "worker_payout_duplicate",
    "worker_payout_amount_mismatch",
    "worker_payout_without_assignment",
}

# All known VIP timer tables that are keyed by order_id. Child/history tables are
# intentionally deleted before the session row so this remains safe if foreign
# keys are added later.
_VIP_TIMER_ORDER_TABLES = (
    "vip_timer_end_requests",
    "vip_timer_corrections",
    "vip_timer_disputes",
    "vip_timer_alerts",
    "vip_timer_events",
    "vip_timer_segments",
    "vip_timer_sessions",
)


def _order_value(order: Any, key: str, default=None):
    if order is None:
        return default
    try:
        value = getattr(order, key)
    except Exception:
        try:
            value = order[key]
        except Exception:
            return default
    return default if value is None else value


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or ""))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _vip_timer_identity_parts(order: Any) -> tuple[bool, bool]:
    """Return (marker_present, structural_timer_signal_present).

    A real timer order is stamped twice at creation time. Discord checkout writes
    the VIP category + free-timer item + marker; website checkout writes the
    free-timer item + a vip_timer price snapshot + marker. Requiring the marker
    plus one structural signal prevents an orphan vip_timer_sessions row (or a
    stale marker left on a repurposed WebOrder) from changing payout semantics.
    """
    category = str(_order_value(order, "category", "") or "").strip()
    item = str(_order_value(order, "item", "") or "").strip()
    note = str(_order_value(order, "note", "") or "")
    price_snapshot = _json_dict(_order_value(order, "price_snapshot_json", None))

    marker_present = VIP_TIMER_MARKER in note
    structural_signal = (
        category == VIP_TIMER_CATEGORY_LABEL
        or item.startswith("自由計時｜")
        or bool(price_snapshot.get("vip_timer"))
    )
    return marker_present, structural_signal


def web_order_has_vip_timer_identity(order: Any) -> bool:
    marker_present, structural_signal = _vip_timer_identity_parts(order)
    return bool(marker_present and structural_signal)


def _has_table(db, table_name: str) -> bool:
    try:
        return bool(inspect(db.connection()).has_table(str(table_name)))
    except Exception:
        return False


def _has_timer_session(order_id: int, db) -> bool:
    if not _has_table(db, "vip_timer_sessions"):
        return False
    row = db.execute(
        text("SELECT 1 FROM vip_timer_sessions WHERE order_id=:order_id LIMIT 1"),
        {"order_id": int(order_id)},
    ).first()
    return row is not None


def is_canonical_vip_timer_order(order_id: int, db) -> bool:
    """Require both persisted timer metadata and canonical WebOrder identity."""
    try:
        if not _has_timer_session(int(order_id), db):
            return False
        order = db.get(WebOrder, int(order_id))
        if order is None:
            return False
        return web_order_has_vip_timer_identity(order)
    except Exception:
        # Ordinary payout calculation must keep working if the timer schema is
        # missing or temporarily unreadable.
        return False


def delete_vip_timer_rows(order_id: int, db=None) -> int:
    """Delete every known VIP timer row for one WebOrder ID, idempotently."""
    owns_session = db is None
    if owns_session:
        db = SessionLocal()

    deleted = 0
    try:
        for table_name in _VIP_TIMER_ORDER_TABLES:
            if not _has_table(db, table_name):
                continue
            result = db.execute(
                text(f"DELETE FROM {table_name} WHERE order_id=:order_id"),
                {"order_id": int(order_id)},
            )
            rowcount = getattr(result, "rowcount", 0)
            if isinstance(rowcount, int) and rowcount > 0:
                deleted += rowcount
        if owns_session:
            db.commit()
        return deleted
    except Exception:
        if owns_session:
            db.rollback()
        raise
    finally:
        if owns_session:
            db.close()


def cleanup_stale_vip_timer_rows(db=None) -> list[int]:
    """Remove timer rows that are provably attached to a non-timer/orphan order.

    Structural-only historical rows are preserved (fail closed) because they may
    be a very old real timer whose marker is unavailable. Marker-only rows are
    safe to remove: a real timer always has an additional timer structure signal,
    while a repurposed normal order can retain only an old note marker.
    """
    owns_session = db is None
    if owns_session:
        db = SessionLocal()

    removed: list[int] = []
    try:
        if not _has_table(db, "vip_timer_sessions") or not _has_table(db, "web_orders"):
            return removed

        order_ids = [
            int(row[0])
            for row in db.execute(
                text("SELECT order_id FROM vip_timer_sessions ORDER BY order_id ASC")
            ).all()
        ]

        for order_id in order_ids:
            order = db.get(WebOrder, int(order_id))
            if order is None:
                delete_vip_timer_rows(int(order_id), db)
                removed.append(int(order_id))
                continue

            marker_present, structural_signal = _vip_timer_identity_parts(order)
            if marker_present and structural_signal:
                continue

            # Keep structural-only rows for manual inspection; they are not
            # treated as canonical timers by accounting, but we also do not
            # destroy potentially historical timer evidence automatically.
            if structural_signal and not marker_present:
                continue

            delete_vip_timer_rows(int(order_id), db)
            removed.append(int(order_id))

        if owns_session:
            db.commit()
        return removed
    except Exception:
        if owns_session:
            db.rollback()
        raise
    finally:
        if owns_session:
            db.close()


def _resolve_web_order_id(*, ticket_channel_id=None, dispatch_message_id=None) -> int | None:
    ticket = str(ticket_channel_id or "").strip()
    dispatch = str(dispatch_message_id or "").strip()
    if not ticket and not dispatch:
        return None

    db = SessionLocal()
    try:
        clauses = []
        if ticket:
            clauses.append(WebOrder.ticket_channel_id == ticket)
        if dispatch:
            clauses.append(WebOrder.dispatch_message_id == dispatch)
        if not clauses:
            return None
        order = db.scalar(select(WebOrder).where(or_(*clauses)).limit(1))
        return int(order.id) if order is not None else None
    finally:
        db.close()


def _provably_normal_timer_session_order_ids(web) -> set[int]:
    """Return closed orders whose session row is stale, not timer identity.

    This intentionally excludes structural-only historical rows. Those remain
    ambiguous and should not be silently reinterpreted in either direction.
    """
    try:
        rows = web.execute(
            """
            SELECT
                s.order_id,
                o.category,
                o.item,
                o.note,
                o.price_snapshot_json
            FROM vip_timer_sessions AS s
            JOIN web_orders AS o ON o.id = s.order_id
            WHERE LOWER(COALESCE(o.status, '')) = 'closed'
            """
        ).fetchall()
    except Exception:
        return set()

    result: set[int] = set()
    for row in rows:
        payload = dict(row)
        marker_present, structural_signal = _vip_timer_identity_parts(payload)
        if structural_signal:
            continue
        # No timer structure means the WebOrder is demonstrably an ordinary
        # order. This also covers marker-only residue on a repurposed row.
        _ = marker_present
        try:
            result.add(int(payload.get("order_id") or 0))
        except (TypeError, ValueError):
            continue
    result.discard(0)
    return result


def _restore_generic_worker_issues_for_noncanonical_timers(
    web,
    issues: list[dict[str, Any]],
    generic_checker: Callable[[Any, list[dict[str, Any]]], None],
) -> None:
    stale_ids = _provably_normal_timer_session_order_ids(web)
    if not stale_ids:
        return

    generic_issues: list[dict[str, Any]] = []
    generic_checker(web, generic_issues)
    existing = {
        (
            int(item.get("order_id") or 0),
            str(item.get("code") or ""),
            str(item.get("detail") or ""),
        )
        for item in issues
    }
    for item in generic_issues:
        order_id = int(item.get("order_id") or 0)
        code = str(item.get("code") or "")
        if order_id not in stale_ids or code not in _TIMER_WORKER_ISSUE_CODES:
            continue
        identity = (order_id, code, str(item.get("detail") or ""))
        if identity in existing:
            continue
        issues.append(item)
        existing.add(identity)


def install_vip_timer_accounting_integrity_guard(
    generic_checker: Callable[[Any, list[dict[str, Any]]], None],
) -> None:
    """Ensure stale timer rows can never suppress ordinary payout diagnostics."""
    global _ACCOUNTING_INSTALLED
    if _ACCOUNTING_INSTALLED:
        return

    from web.app.services import accounting_reconciliation as reconciliation

    timer_aware_checker = reconciliation._check_payouts

    @wraps(timer_aware_checker)
    def checked(web, issues):
        timer_aware_checker(web, issues)
        _restore_generic_worker_issues_for_noncanonical_timers(
            web,
            issues,
            generic_checker,
        )

    reconciliation._check_payouts = checked
    _ACCOUNTING_INSTALLED = True


def install_vip_timer_integrity_guard() -> None:
    """Install cross-process guards without changing timer business logic."""
    global _INSTALLED
    if _INSTALLED:
        return

    from shared import web_order_sync
    from services import vip_timer_roster_payout

    original_delete = web_order_sync.delete_web_order_by_ticket_channel

    @wraps(original_delete)
    def delete_with_timer_cleanup(*, ticket_channel_id=None, dispatch_message_id=None):
        order_id = _resolve_web_order_id(
            ticket_channel_id=ticket_channel_id,
            dispatch_message_id=dispatch_message_id,
        )
        result = original_delete(
            ticket_channel_id=ticket_channel_id,
            dispatch_message_id=dispatch_message_id,
        )
        if result and order_id is not None:
            try:
                delete_vip_timer_rows(int(order_id))
            except Exception as exc:
                # The WebOrder deletion already committed. Do not turn a
                # successful retract into a fake failure; startup reconciliation
                # will retry orphan cleanup, and canonical detection below keeps
                # the stale row from affecting ordinary payout logic meanwhile.
                print(
                    f"[vip-timer-integrity] deferred timer cleanup "
                    f"order_id={order_id}: {type(exc).__name__}: {exc}",
                    flush=True,
                )
        return result

    web_order_sync.delete_web_order_by_ticket_channel = delete_with_timer_cleanup
    vip_timer_roster_payout._is_timer_order = is_canonical_vip_timer_order
    _INSTALLED = True


__all__ = [
    "cleanup_stale_vip_timer_rows",
    "delete_vip_timer_rows",
    "install_vip_timer_accounting_integrity_guard",
    "install_vip_timer_integrity_guard",
    "is_canonical_vip_timer_order",
    "web_order_has_vip_timer_identity",
]
