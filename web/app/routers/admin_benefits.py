from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from services.promotion_benefits import (
    EFFECT_FIXED_CASH,
    EFFECT_FREE_GAMES,
    EFFECT_FREE_HOURS,
    EFFECT_FREE_ORDER,
    EFFECT_PERCENT,
    EFFECT_WAIVE_SPECIFY,
    FUNDING_SHARED,
    FUNDING_STORE,
    create_template,
    ensure_promotion_benefit_tables,
    get_template,
    issue_benefit,
    list_issued_benefits,
    list_templates,
    revoke_issued_benefit,
)


router = APIRouter(tags=["admin-benefits"])
ROOT = Path(__file__).resolve().parents[3]
WEB_DB = ROOT / "web_dashboard.db"
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _admin(request: Request) -> dict | None:
    user = request.session.get("user")
    if not isinstance(user, dict) or not user.get("is_admin"):
        return None
    return user


def _customer_options(limit: int = 400) -> list[dict]:
    if not WEB_DB.exists():
        return []
    try:
        with sqlite3.connect(WEB_DB, timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='web_orders' LIMIT 1"
            ).fetchone()
            if exists is None:
                return []
            rows = conn.execute(
                """
                SELECT customer_discord_id,
                       MAX(COALESCE(customer_display_name, customer_discord_id)) AS display_name,
                       MAX(COALESCE(updated_at, created_at)) AS last_seen
                FROM web_orders
                WHERE COALESCE(customer_discord_id, '') <> ''
                GROUP BY customer_discord_id
                ORDER BY last_seen DESC
                LIMIT ?
                """,
                (max(1, min(1000, int(limit or 400))),),
            ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []


def _redirect(message: str = "", *, customer_id: str = "") -> RedirectResponse:
    params = {}
    if message:
        params["message"] = message
    if customer_id:
        params["customer"] = customer_id
    query = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"/admin/benefits{query}", status_code=303)


@router.get("/admin/benefits")
async def benefits_center(request: Request, customer: str = "", message: str = ""):
    user = _admin(request)
    if user is None:
        return RedirectResponse(url="/", status_code=303)

    ensure_promotion_benefit_tables()
    issued = list_issued_benefits(limit=300)
    effect_labels = {
        EFFECT_FIXED_CASH: "固定金額抵免",
        EFFECT_PERCENT: "百分比折扣",
        EFFECT_FREE_HOURS: "折抵時數",
        EFFECT_FREE_GAMES: "折抵局數",
        EFFECT_WAIVE_SPECIFY: "免指定費",
        EFFECT_FREE_ORDER: "整單免單",
    }
    funding_labels = {
        FUNDING_SHARED: "共同分攤",
        FUNDING_STORE: "店家吸收",
    }
    return templates.TemplateResponse(
        request=request,
        name="admin_benefits.html",
        context={
            "title": "優惠與福利｜魔丸娛樂",
            "user": user,
            "templates": list_templates(include_inactive=True),
            "issued": issued,
            "customers": _customer_options(),
            "selected_customer": str(customer or "").strip(),
            "message": str(message or ""),
            "effect_labels": effect_labels,
            "funding_labels": funding_labels,
            "effect_kinds": [
                (EFFECT_FIXED_CASH, "固定金額抵免"),
                (EFFECT_PERCENT, "百分比折扣"),
                (EFFECT_FREE_HOURS, "折抵小時"),
                (EFFECT_FREE_GAMES, "折抵局數"),
                (EFFECT_WAIVE_SPECIFY, "免指定費"),
                (EFFECT_FREE_ORDER, "整單免單"),
            ],
        },
    )


@router.post("/admin/benefits/templates")
async def create_benefit_template(request: Request):
    user = _admin(request)
    if user is None:
        return RedirectResponse(url="/", status_code=303)
    if not bool(user.get("is_manager")):
        return _redirect("只有管理員可以建立或修改福利模板。")

    form = await request.form()
    effect_kind = str(form.get("effect_kind") or EFFECT_FIXED_CASH)
    funding = str(form.get("funding") or FUNDING_STORE)
    high_risk = effect_kind == EFFECT_FREE_ORDER or str(form.get("high_risk") or "") == "1"
    try:
        template_id = create_template(
            name=str(form.get("name") or ""),
            rules={
                "effect_kind": effect_kind,
                "effect_value": form.get("effect_value") or 0,
                "funding": funding,
                "min_order_amount": form.get("min_order_amount") or 0,
                "scope_type": form.get("scope_type") or "all",
                "scope_values": str(form.get("scope_values") or ""),
                "excluded_rule_keys": str(form.get("excluded_rule_keys") or ""),
                "valid_days": form.get("valid_days") or None,
                "usage_limit": form.get("usage_limit") or 1,
                "consume_mode": form.get("consume_mode") or "one_shot",
                "seat_mode": form.get("seat_mode") or "one_seat",
                "include_specify_fee": str(form.get("include_specify_fee") or "") == "1",
                "allow_vip_discount": str(form.get("allow_vip_discount") or "") == "1",
                "allow_points": False,
                "is_high_risk": high_risk,
            },
            actor_discord_id=user.get("id"),
        )
    except ValueError as exc:
        return _redirect(str(exc))
    return _redirect(f"已建立福利模板 #{template_id}。")


@router.post("/admin/benefits/issue")
async def issue_customer_benefit(request: Request):
    user = _admin(request)
    if user is None:
        return RedirectResponse(url="/", status_code=303)

    form = await request.form()
    customer_id = str(form.get("customer_discord_id") or "").strip()
    template_id = str(form.get("template_id") or "").strip()
    template = get_template(template_id) if template_id else None
    if template is None:
        return _redirect("請選擇有效的福利模板。", customer_id=customer_id)
    if bool(template.get("is_high_risk")) and not bool(user.get("is_manager")):
        return _redirect("這是高風險福利模板，只能由管理員發放。", customer_id=customer_id)

    try:
        issued_id = issue_benefit(
            template_id=template_id,
            customer_discord_id=customer_id,
            actor_discord_id=user.get("id"),
            note=str(form.get("note") or ""),
            expires_at=str(form.get("expires_at") or "").strip() or None,
        )
    except ValueError as exc:
        return _redirect(str(exc), customer_id=customer_id)
    return _redirect(f"已發放福利 #{issued_id}。", customer_id=customer_id)


@router.post("/admin/benefits/issued/{issued_id}/revoke")
async def revoke_customer_benefit(request: Request, issued_id: int):
    user = _admin(request)
    if user is None:
        return RedirectResponse(url="/", status_code=303)
    form = await request.form()
    try:
        revoke_issued_benefit(
            issued_id,
            actor_discord_id=user.get("id"),
            reason=str(form.get("reason") or "管理端撤回"),
        )
    except ValueError as exc:
        return _redirect(str(exc))
    return _redirect(f"已撤回福利 #{issued_id}。")
