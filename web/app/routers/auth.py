from urllib.parse import urlencode

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from web.app.config import config
from web.app.services.discord_service import get_dashboard_access, get_member_role_ids

router = APIRouter(prefix="/auth", tags=["auth"])

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = f"{DISCORD_API_BASE}/oauth2/token"


@router.get("/discord/login")
async def discord_login():
    if not config.DISCORD_CLIENT_ID:
        raise HTTPException(status_code=500, detail="DISCORD_CLIENT_ID is not configured")

    params = {
        "client_id": config.DISCORD_CLIENT_ID,
        "redirect_uri": config.DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify",
        "prompt": "none",
    }

    return RedirectResponse(f"{DISCORD_AUTHORIZE_URL}?{urlencode(params)}")


@router.get("/discord/callback")
async def discord_callback(request: Request, code: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(status_code=400, detail=f"Discord OAuth error: {error}")

    if not code:
        raise HTTPException(status_code=400, detail="Missing Discord OAuth code")

    token_response = requests.post(
        DISCORD_TOKEN_URL,
        data={
            "client_id": config.DISCORD_CLIENT_ID,
            "client_secret": config.DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.DISCORD_REDIRECT_URI,
        },
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=15,
    )

    if token_response.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to exchange OAuth code: {token_response.text}",
        )

    token_data = token_response.json()
    access_token = token_data["access_token"]

    user_response = requests.get(
        f"{DISCORD_API_BASE}/users/@me",
        headers={
            "Authorization": f"Bearer {access_token}",
        },
        timeout=15,
    )

    if user_response.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to fetch Discord user: {user_response.text}",
        )

    user_data = user_response.json()
    discord_user_id = str(user_data.get("id"))

    role_ids = get_member_role_ids(discord_user_id)
    access = get_dashboard_access(role_ids)

    request.session["user"] = {
        "id": discord_user_id,
        "username": user_data.get("username"),
        "global_name": user_data.get("global_name"),
        "avatar": user_data.get("avatar"),
        "role_ids": role_ids,
        "is_admin": access["is_admin"],
        "is_worker": access["is_worker"],
    }

    if access["is_admin"]:
        return RedirectResponse("/admin")

    if access["is_worker"]:
        return RedirectResponse("/dispatch")

    return RedirectResponse("/no-access")


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")