from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from web.app.services.accounting_reconciliation import (
    build_accounting_reconciliation_snapshot,
)

TAIPEI_TZ = timezone(timedelta(hours=8))
UTC_TZ = timezone.utc

CANONICAL_ORDER_STATES = {
    "pending_cs_dispatch",
    "waiting_acceptance",
    "accepted_pending_pay",
    "active",
    "stored",
    "closed",
    "cancelled",
}

ORDER_STATE_ALIASES = {
    "created": "pending_cs_dispatch",
    "paid": "active",
    "completed": "closed",
    "done": "closed",
    "canceled": "cancelled",
}

OPEN_ORDER_STATES = {
    "pending_cs_dispatch",
    "waiting_acceptance",
    "accepted_pending_pay",
    "active",
    "stored",
}

ORDER_STALE_WARNING_MINUTES = {
    "pending_cs_dispatch": 30,
    "waiting_acceptance": 60,
    "accepted_pending_pay": 60,
    "active": 36 * 60,
}

SEVERITY_ORDER = {
    "critical": 0,
    "warning": 1,
    "info": 2,
}

CATEGORY_LABELS = {
    "order": "訂單流程",
    "payment": "付款審核",
    "sync": "Discord 同步",
    "topup": "儲值流程",
    "accounting": "帳務對帳",
    "support": "客服鈴",
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _connect_readonly(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None

    try:
        conn = sqlite3.connect(
            f"file:{path}?mode=ro",
            uri=True,
            timeout=3.0,
        )
    except sqlite3.Error:
        return None

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        LIMIT 1
        """,
        (str(table),),
    ).fetchone()
    return row is not None


def _normalize_order_status(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return ORDER_STATE_ALIASES.get(normalized, normalized)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None

        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        parsed = None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S.%f",
            ):
                try:
                    parsed = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue

        if parsed is None:
            return None

    if parsed.tzinfo is None:
        # SQLAlchemy models in shared/models.py use datetime.utcnow and SQLite
        # CURRENT_TIMESTAMP also stores UTC. Explicit ISO workflow tables already
        # include their timezone offsets.
        parsed = parsed.replace(tzinfo=UTC_TZ)

    return parsed.astimezone(TAIPEI_TZ)


def _age_minutes(value: Any, *, now: datetime) -> int | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds() // 60))


def _format_age(minutes: int | None) -> str:
    if minutes is None:
        return "-"
    if minutes < 60:
        return f"{minutes} 分鐘"
    hours, remainder = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} 小時 {remainder} 分"
    days, hours = divmod(hours, 24)
    return f"{days} 天 {hours} 小時"


def _issue(
    issues: list[dict[str, Any]],
    *,
    category: str,
    code: str,
    severity: str,
    reference: str,
    title: str,
    detail: str,
    age_minutes: int | None = None,
    order_id: int | None = None,
    action_url: str | None = None,
    action_label: str | None = None,
    source: str = "runtime",
) -> None:
    if severity not in SEVERITY_ORDER:
        severity = "warning"

    if action_url is None and order_id is not None:
        action_url = f"/admin/order-workspace/{int(order_id)}"
        action_label = action_label or "查看訂單"

    issues.append(
        {
            "category": category,
            "category_label": CATEGORY_LABELS.get(category, category),
            "code": code,
            "severity": severity,
            "reference": str(reference or "-"),
            "title": str(title),
            "detail": str(detail),
            "age_minutes": age_minutes,
            "age_text": _format_age(age_minutes),
            "order_id": int(order_id) if order_id is not None else None,
            "action_url": action_url,
            "action_label": action_label,
            "source": source,
        }
    )


def _order_reference(row: sqlite3.Row | dict[str, Any]) -> str:
    data = dict(row)
    order_no = str(data.get("bot_order_no") or "").strip()
    if order_no:
        return order_no
    return f"WEB-{int(data.get('id') or 0)}"


def _check_orders(
    web: sqlite3.Connection,
    issues: list[dict[str, Any]],
    *,
    now: datetime,
) -> None:
    if not _table_exists(web, "web_orders"):
        return

    has_assignments = _table_exists(web, "order_assignments")
    assignment_expr = (
        """
        (
            SELECT COUNT(*)
            FROM order_assignments a
            WHERE a.order_id = o.id
              AND COALESCE(a.is_active, 1) = 1
        ) AS active_assignment_count
        """
        if has_assignments
        else "0 AS active_assignment_count"
    )

    rows = web.execute(
        f"""
        SELECT
            o.id,
            o.bot_order_no,
            o.status,
            o.ticket_channel_id,
            o.dispatch_channel_id,
            o.dispatch_message_id,
            o.customer_discord_id,
            o.created_at,
            o.updated_at,
            {assignment_expr}
        FROM web_orders o
        ORDER BY o.id DESC
        """
    ).fetchall()

    acceptance_status: dict[int, str] = {}
    if _table_exists(web, "order_acceptance_meta"):
        for row in web.execute(
            "SELECT order_id, status FROM order_acceptance_meta"
        ).fetchall():
            acceptance_status[int(row["order_id"])] = _normalize_order_status(
                row["status"]
            )

    for row in rows:
        data = dict(row)
        order_id = int(data["id"])
        reference = _order_reference(data)
        status = _normalize_order_status(data.get("status"))
        updated_value = data.get("updated_at") or data.get("created_at")
        age = _age_minutes(updated_value, now=now)

        if status not in CANONICAL_ORDER_STATES:
            _issue(
                issues,
                category="order",
                code="unknown_order_status",
                severity="critical",
                reference=reference,
                title="訂單出現未知狀態",
                detail=f"目前狀態為 {data.get('status')!r}，不在正式狀態機內。",
                age_minutes=age,
                order_id=order_id,
            )
            continue

        meta_status = acceptance_status.get(order_id)
        if meta_status and meta_status != status:
            _issue(
                issues,
                category="order",
                code="order_state_drift",
                severity="critical",
                reference=reference,
                title="訂單狀態不同步",
                detail=(
                    f"web_orders={status}，order_acceptance_meta={meta_status}。"
                    " 兩邊狀態應一致。"
                ),
                age_minutes=age,
                order_id=order_id,
            )

        if status not in OPEN_ORDER_STATES:
            continue

        customer_id = str(data.get("customer_discord_id") or "").strip()
        ticket_channel_id = str(data.get("ticket_channel_id") or "").strip()
        dispatch_channel_id = str(data.get("dispatch_channel_id") or "").strip()
        dispatch_message_id = str(data.get("dispatch_message_id") or "").strip()
        assignments = int(data.get("active_assignment_count") or 0)

        if not customer_id:
            _issue(
                issues,
                category="order",
                code="open_order_customer_missing",
                severity="critical",
                reference=reference,
                title="進行中訂單缺少顧客 Discord ID",
                detail="無法可靠辨識顧客，後續付款、權限與客服流程可能失效。",
                age_minutes=age,
                order_id=order_id,
            )

        if not ticket_channel_id:
            _issue(
                issues,
                category="order",
                code="open_order_ticket_missing",
                severity="critical",
                reference=reference,
                title="進行中訂單缺少票口頻道 ID",
                detail="訂單仍在流程中，但資料庫沒有 ticket_channel_id。",
                age_minutes=age,
                order_id=order_id,
            )

        if status == "waiting_acceptance" and (
            not dispatch_channel_id or not dispatch_message_id
        ):
            _issue(
                issues,
                category="order",
                code="waiting_order_dispatch_reference_missing",
                severity="critical",
                reference=reference,
                title="等待接單卻缺少派單訊息識別碼",
                detail=(
                    "狀態是 waiting_acceptance，但 dispatch_channel_id 或 "
                    "dispatch_message_id 缺失，可能導致接單按鈕無法正常工作。"
                ),
                age_minutes=age,
                order_id=order_id,
            )

        if status == "accepted_pending_pay" and assignments <= 0:
            _issue(
                issues,
                category="order",
                code="accepted_order_assignment_missing",
                severity="critical",
                reference=reference,
                title="已接單待付款卻沒有有效接單人員",
                detail="accepted_pending_pay 應至少有一筆有效 order_assignment。",
                age_minutes=age,
                order_id=order_id,
            )

        if status == "active" and assignments <= 0:
            _issue(
                issues,
                category="order",
                code="active_order_assignment_missing",
                severity="warning",
                reference=reference,
                title="進行中訂單沒有有效接單人員",
                detail="可能是舊資料或接單同步遺失，請確認目前實際服務人員。",
                age_minutes=age,
                order_id=order_id,
            )

        stale_after = ORDER_STALE_WARNING_MINUTES.get(status)
        if stale_after is not None and age is not None and age >= stale_after:
            _issue(
                issues,
                category="order",
                code=f"order_stale_{status}",
                severity="warning",
                reference=reference,
                title="訂單長時間沒有更新",
                detail=(
                    f"目前狀態 {status} 已約 {_format_age(age)}沒有更新；"
                    "請確認是否卡在客服、接單、付款或結單流程。"
                ),
                age_minutes=age,
                order_id=order_id,
            )


def _check_payment_reviews(
    web: sqlite3.Connection,
    issues: list[dict[str, Any]],
    *,
    now: datetime,
) -> None:
    if not _table_exists(web, "payment_reviews"):
        return

    rows = web.execute(
        """
        SELECT
            id,
            review_no,
            source_type,
            source_id,
            status,
            created_at,
            updated_at,
            apply_error
        FROM payment_reviews
        WHERE status IN (
            'pending_review',
            'approved_pending_apply',
            'apply_error'
        )
        ORDER BY id DESC
        """
    ).fetchall()

    for row in rows:
        data = dict(row)
        status = str(data.get("status") or "").strip()
        reference = str(data.get("review_no") or f"PAY-{data['id']}")
        age = _age_minutes(
            data.get("updated_at") or data.get("created_at"),
            now=now,
        )
        source_type = str(data.get("source_type") or "").strip()
        source_id = str(data.get("source_id") or "").strip()

        if status == "apply_error":
            _issue(
                issues,
                category="payment",
                code="payment_apply_error",
                severity="critical",
                reference=reference,
                title="付款核准後套用失敗",
                detail=(
                    f"來源 {source_type}:{source_id}。"
                    f" {str(data.get('apply_error') or '沒有錯誤訊息')[:240]}"
                ),
                age_minutes=age,
                action_url="/admin/payment-reviews",
                action_label="處理付款",
            )
        elif status == "approved_pending_apply" and age is not None and age >= 10:
            _issue(
                issues,
                category="payment",
                code="payment_approved_apply_stalled",
                severity="critical",
                reference=reference,
                title="付款已核准但尚未套用",
                detail="核准後超過 10 分鐘仍未完成套用，可能是 Bot runtime 卡住。",
                age_minutes=age,
                action_url="/admin/payment-reviews",
                action_label="查看付款",
            )
        elif status == "pending_review" and age is not None and age >= 30:
            _issue(
                issues,
                category="payment",
                code="payment_review_waiting_long",
                severity="warning",
                reference=reference,
                title="付款審核等待時間過長",
                detail="待人工審核超過 30 分鐘。",
                age_minutes=age,
                action_url="/admin/payment-reviews?status=pending",
                action_label="前往審核",
            )


def _check_sync_events(
    web: sqlite3.Connection,
    issues: list[dict[str, Any]],
    *,
    now: datetime,
) -> None:
    if not _table_exists(web, "sync_events"):
        return

    rows = web.execute(
        """
        SELECT
            id,
            event_type,
            status,
            order_id,
            error_message,
            retry_count,
            created_at,
            processed_at
        FROM sync_events
        WHERE status IN ('pending', 'processing', 'failed')
        ORDER BY id DESC
        LIMIT 500
        """
    ).fetchall()

    for row in rows:
        data = dict(row)
        event_id = int(data["id"])
        status = str(data.get("status") or "").strip().lower()
        event_type = str(data.get("event_type") or "unknown")
        order_id = (
            int(data["order_id"])
            if data.get("order_id") is not None
            else None
        )
        age = _age_minutes(
            data.get("processed_at") or data.get("created_at"),
            now=now,
        )
        reference = f"SYNC-{event_id}"

        if status == "failed":
            _issue(
                issues,
                category="sync",
                code="sync_event_failed",
                severity="critical",
                reference=reference,
                title="Discord / Web 同步事件失敗",
                detail=(
                    f"{event_type}，重試 {int(data.get('retry_count') or 0)} 次。"
                    f" {str(data.get('error_message') or '')[:240]}"
                ).strip(),
                age_minutes=age,
                order_id=order_id,
                action_url=(
                    f"/admin/order-workspace/{order_id}"
                    if order_id is not None
                    else "/admin/system"
                ),
                action_label="查看相關資料",
            )
        elif status == "processing" and age is not None and age >= 10:
            _issue(
                issues,
                category="sync",
                code="sync_event_processing_stalled",
                severity="critical" if age >= 30 else "warning",
                reference=reference,
                title="同步事件卡在 processing",
                detail=f"{event_type} 已 {_format_age(age)}沒有完成。",
                age_minutes=age,
                order_id=order_id,
            )
        elif status == "pending" and age is not None and age >= 15:
            _issue(
                issues,
                category="sync",
                code="sync_event_pending_stalled",
                severity="critical" if age >= 60 else "warning",
                reference=reference,
                title="同步事件等待時間過長",
                detail=f"{event_type} 已等待 {_format_age(age)}。",
                age_minutes=age,
                order_id=order_id,
            )


def _check_topups(
    bot: sqlite3.Connection,
    issues: list[dict[str, Any]],
    *,
    now: datetime,
) -> None:
    if not _table_exists(bot, "topup_orders"):
        return

    rows = bot.execute(
        """
        SELECT
            id,
            topup_no,
            status,
            created_at,
            updated_at
        FROM topup_orders
        WHERE status IN (
            'pending_review',
            'approved_pending_credit',
            'crediting'
        )
        ORDER BY id DESC
        """
    ).fetchall()

    for row in rows:
        data = dict(row)
        status = str(data.get("status") or "").strip()
        reference = str(data.get("topup_no") or f"TOPUP-ID-{data['id']}")
        age = _age_minutes(
            data.get("updated_at") or data.get("created_at"),
            now=now,
        )

        if status == "pending_review" and age is not None and age >= 30:
            _issue(
                issues,
                category="topup",
                code="topup_review_waiting_long",
                severity="warning",
                reference=reference,
                title="儲值審核等待時間過長",
                detail="待客服審核超過 30 分鐘。",
                age_minutes=age,
                action_url="/admin/topups?status=pending_review",
                action_label="前往審核",
            )
        elif status == "approved_pending_credit" and age is not None and age >= 10:
            _issue(
                issues,
                category="topup",
                code="topup_credit_waiting_long",
                severity="warning",
                reference=reference,
                title="儲值已核准但尚未入帳",
                detail="核准後超過 10 分鐘仍在等待入帳。",
                age_minutes=age,
                action_url="/admin/topups?status=approved_pending_credit",
                action_label="查看儲值",
            )
        elif status == "crediting" and age is not None and age >= 10:
            _issue(
                issues,
                category="topup",
                code="topup_crediting_stalled",
                severity="critical",
                reference=reference,
                title="儲值卡在入帳中",
                detail="crediting 超過 10 分鐘，請確認 Bot runtime 與錢包流水。",
                age_minutes=age,
                action_url="/admin/topups?status=crediting",
                action_label="查看儲值",
            )


def _check_support_calls(
    web: sqlite3.Connection,
    issues: list[dict[str, Any]],
    *,
    now: datetime,
) -> None:
    if not _table_exists(web, "support_calls"):
        return

    rows = web.execute(
        """
        SELECT
            id,
            ticket_channel_id,
            customer_discord_id,
            status,
            called_at,
            claimed_at,
            updated_at
        FROM support_calls
        WHERE status IN ('open', 'claimed')
        ORDER BY id DESC
        LIMIT 300
        """
    ).fetchall()

    for row in rows:
        data = dict(row)
        status = str(data.get("status") or "").strip().lower()
        call_id = int(data.get("id") or 0)
        reference = f"客服鈴 #{call_id}"
        age = _age_minutes(
            data.get("called_at") or data.get("updated_at"),
            now=now,
        )

        if status == "open" and age is not None and age >= 15:
            _issue(
                issues,
                category="support",
                code="support_call_unclaimed_15m",
                severity="critical",
                reference=reference,
                title="客服鈴超過 15 分鐘仍未接手",
                detail=(
                    f"票口 {data.get('ticket_channel_id') or '-'} 的客服需求"
                    f"已等待 {_format_age(age)}。"
                ),
                age_minutes=age,
                action_url="/admin/support-calls",
                action_label="查看客服鈴",
            )
        elif status == "open" and age is not None and age >= 5:
            _issue(
                issues,
                category="support",
                code="support_call_unclaimed_5m",
                severity="warning",
                reference=reference,
                title="客服鈴超過 5 分鐘仍未接手",
                detail=(
                    f"票口 {data.get('ticket_channel_id') or '-'} 的客服需求"
                    f"已等待 {_format_age(age)}。"
                ),
                age_minutes=age,
                action_url="/admin/support-calls",
                action_label="查看客服鈴",
            )
        elif status == "claimed" and age is not None and age >= 120:
            _issue(
                issues,
                category="support",
                code="support_call_claimed_long",
                severity="warning",
                reference=reference,
                title="客服鈴已接手但長時間未完成",
                detail=(
                    f"票口 {data.get('ticket_channel_id') or '-'} 的客服需求"
                    f"自呼叫起已 {_format_age(age)}，請確認是否忘記完成處理。"
                ),
                age_minutes=age,
                action_url="/admin/support-calls",
                action_label="查看客服鈴",
            )


def _append_accounting_issues(
    issues: list[dict[str, Any]],
    accounting: dict[str, Any],
) -> None:
    for item in accounting.get("issues") or []:
        severity = str(item.get("severity") or "warning").lower()
        if severity not in {"critical", "warning"}:
            severity = "warning"

        raw_order_id = item.get("order_id")
        order_id: int | None = None
        if raw_order_id not in (None, ""):
            try:
                order_id = int(raw_order_id)
            except (TypeError, ValueError):
                order_id = None

        action_url = (
            f"/admin/order-workspace/{order_id}"
            if order_id is not None
            else "/admin/accounting-reconciliation"
        )

        _issue(
            issues,
            category="accounting",
            code=str(item.get("code") or "accounting_issue"),
            severity=severity,
            reference=str(item.get("reference") or "-"),
            title=str(item.get("title") or "帳務對帳異常"),
            detail=str(item.get("detail") or "請前往帳務對帳查看。"),
            order_id=order_id,
            action_url=action_url,
            action_label=(
                "查看訂單"
                if order_id is not None
                else "前往帳務對帳"
            ),
            source="accounting",
        )


def build_anomaly_snapshot(
    root: Path | None = None,
    *,
    limit: int = 400,
    now: datetime | None = None,
) -> dict[str, Any]:
    root = root or repository_root()
    now = (now or datetime.now(TAIPEI_TZ)).astimezone(TAIPEI_TZ)
    limit = max(20, min(int(limit or 400), 1000))

    issues: list[dict[str, Any]] = []
    web = _connect_readonly(root / "web_dashboard.db")
    bot = _connect_readonly(root / "bot.db")

    unavailable: list[str] = []

    if web is None:
        unavailable.append("web_dashboard.db")
    else:
        try:
            _check_orders(web, issues, now=now)
            _check_payment_reviews(web, issues, now=now)
            _check_sync_events(web, issues, now=now)
            _check_support_calls(web, issues, now=now)
        finally:
            web.close()

    if bot is None:
        unavailable.append("bot.db")
    else:
        try:
            _check_topups(bot, issues, now=now)
        finally:
            bot.close()

    accounting = build_accounting_reconciliation_snapshot(
        root,
        detail_limit=limit,
    )
    _append_accounting_issues(issues, accounting)

    if unavailable:
        _issue(
            issues,
            category="sync",
            code="anomaly_source_unavailable",
            severity="critical",
            reference="DATABASE",
            title="異常中心無法讀取資料來源",
            detail="無法讀取：" + "、".join(unavailable),
            action_url="/admin/system",
            action_label="查看系統健康",
        )

    issues.sort(
        key=lambda item: (
            SEVERITY_ORDER.get(str(item.get("severity")), 9),
            -(int(item.get("age_minutes") or -1)),
            str(item.get("category") or ""),
            str(item.get("reference") or ""),
        )
    )

    total_issue_count = len(issues)
    visible_issues = issues[:limit]

    severity_counts = Counter(
        str(item.get("severity") or "warning")
        for item in issues
    )
    category_counts = Counter(
        str(item.get("category") or "other")
        for item in issues
    )

    if severity_counts.get("critical", 0):
        status = "critical"
        status_text = "需要處理"
    elif total_issue_count:
        status = "warning"
        status_text = "有注意事項"
    else:
        status = "ok"
        status_text = "目前正常"

    return {
        "checked_at": now.strftime("%Y/%m/%d %H:%M:%S"),
        "status": status,
        "status_text": status_text,
        "issue_count": total_issue_count,
        "critical_count": int(severity_counts.get("critical", 0)),
        "warning_count": int(severity_counts.get("warning", 0)),
        "category_counts": dict(category_counts),
        "category_labels": dict(CATEGORY_LABELS),
        "issues": visible_issues,
        "truncated": total_issue_count > len(visible_issues),
        "visible_count": len(visible_issues),
        "accounting_issue_count": int(accounting.get("issue_count") or 0),
    }
