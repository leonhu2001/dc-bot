from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from web.app.routers.roulette import router as roulette_router


router = APIRouter(tags=["admin-payouts-grouped-redirect"])

# main.py already mounts this lightweight compatibility router. Include the
# roulette feature router here as well so its member/admin endpoints and startup
# notification worker are actually registered without duplicating application
# bootstrap logic. This can be moved to a direct main.py include when the router
# registry is next consolidated.
router.include_router(roulette_router)


@router.get("/admin/payouts/grouped")
async def redirect_admin_payouts_grouped():
    return RedirectResponse("/admin/payouts/summary", status_code=303)


@router.post("/admin/payouts/grouped/status")
async def redirect_admin_payouts_grouped_status():
    return RedirectResponse("/admin/payouts/summary", status_code=303)
