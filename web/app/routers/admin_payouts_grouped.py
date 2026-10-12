from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from web.app.routers.love_delta import router as love_delta_router
from web.app.routers.roulette import router as roulette_router
from web.app.services.love_delta_service import get_love_delta_context


router = APIRouter(tags=["admin-payouts-grouped-redirect"])


def _session_user_id(request: Request) -> str:
    user = request.session.get("user")
    if not isinstance(user, dict):
        return ""
    return str(user.get("id") or "").strip()


async def _love_delta_write_guard(request: Request) -> None:
    """Companions may only edit the shared guess; all scoring stays boss-owned."""
    method = request.method.upper()
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return

    path = request.url.path.rstrip("/")
    if path.endswith("/guess/companion"):
        return

    user_id = _session_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="請先登入。")

    raw_order_id = request.path_params.get("order_id")
    try:
        order_id = int(raw_order_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="訂單編號不正確。") from exc

    try:
        context = await run_in_threadpool(
            get_love_delta_context,
            user_id,
            order_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if str((context.get("viewer") or {}).get("role") or "") != "boss":
        raise HTTPException(
            status_code=403,
            detail="計分、扣分與攻略管理僅限老闆操作。",
        )


# main.py already mounts this lightweight compatibility router. Include the
# standalone fun-order feature routers here as well so their member/admin
# endpoints are registered without duplicating application bootstrap logic.
# This can be moved to direct main.py includes when the router registry is next
# consolidated.
router.include_router(roulette_router)
router.include_router(
    love_delta_router,
    dependencies=[Depends(_love_delta_write_guard)],
)


@router.get("/admin/payouts/grouped")
async def redirect_admin_payouts_grouped():
    return RedirectResponse("/admin/payouts/summary", status_code=303)


@router.post("/admin/payouts/grouped/status")
async def redirect_admin_payouts_grouped_status():
    return RedirectResponse("/admin/payouts/summary", status_code=303)
