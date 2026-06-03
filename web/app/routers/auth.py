from urllib.parse import urlencode
import secrets

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from web.app.config import config
from web.app.services.discord_service import get_dashboard_access, get_member_role_ids

router = APIRouter(prefix="/auth", tags=["auth"])

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
DISCORD_TOKEN_URL = f"{DISCORD_API_BASE}/oauth2/token"


@router.get("/discord/login")
async def discord_login(request: Request):
    if not config.DISCORD_CLIENT_ID:
        raise HTTPException(status_code=500, detail="DISCORD_CLIENT_ID is not configured")

    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state

    params = {
        "client_id": config.DISCORD_CLIENT_ID,
        "redirect_uri": config.DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify",
        "prompt": "none",
        "state": state,
    }

    return RedirectResponse(f"{DISCORD_AUTHORIZE_URL}?{urlencode(params)}")


@router.get("/discord/callback")
async def discord_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        raise HTTPException(status_code=400, detail=f"Discord OAuth error: {error}")

    if not code:
        raise HTTPException(status_code=400, detail="Missing Discord OAuth code")

    expected_state = request.session.pop("oauth_state", None)
    if expected_state is not None:
        if not state or state != expected_state:
            raise HTTPException(status_code=400, detail="Invalid Discord OAuth state")

    async with httpx.AsyncClient(timeout=15) as client:
        token_response = await client.post(
            f"{DISCORD_API_BASE}/oauth2/token",
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
        )

        if token_response.status_code != 200:
            raise HTTPException(
                status_code=400,
                detail=f"Discord token exchange failed: {token_response.status_code} {token_response.text}",
            )

        token_data = token_response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            raise HTTPException(status_code=400, detail="Missing Discord access token")

        user_response = await client.get(
            f"{DISCORD_API_BASE}/users/@me",
            headers={
                "Authorization": f"Bearer {access_token}",
            },
        )

        if user_response.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch Discord user")

        user_data = user_response.json()

    discord_id = str(user_data.get("id") or "")
    username = user_data.get("username") or ""
    global_name = user_data.get("global_name") or username
    avatar = user_data.get("avatar")

    if not discord_id:
        raise HTTPException(status_code=400, detail="Missing Discord user id")

    request.session["discord_user"] = {
        "id": discord_id,
        "username": username,
        "global_name": global_name,
        "avatar": avatar,
    }

    return RedirectResponse(url="/")

@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")