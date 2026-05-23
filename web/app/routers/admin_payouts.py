from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(tags=["admin_payouts"])


@router.get("/admin/payouts")
async def admin_payouts_redirect():
    return RedirectResponse(url="/admin/payouts/grouped", status_code=303)
