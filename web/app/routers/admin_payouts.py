from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(tags=["admin-payouts-redirect"])


@router.get("/admin/payouts")
async def redirect_admin_payouts():
    return RedirectResponse("/admin/payouts/summary", status_code=303)
