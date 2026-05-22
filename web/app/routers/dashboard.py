from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["dashboard"])

templates = Jinja2Templates(directory="web/app/templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    discord_id: str = "",
    username: str = "",
    global_name: str = "",
    is_admin: bool = False,
    is_worker: bool = False,
):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "discord_id": discord_id,
            "username": username,
            "global_name": global_name,
            "is_admin": is_admin,
            "is_worker": is_worker,
        },
    )