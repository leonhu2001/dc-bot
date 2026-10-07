import asyncio
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from services.dispatch_presence import (
    count_online_dispatch_workers,
    get_online_dispatch_support_ids,
)
from shared.order_acceptance import (
    PUBLIC_ACCEPTANCE_LOCK_SECONDS,
    WAITING_ACCEPTANCE,
)
from web.app.config import config
from web.app.services.dispatch_access import (
    can_use_dispatch,
    touch_dispatch_user_presence,
)
from web.app.services.order_service import VISIBLE_DISPATCH_STATUSES

router = APIRouter(tags=["dispatch_state"])

_VISIBLE_STATUS_VALUES = tuple(VISIBLE_DISPATCH_STATUSES)
_VISIBLE_STATUS_PLACEHOLDERS = ", ".join("?" for _ in _VISIBLE_STATUS_VALUES)
_DISPATCH_EVENT_CACHE_TTL_SECONDS = 1.0
# SessionMiddleware 的登入 cookie 目前是 12 小時效期。SSE 連線本身可以掛很久，
# 但 HTTP response headers 只會在連線建立時送一次，因此長時間只靠 SSE 心跳
# 不會刷新登入 cookie。定期主動結束串流，讓瀏覽器 EventSource 自動重連；
# 每次重連都會重新經過 SessionMiddleware 並刷新 cookie 效期。
# 這樣員工只要仍掛在接單大廳，就不會因為長時間待機而被自動登出。
_DISPATCH_SSE_SESSION_REFRESH_SECONDS = 4 * 60 * 60
_dispatch_event_cache: dict | None = None
_dispatch_event_cache_expires_at = 0.0
_dispatch_event_cache_lock = asyncio.Lock()


def get_sqlite_path() -> str:
    url = config.DATABASE_URL
    if not url.startswith("sqlite:///"):
        raise RuntimeError("Only sqlite DATABASE_URL is supported for dispatch state")
    return url.replace("sqlite:///", "", 1)


def _dispatch_presence_snapshot() -> dict:
    return {
        "online_companion_count": count_online_dispatch_workers(),
        "online_support_count": len(get_online_dispatch_support_ids()),
    }


def _load_json_id_list(value) -> list[str]:
    if value is None:
        return []

    try:
        parsed = json.loads(str(value))
    except Exception:
        return []

    if not isinstance(parsed, list):
        return []

    return [str(item).strip() for item in parsed if str(item).strip()]


def _load_csv_id_list(value) -> list[str]:
    return [
        part.strip()
        for part in str(value or "").split(",")
        if part.strip()
    ]


def _acceptance_lock_info(
    created_at_value,
    status_value,
) -> tuple[bool, str | None, int]:
    if str(status_value or "").strip() != WAITING_ACCEPTANCE:
        return False, None, 0

    created_text = str(created_at_value or "").strip()
    if not created_text:
        return False, None, 0

    try:
        created = datetime.fromisoformat(created_text.replace("Z", "+00:00"))
    except ValueError:
        return False, None, 0

    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    else:
        created = created.astimezone(timezone.utc)

    opens_at = created + timedelta(seconds=PUBLIC_ACCEPTANCE_LOCK_SECONDS)
    now = datetime.now(timezone.utc)
    remaining_float = (opens_at - now).total_seconds()
    locked = remaining_float > 0
    remaining_seconds = max(0, int(remaining_float + 0.999)) if locked else 0
    opens_at_text = opens_at.isoformat().replace("+00:00", "Z")
    return locked, opens_at_text, remaining_seconds


def _dispatch_order_rows() -> list[sqlite3.Row]:
    conn = sqlite3.connect(get_sqlite_path())
    conn.row_factory = sqlite3.Row

    try:
        return conn.execute(
            f"""
            SELECT
                o.id,
                o.bot_order_no,
                o.ticket_channel_id,
                o.dispatch_message_id,
                o.customer_display_name,
                o.customer_discord_id,
                o.category,
                o.item,
                o.quantity,
                o.amount,
                o.status,
                o.updated_at,
                o.created_at,
                m.created_at AS acceptance_created_at,
                m.required_staff_count AS acceptance_required_staff_count,
                m.specified_staff_ids_json,
                (
                    SELECT GROUP_CONCAT(c.staff_discord_id, ',')
                    FROM order_acceptance_claims c
                    WHERE c.order_id = o.id
                      AND c.is_active = 1
                ) AS active_claim_staff_ids
            FROM web_orders o
            LEFT JOIN order_acceptance_meta m ON m.order_id = o.id
            WHERE o.status IN ({_VISIBLE_STATUS_PLACEHOLDERS})
            ORDER BY o.id ASC
            """,
            _VISIBLE_STATUS_VALUES,
        ).fetchall()
    finally:
        conn.close()


