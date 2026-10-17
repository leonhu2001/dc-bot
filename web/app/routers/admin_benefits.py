from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from services.issued_benefits import (
    EFFECT_FIXED_CASH,
    EFFECT_FULL_ORDER,
    EFFECT_PERCENT,
    EFFECT_SERVICE_GAMES,
    EFFECT_SERVICE_HOURS,
    EFFECT_WAIVE_FEE,
    create_benefit_template,
    describe_rules,
    get_benefit_template,
    issue_benefit,
    list_benefit_templates,
    list_issued_benefits,
    revoke_issued_benefit,
    set_benefit_template_active,
)
from services.order_discounts import FUNDING_SHARED, FUNDING_STORE
from web.app.routers.admin_staff import require_admin


router = APIRouter(prefix="/admin/benefit-center", tags=["admin-benefits"])
templates = Jinja2Templates(directory="web/app/templates")
ROOT = Path(__file__).resolve().parents[3]
WEB_DB = ROOT / "web_dashboard.db"


def _actor_id(user: dict) -> str:
    return str(user.get("id") or "").strip()


def _redirect(*, ok: str | None = None, error: str | None = None, customer_id: str = ""):
    parts = []
    if customer_id:
        parts.append("customer_id=" + quote(str(customer_id), safe=""))
    if ok:
        parts.append("ok=" + quote(str(ok), safe=""))
    if error:
        parts.append("error=" + quote(str(error), safe=""))
    suffix = "?" + "&".join(parts) if parts else ""
    return RedirectResponse("/admin/benefit-center" + suffix, status_code=303)


def _csv(value: str | None) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _rules_from_form(
    *,
    effect_type: str,
    funding: str,
    amount: int,
    percent_off: float,
    service_hours: float,
    service_games: int,
    minimum_order_amount: int,
    maximum_discount_amount: int,
    max_uses: int,
    include_specify_fee: bool,
    manager_only: bool,
    rule_keys: str,
    categories: str,
    excluded_rule_keys: str,
    excluded_categories: str,
) -> dict:
    return {
        "effect_type": str(effect_type),
        "funding": str(funding),
        "amount": int(amount or 0),
        "percent_off": float(percent_off or 0),
        "service_hours": float(service_hours or 0),
        "service_games": int(service_games or 0),
        "minimum_order_amount": int(minimum_order_amount or 0),
        "maximum_discount_amount": int(maximum_discount_amount or 0),
        "max_uses": max(1, int(max_uses or 1)),
        "unused_balance_policy": "forfeit",
        "include_specify_fee": bool(include_specify_fee),
        "exclusive_coupon": True,
        "allow_vip_percent": True,
        "manager_only": bool(manager_only),
        "rule_keys": _csv(rule_keys),
        "categories": _csv(categories),
        "excluded_rule_keys": _csv(excluded_rule_keys),
        "excluded_categories": _csv(excluded_categories),
    }


def _customer_names(customer_ids: list[str]) -> dict[str, str]:
    ids = list(dict.fromkeys(str(value).strip() for value in customer_ids if str(value).strip()))
    if not ids or not WEB_DB.exists():
        return {}
    try:
        with sqlite3.connect(WEB_DB, timeout=10) as conn:
            conn.row_factory = sqlite3.Row
            cols = {str(row[1]) for row in conn.execute("PRAGMA table_info(web_orders)").fetchall()}
            if "customer_discord_id" not in cols:
                return {}
            name_col = next(
                (
                    col
                    for col in (
                        "customer_display_name",
                        "customer_name",
                        "customer_nickname",
                        "customer_username",
                    )
                    if col in cols
                ),
                None,
            )
            if not name_col:
                return {}
            placeholders = ",".join("?" for _ in ids)
            rows = conn.execute(
                f"""
                SELECT customer_discord_id, {name_col} AS display_name, MAX(id) AS latest_id
                FROM web_orders
                WHERE customer_discord_id IN ({placeholders})
                  AND {name_col} IS NOT NULL
                  AND TRIM({name_col}) != ''
                GROUP BY customer_discord_id
                """,
                ids,
            ).fetchall()
            return {
                str(row["customer_discord_id"]): str(row["display_name"] or "").strip()
                for row in rows
                if str(row["customer_discord_id"] or "").strip()
            }
    except sqlite3.Error:
        return {}


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def benefit_center(
    request: Request,
    customer_id: str = Query(default=""),
    status: str = Query(default=""),
):
    user = require_admin(request)
    if not user:
        return RedirectResponse("/admin", status_code=303)

    template_rows = list_benefit_templates(include_inactive=True)
    issued_rows = list_issued_benefits(
        customer_id=customer_id or None,
        status=status or None,
        limit=300,
    )
    names = _customer_names([str(row.get("customer_id") or "") for row in issued_rows])

    for row in template_rows:
        row["summary"] = describe_rules(row.get("rules") or {})
    for row in issued_rows:
        row["summary"] = describe_rules(row.get("rules") or {})
        row["customer_display_name"] = names.get(str(row.get("customer_id") or ""), "")

    return templates.TemplateResponse(
        request=request,
        name="admin_benefit_center.html",
        context={
            "title": "優惠與福利",
            "user": user,
            "templates": template_rows,
            "issued": issued_rows,
            "customer_id": customer_id,
            "status_filter": status,
            "ok": request.query_params.get("ok"),
            "error": request.query_params.get("error"),
            "effect_types": [
                (EFFECT_FIXED_CASH, "固定金額折抵"),
                (EFFECT_PERCENT, "百分比折扣"),
                (EFFECT_SERVICE_HOURS, "免費時數"),
                (EFFECT_SERVICE_GAMES, "免費局數"),
                (EFFECT_WAIVE_FEE, "免指定費"),
                (EFFECT_FULL_ORDER, "整單免單"),
            ],
            "funding_types": [
                (FUNDING_STORE, "店家全額吸收（打手／客服不受影響）"),
                (FUNDING_SHARED, "共同分攤（降低分潤基數）"),
            ],
        },
    )


