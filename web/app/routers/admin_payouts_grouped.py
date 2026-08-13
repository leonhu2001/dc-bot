from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(tags=["admin-payouts-grouped-redirect"])


@router.get("/admin/payouts/grouped")
async def redirect_admin_payouts_grouped():
    return RedirectResponse("/admin/payouts/summary", status_code=303)


@router.post("/admin/payouts/grouped/status")
async def redirect_admin_payouts_grouped_status():
    return RedirectResponse("/admin/payouts/summary", status_code=303)