def _dispatch_state_snapshot(*, include_orders: bool) -> dict:
    rows = _dispatch_order_rows()
    orders = []
    alert_rules: dict[str, dict] = {}

    for row in rows:
        order_key = str(row["bot_order_no"] or f"WEB-{row['id']}")
        specified_staff_ids = _load_json_id_list(row["specified_staff_ids_json"])
        active_claim_staff_ids = _load_csv_id_list(row["active_claim_staff_ids"])
        required_staff_count = int(row["acceptance_required_staff_count"] or 0)
        acceptance_locked, acceptance_opens_at, lock_remaining_seconds = (
            _acceptance_lock_info(
                row["acceptance_created_at"],
                row["status"],
            )
        )

        orders.append(
            {
                "id": row["id"],
                "key": order_key,
                "bot_order_no": row["bot_order_no"],
                "ticket_channel_id": row["ticket_channel_id"],
                "dispatch_message_id": row["dispatch_message_id"],
                "customer": (
                    row["customer_display_name"]
                    or row["customer_discord_id"]
                    or ""
                ),
                "category": row["category"] or "",
                "item": row["item"] or "",
                "quantity": row["quantity"] or 0,
                "amount": row["amount"] or 0,
                "status": row["status"] or "",
                "updated_at": row["updated_at"] or "",
                "created_at": row["created_at"] or "",
                "acceptance_locked": acceptance_locked,
                "acceptance_opens_at": acceptance_opens_at,
                "acceptance_lock_remaining_seconds": lock_remaining_seconds,
            }
        )
        alert_rules[order_key] = {
            "required_staff_count": required_staff_count,
            "specified_staff_ids": specified_staff_ids,
            "active_claim_staff_ids": active_claim_staff_ids,
            "acceptance_locked": acceptance_locked,
        }

    signature = "|".join(
        (
            f"{order['id']}:{order['key']}:{order['updated_at']}:"
            f"{order['amount']}:{order['quantity']}:{order['status']}:"
            f"{int(bool(alert_rules[order['key']]['acceptance_locked']))}:"
            f"{alert_rules[order['key']]['required_staff_count']}:"
            f"{','.join(sorted(alert_rules[order['key']]['specified_staff_ids']))}:"
            f"{','.join(sorted(alert_rules[order['key']]['active_claim_staff_ids']))}"
        )
        for order in orders
    )

    snapshot = {
        "count": len(orders),
        "keys": [order["key"] for order in orders],
        "signature": signature,
        "_alert_rules": alert_rules,
    }

    if include_orders:
        snapshot["orders"] = orders

    return snapshot


def _dispatch_alert_keys_for_user(snapshot: dict, user: dict | None) -> list[str]:
    """Return orders that should actively alert this logged-in dispatch user.

    The first 60 seconds are a silent reading period for every worker. After
    unlock, a fully specified order only alerts its specified staff. If the
    order needs more staff than were specified, unrestricted slots remain
    alertable to everyone else until those slots are filled.
    """
    user_id = str((user or {}).get("id") or "").strip()
    alert_rules = snapshot.get("_alert_rules") or {}
    result: list[str] = []

    for key in snapshot.get("keys") or []:
        key = str(key)
        rule = alert_rules.get(key) or {}

        if bool(rule.get("acceptance_locked")):
            continue

        specified_set = {
            str(item).strip()
            for item in (rule.get("specified_staff_ids") or [])
            if str(item).strip()
        }

        if not specified_set:
            result.append(key)
            continue

        if user_id and user_id in specified_set:
            result.append(key)
            continue

        required_staff_count = max(
            1,
            int(rule.get("required_staff_count") or 0),
        )
        unrestricted_slots = max(
            0,
            required_staff_count - len(specified_set),
        )
        if unrestricted_slots <= 0:
            continue

        active_claim_staff_ids = [
            str(item).strip()
            for item in (rule.get("active_claim_staff_ids") or [])
            if str(item).strip()
        ]
        non_specified_active_count = sum(
            1
            for staff_id in active_claim_staff_ids
            if staff_id not in specified_set
        )

        if non_specified_active_count < unrestricted_slots:
            result.append(key)

    return result


