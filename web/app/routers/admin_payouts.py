from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from web.app.routers.internal_transfers import router as employee_internal_transfers_router
from web.app.routers.roulette import router as roulette_router


router = APIRouter(tags=["admin-payouts-redirect"])
router.include_router(employee_internal_transfers_router)
router.include_router(roulette_router)


@router.get("/admin/payouts")
async def redirect_admin_payouts():
    return RedirectResponse("/admin/payouts/summary", status_code=303)