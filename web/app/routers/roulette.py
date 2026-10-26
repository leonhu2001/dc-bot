from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from web.app.services import roulette_redraw_service as roulette_redraw_service
from web.app.services import roulette_service as roulette_service
from web.app.services.roulette_redraw_service import (
    ensure_redraw_tables,
    get_redraw_state,
    grant_redraw,
    prepare_redraw_if_credited,
)
from web.app.services.roulette_service import (
    DRAW_ALLOWED_STATUSES,
    draw_roulette,
    ensure_roulette_feature,
    get_roulette_context,
    normalize_bet,
    notify_ready_roulette_orders,
)


router = APIRouter(tags=["roulette"])
TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[1] / "templates")
)
_ROULETTE_READY_TASK: asyncio.Task | None = None


def _strict_roulette_identity(order: dict[str, Any]) -> bool:
    """A roulette order must match both rule metadata and its creation snapshot.

    Manager-created rule keys can be renamed or repurposed later.  The copied
    order item is creation-time data, so requiring both prevents a historical
    order from becoming roulette retroactively when a rule key is reused.
    """
    rule_key = str(order.get("order_rule_key") or "").strip()
    item_snapshot = str(order.get("item") or "").strip()
    return (
        rule_key in roulette_service.ROULETTE_RULE_KEYS
        and roulette_service.ROULETTE_ITEM_LABEL in item_snapshot
    )


# Roulette services and routes share one strict identity rule for this process.
roulette_service._is_roulette_order = _strict_roulette_identity


def _list_admin_roulette_orders_strict(*, limit: int = 100) -> list[dict[str, Any]]:
    ensure_redraw_tables()
    safe_limit = max(1, min(int(limit or 100), 250))
    keys = tuple(sorted(roulette_service.ROULETTE_RULE_KEYS))
    placeholders = ",".join("?" for _ in keys)

    with roulette_redraw_service._connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM web_orders
            WHERE order_rule_key IN ({placeholders})
              AND item LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (
                *keys,
                f"%{roulette_service.ROULETTE_ITEM_LABEL}%",
                safe_limit,
            ),
        ).fetchall()

    output: list[dict[str, Any]] = []
    for raw in rows:
        order = dict(raw)
        state = get_redraw_state(int(order["id"]))
        output.append(
            {
                "id": int(order["id"]),
                "order_no": str(order.get("bot_order_no") or f"WEB-{order['id']}"),
                "customer_name": str(
                    order.get("customer_display_name")
                    or order.get("customer_username")
                    or order.get("customer_discord_id")
                    or "未紀錄"
                ),
                "customer_discord_id": str(order.get("customer_discord_id") or ""),
                "status": str(order.get("status") or "").strip().lower(),
                "ticket_channel_id": str(order.get("ticket_channel_id") or ""),
                "final_draw": state["final_draw"],
                "remaining": state["remaining"],
                "total_granted": state["total_granted"],
                "attempt_count": state["attempt_count"],
                "history": state["history"],
                "grants": state["grants"],
            }
        )
    return output


# 只初始化輪盤資料表與舊誤建商品清理；正式商品設定仍完全由後台管理。
ensure_roulette_feature()
ensure_redraw_tables()


class RouletteDrawPayload(BaseModel):
    mode: str
    selection: Any


def _session_user(request: Request) -> dict | None:
    user = request.session.get("user")
    return user if isinstance(user, dict) else None


def _customer_id(user: dict | None) -> str:
    return str((user or {}).get("id") or "").strip()


def _admin_user(request: Request) -> dict | None:
    user = _session_user(request)
    if not user or not bool(user.get("is_admin")):
        return None
    return user