def _public_dispatch_snapshot(snapshot: dict, user: dict | None) -> dict:
    return {
        **{
            key: value
            for key, value in snapshot.items()
            if key != "_alert_rules"
        },
        "alert_keys": _dispatch_alert_keys_for_user(snapshot, user),
    }


def _build_dispatch_event_snapshot() -> dict:
    return {
        **_dispatch_state_snapshot(include_orders=False),
        **_dispatch_presence_snapshot(),
    }


async def _shared_dispatch_event_snapshot() -> dict:
    """Reuse one compact DB snapshot across all SSE clients for one second."""
    global _dispatch_event_cache, _dispatch_event_cache_expires_at

    now = time.monotonic()
    cached = _dispatch_event_cache
    if cached is not None and now < _dispatch_event_cache_expires_at:
        return dict(cached)

    async with _dispatch_event_cache_lock:
        now = time.monotonic()
        cached = _dispatch_event_cache
        if cached is not None and now < _dispatch_event_cache_expires_at:
            return dict(cached)

        snapshot = await asyncio.to_thread(_build_dispatch_event_snapshot)
        _dispatch_event_cache = dict(snapshot)
        _dispatch_event_cache_expires_at = now + _DISPATCH_EVENT_CACHE_TTL_SECONDS
        return dict(snapshot)


@router.get("/dispatch/state")
async def dispatch_state(request: Request):
    user = request.session.get("user")
    if not user:
        return JSONResponse(
            {"ok": False, "error": "not_logged_in"},
            status_code=401,
        )

    if not can_use_dispatch(user):
        return JSONResponse(
            {"ok": False, "error": "forbidden"},
            status_code=403,
        )

    presence_online, support_presence_online = touch_dispatch_user_presence(user)
    state_snapshot, presence_snapshot = await asyncio.gather(
        asyncio.to_thread(_dispatch_state_snapshot, include_orders=True),
        asyncio.to_thread(_dispatch_presence_snapshot),
    )

    return {
        "ok": True,
        "presence_online": presence_online,
        "support_presence_online": support_presence_online,
        **presence_snapshot,
        **_public_dispatch_snapshot(state_snapshot, user),
    }


@router.get("/dispatch/events")
async def dispatch_events(request: Request):
    user = request.session.get("user")
    if not user:
        return JSONResponse(
            {"ok": False, "error": "not_logged_in"},
            status_code=401,
        )

    if not can_use_dispatch(user):
        return JSONResponse(
            {"ok": False, "error": "forbidden"},
            status_code=403,
        )

    async def event_stream():
        stream_started = time.monotonic()
        last_signature = None
        last_presence_touch = 0.0
        last_heartbeat = 0.0

        yield "retry: 3000\n\n"

        while True:
            if await request.is_disconnected():
                return

            now = time.monotonic()

            # StreamingResponse 已送出的 headers 無法在後續 heartbeat 更新 cookie。
            # 在 session 到期前主動收掉 SSE，EventSource 會依 retry 自動重連，
            # 新連線即可刷新登入 session。使用者不需要重新整理或重新登入。
            if (
                now - stream_started
                >= _DISPATCH_SSE_SESSION_REFRESH_SECONDS
            ):
                return

            if now - last_presence_touch >= 20:
                await asyncio.to_thread(touch_dispatch_user_presence, user)
                last_presence_touch = now

            snapshot = await _shared_dispatch_event_snapshot()
            public_snapshot = _public_dispatch_snapshot(snapshot, user)
            signature = snapshot["signature"]

            if last_signature is None or signature != last_signature:
                payload = {
                    "ok": True,
                    "initial": last_signature is None,
                    **public_snapshot,
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_signature = signature
                last_heartbeat = now
            elif now - last_heartbeat >= 15:
                heartbeat = {
                    "ok": True,
                    "heartbeat": True,
                    **public_snapshot,
                }
                yield f"data: {json.dumps(heartbeat, ensure_ascii=False)}\n\n"
                last_heartbeat = now

            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