@router.post("/templates")
async def create_template(
    request: Request,
    name: str = Form(...),
    description: str = Form(default=""),
    effect_type: str = Form(default=EFFECT_FIXED_CASH),
    funding: str = Form(default=FUNDING_STORE),
    amount: int = Form(default=0),
    percent_off: float = Form(default=0),
    service_hours: float = Form(default=0),
    service_games: int = Form(default=0),
    minimum_order_amount: int = Form(default=0),
    maximum_discount_amount: int = Form(default=0),
    max_uses: int = Form(default=1),
    include_specify_fee: bool = Form(default=False),
    manager_only: bool = Form(default=False),
    rule_keys: str = Form(default=""),
    categories: str = Form(default=""),
    excluded_rule_keys: str = Form(default=""),
    excluded_categories: str = Form(default=""),
):
    user = require_admin(request)
    if not user:
        return RedirectResponse("/admin", status_code=303)
    if not user.get("is_manager"):
        return _redirect(error="只有總管可以建立或修改福利模板。")

    try:
        rules = _rules_from_form(
            effect_type=effect_type,
            funding=funding,
            amount=amount,
            percent_off=percent_off,
            service_hours=service_hours,
            service_games=service_games,
            minimum_order_amount=minimum_order_amount,
            maximum_discount_amount=maximum_discount_amount,
            max_uses=max_uses,
            include_specify_fee=include_specify_fee,
            manager_only=manager_only,
            rule_keys=rule_keys,
            categories=categories,
            excluded_rule_keys=excluded_rule_keys,
            excluded_categories=excluded_categories,
        )
        template_id = create_benefit_template(
            name=name,
            description=description,
            rules=rules,
            actor_id=_actor_id(user),
        )
    except ValueError as exc:
        return _redirect(error=str(exc))

    return _redirect(ok=f"福利模板 #{template_id} 已建立。")


@router.post("/templates/{template_id}/toggle")
async def toggle_template(
    request: Request,
    template_id: int,
    is_active: int = Form(...),
):
    user = require_admin(request)
    if not user:
        return RedirectResponse("/admin", status_code=303)
    if not user.get("is_manager"):
        return _redirect(error="只有總管可以停用或啟用福利模板。")
    try:
        set_benefit_template_active(
            template_id,
            is_active=bool(int(is_active)),
            actor_id=_actor_id(user),
        )
    except ValueError as exc:
        return _redirect(error=str(exc))
    return _redirect(ok="模板狀態已更新。")


@router.post("/issue")
async def issue_from_template(
    request: Request,
    customer_id: str = Form(...),
    template_id: int = Form(...),
    expires_in_days: int = Form(default=30),
    reason: str = Form(default=""),
):
    user = require_admin(request)
    if not user:
        return RedirectResponse("/admin", status_code=303)

    template = get_benefit_template(template_id)
    if template is None:
        return _redirect(error="找不到福利模板。", customer_id=customer_id)
    if bool((template.get("rules") or {}).get("manager_only")) and not user.get("is_manager"):
        return _redirect(error="這個高風險模板只能由總管發放。", customer_id=customer_id)

    try:
        benefit_id = issue_benefit(
            customer_id=customer_id,
            actor_id=_actor_id(user),
            template_id=template_id,
            reason=reason,
            expires_in_days=(None if int(expires_in_days or 0) <= 0 else int(expires_in_days)),
        )
    except ValueError as exc:
        return _redirect(error=str(exc), customer_id=customer_id)

    return _redirect(ok=f"福利券 #{benefit_id} 已發放。", customer_id=customer_id)


@router.post("/issued/{benefit_id}/revoke")
async def revoke_benefit(
    request: Request,
    benefit_id: int,
    customer_id: str = Form(default=""),
    reason: str = Form(default=""),
):
    user = require_admin(request)
    if not user:
        return RedirectResponse("/admin", status_code=303)
    try:
        revoke_issued_benefit(
            benefit_id,
            actor_id=_actor_id(user),
            reason=reason,
        )
    except ValueError as exc:
        return _redirect(error=str(exc), customer_id=customer_id)
    return _redirect(ok=f"福利券 #{benefit_id} 已撤回。", customer_id=customer_id)
