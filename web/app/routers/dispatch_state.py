import asyncio
import json
import sqlite3
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from services.dispatch_presence import (
    count_online_dispatch_workers,
    get_online_dispatch_support_ids,
)
from web.app.config import config
from web.app.services.dispatch_access import (
    can_use_dispatch,
    touch_dispatch_user_presence,
)
from web.app.services.dispatch_claim_access import (
    dispatch_user_role_ids,
    evaluate_dispatch_claim_access,
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


def _dispatch_order_rows() -> list[dict]:
    conn = sqlite3.connect(get_sqlite_path())
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
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
                m.order_rule_key,
                m.required_staff_count AS acceptance_required_staff_count,
                m.min_protector_count,
                m.allowed_role_ids_json,
                m.required_game_role_ids_json,
                m.specified_staff_ids_json,
                m.status AS acceptance_status,
                m.created_at AS acceptance_created_at
            FROM web_orders o
            LEFT JOIN order_acceptance_meta m ON m.order_id = o.id
            WHERE o.status IN ({_VISIBLE_STATUS_PLACEHOLDERS})
            ORDER BY o.id ASC
            """,
            _VISIBLE_STATUS_VALUES,
        ).fetchall()

        claim_rows = conn.execute(
            """
            SELECT
                order_id,
                staff_discord_id,
                staff_role_ids_json
            FROM order_acceptance_claims
            WHERE is_active = 1
            ORDER BY order_id ASC, claimed_at ASC, id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    claims_by_order: dict[int, list[dict]] = {}
    for row in claim_rows:
        order_id = int(row["order_id"])
        claims_by_order.setdefault(order_id, []).append(
            {
                "staff_discord_id": str(row["staff_discord_id"] or ""),
                "staff_role_ids_json": row["staff_role_ids_json"],
            }
        )

    result = []
    for row in rows:
        data = dict(row)
        data["active_claim_rows"] = claims_by_order.get(int(row["id"]), [])
        result.append(data)

    return result


def _dispatch_state_snapshot(*, include_orders: bool) -> dict:
    rows = _dispatch_order_rows()
    orders = []
    alert_rules: dict[str, dict] = {}

    for row in rows:
        order_key = str(row["bot_order_no"] or f"WEB-{row['id']}")
        active_rows = list(row.get("active_claim_rows") or [])
        meta = {
            "order_rule_key": row.get("order_rule_key"),
            "required_staff_count": row.get("acceptance_required_staff_count"),
            "min_protector_count": row.get("min_protector_count"),
            "allowed_role_ids_json": row.get("allowed_role_ids_json"),
            "required_game_role_ids_json": row.get("required_game_role_ids_json"),
            "specified_staff_ids_json": row.get("specified_staff_ids_json"),
            "status": row.get("acceptance_status"),
            "created_at": row.get("acceptance_created_at"),
        }

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
            }
        )
        alert_rules[order_key] = {
            "order_id": int(row["id"]),
            "order_status": str(row["status"] or ""),
            "meta": meta,
            "active_rows": active_rows,
        }

    signature_parts = []
    for order in orders:
        rule = alert_rules[order["key"]]
        meta = rule["meta"]
        claim_signature = ",".join(
            sorted(
                f"{claim.get('staff_discord_id','')}:{claim.get('staff_role_ids_json') or ''}"
                for claim in rule["active_rows"]
            )
        )
        signature_parts.append(
            f"{order['id']}:{order['key']}:{order['updated_at']}:"
            f"{order['amount']}:{order['quantity']}:{order['status']}:"
            f"{meta.get('required_staff_count') or 0}:"
            f"{meta.get('min_protector_count') or 0}:"
            f"{meta.get('allowed_role_ids_json') or ''}:"
            f"{meta.get('required_game_role_ids_json') or ''}:"
            f"{meta.get('specified_staff_ids_json') or ''}:"
            f"{meta.get('created_at') or ''}:{claim_signature}"
        )

    snapshot = {
        "count": len(orders),
        "keys": [order["key"] for order in orders],
        "signature": "|".join(signature_parts),
        "_alert_rules": alert_rules,
    }

    if include_orders:
        snapshot["orders"] = orders

    return snapshot


def _dispatch_claim_access_for_user(snapshot: dict, user: dict | None) -> dict[str, dict]:
    user_id = str((user or {}).get("id") or "").strip()
    role_ids = dispatch_user_role_ids(user)
    alert_rules = snapshot.get("_alert_rules") or {}
    result: dict[str, dict] = {}

    for key in snapshot.get("keys") or []:
        key = str(key)
        rule = alert_rules.get(key) or {}
        result[key] = evaluate_dispatch_claim_access(
            meta=dict(rule.get("meta") or {}),
            active_rows=list(rule.get("active_rows") or []),
            order_status=str(rule.get("order_status") or ""),
            user_id=user_id,
            user_role_ids=role_ids,
        )

    return result


def _dispatch_alert_keys_for_user(snapshot: dict, user: dict | None) -> list[str]:
    """Only alert when this user can successfully claim the order right now.

    The sound therefore has one meaning: the logged-in user is eligible and the
    current time/reserved-slot/protector rules all allow an immediate claim.
    Specified staff can bypass the first 60 seconds; everybody else becomes
    alertable only after the public lock expires.
    """
    access_map = _dispatch_claim_access_for_user(snapshot, user)
    return [
        str(key)
        for key in snapshot.get("keys") or []
        if bool((access_map.get(str(key)) or {}).get("allowed"))
    ]


def _public_dispatch_snapshot(snapshot: dict, user: dict | None) -> dict:
    access_map = _dispatch_claim_access_for_user(snapshot, user)
    public_access = {
        key: {
            "allowed": bool(value.get("allowed")),
            "reason": str(value.get("reason") or ""),
            "is_specified": bool(value.get("is_specified")),
            "lock_active": bool(value.get("lock_active")),
            "unlock_at_epoch_ms": value.get("unlock_at_epoch_ms"),
        }
        for key, value in access_map.items()
    }

    return {
        **{
            key: value
            for key, value in snapshot.items()
            if key != "_alert_rules"
        },
        "alert_keys": [
            str(key)
            for key in snapshot.get("keys") or []
            if bool((access_map.get(str(key)) or {}).get("allowed"))
        ],
        "claim_access": public_access,
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
        last_public_signature = None
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
            alert_signature = ",".join(public_snapshot.get("alert_keys") or [])
            public_signature = f"{snapshot['signature']}|alerts:{alert_signature}"

            if last_public_signature is None or public_signature != last_public_signature:
                payload = {
                    "ok": True,
                    "initial": last_public_signature is None,
                    **public_snapshot,
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_public_signature = public_signature
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