async def _roulette_ready_worker() -> None:
    while True:
        try:
            sent = await run_in_threadpool(notify_ready_roulette_orders)
            if sent:
                print(
                    f"[roulette] sent ready ticket prompts: {sent}",
                    flush=True,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(
                "[roulette] ready notification worker failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

        await asyncio.sleep(10)


@router.on_event("startup")
async def start_roulette_ready_worker() -> None:
    global _ROULETTE_READY_TASK
    ensure_roulette_feature()
    ensure_redraw_tables()
    if _ROULETTE_READY_TASK is None or _ROULETTE_READY_TASK.done():
        _ROULETTE_READY_TASK = asyncio.create_task(_roulette_ready_worker())


@router.on_event("shutdown")
async def stop_roulette_ready_worker() -> None:
    global _ROULETTE_READY_TASK
    if _ROULETTE_READY_TASK is None:
        return

    _ROULETTE_READY_TASK.cancel()
    try:
        await _ROULETTE_READY_TASK
    except asyncio.CancelledError:
        pass
    _ROULETTE_READY_TASK = None


@router.get("/me/orders/{order_id}/roulette")
async def member_roulette(request: Request, order_id: int):
    user = _session_user(request)
    customer_id = _customer_id(user)
    if not customer_id:
        next_path = quote(f"/me/orders/{int(order_id)}/roulette", safe="")
        return RedirectResponse(
            url=f"/auth/discord/login?next={next_path}",
            status_code=303,
        )

    try:
        context = await run_in_threadpool(
            get_roulette_context,
            customer_id,
            int(order_id),
        )
        redraw_state = await run_in_threadpool(
            get_redraw_state,
            int(order_id),
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="找不到這張訂單。")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    order_status = str(
        (context.get("order") or {}).get("status") or ""
    ).strip().lower()

    # 輪盤頁不是公開遊戲頁。只有這張輪盤趣味單本人，且訂單仍在
    # 進行中 / 存單中時才能進入；結案後由 Discord 與客服後台保留紀錄。
    if order_status not in DRAW_ALLOWED_STATUSES:
        raise HTTPException(
            status_code=404,
            detail="這張輪盤目前沒有開放。",
        )

    remaining = int(redraw_state.get("remaining") or 0)
    if remaining > 0 and context.get("draw") is not None:
        # 補發後保留舊結果於後台歷史，但前台回到可下注狀態。
        context["previous_draw"] = context["draw"]
        context["draw"] = None
        context["can_draw"] = True
        context["reason"] = f"客服已補發輪盤，目前剩餘 {remaining} 次可補抽。"

    return TEMPLATES.TemplateResponse(
        request=request,
        name="member_roulette.html",
        context={
            "title": "俄羅斯輪盤・保底抽取｜魔丸娛樂",
            "user": user,
            "redraw_remaining": remaining,
            **context,
        },
    )


@router.post("/me/orders/{order_id}/roulette/draw")
async def member_roulette_draw(
    request: Request,
    order_id: int,
    payload: RouletteDrawPayload,
):
    user = _session_user(request)
    customer_id = _customer_id(user)
    if not customer_id:
        raise HTTPException(status_code=401, detail="請先登入。")

    try:
        # 先完整驗證下注內容，再動補抽額度。避免異常 payload 消耗掉補發次數。
        normalize_bet(payload.mode, payload.selection)
        context = await run_in_threadpool(
            get_roulette_context,
            customer_id,
            int(order_id),
        )
        order_status = str(
            (context.get("order") or {}).get("status") or ""
        ).strip().lower()
        if order_status not in DRAW_ALLOWED_STATUSES:
            raise PermissionError("這張輪盤目前沒有開放。")

        await run_in_threadpool(
            prepare_redraw_if_credited,
            customer_id,
            int(order_id),
        )
        result = await run_in_threadpool(
            draw_roulette,
            customer_id,
            int(order_id),
            mode=payload.mode,
            selection=payload.selection,
        )
        redraw_state = await run_in_threadpool(
            get_redraw_state,
            int(order_id),
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="找不到這張訂單。")
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "ok": True,
        "draw": result,
        "remaining_redraws": int(redraw_state.get("remaining") or 0),
    }


@router.get("/admin/fun-orders")
async def admin_fun_orders(
    request: Request,
    message: str | None = None,
    error: str | None = None,
):
    user = _admin_user(request)
    if not user:
        return RedirectResponse(url="/service", status_code=303)

    orders = await run_in_threadpool(_list_admin_roulette_orders_strict)
    return TEMPLATES.TemplateResponse(
        request=request,
        name="admin_fun_orders.html",
        context={
            "title": "趣味單管理｜魔丸娛樂",
            "user": user,
            "orders": orders,
            "message": message,
            "error": error,
        },
    )


@router.get("/admin/roulette")
async def admin_roulette_legacy_redirect(
    message: str | None = None,
    error: str | None = None,
):
    query = []
    if message:
        query.append("message=" + quote(message, safe=""))
    if error:
        query.append("error=" + quote(error, safe=""))
    suffix = "?" + "&".join(query) if query else ""
    return RedirectResponse(url="/admin/fun-orders" + suffix, status_code=303)


@router.post("/admin/fun-orders/roulette/{order_id}/grant")
@router.post("/admin/roulette/{order_id}/grant")
async def admin_roulette_grant(
    request: Request,
    order_id: int,
    count: int = Form(default=1),
    reason: str = Form(default=""),
):
    user = _admin_user(request)
    if not user:
        return RedirectResponse(url="/service", status_code=303)

    try:
        result = await run_in_threadpool(
            grant_redraw,
            int(order_id),
            count=int(count),
            reason=reason,
            admin_user=user,
        )
    except (LookupError, ValueError) as exc:
        return RedirectResponse(
            url=f"/admin/fun-orders?error={quote(str(exc), safe='')}",
            status_code=303,
        )

    message = (
        f"已補發 {int(result['count'])} 次輪盤抽取，"
        f"目前剩餘 {int(result['remaining'])} 次。"
    )
    if result.get("notification_status") == "failed":
        message += " Discord 提示發送失敗，但補發次數已生效。"

    return RedirectResponse(
        url=f"/admin/fun-orders?message={quote(message, safe='')}",
        status_code=303,
    )