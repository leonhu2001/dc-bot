from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

APP_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

app = FastAPI(title="MW Worker Dashboard")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "title": "魔丸打手系統",
        },
    )


@app.get("/health")
async def health():
    return {
        "ok": True,
        "service": "mw-worker-dashboard",
    }