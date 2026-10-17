from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from services.order_product_status import is_order_product_active
from services.order_rules import CATEGORY_LABELS, ORDER_RULES
from services.promotion_benefit_admin import update_template
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
from services.promotion_benefit_presentation import (
    build_benefit_grant_dm,
    list_customer_promotion_benefits,
)
from web.app.services.discord_service import send_direct_message


router = APIRouter(tags=["admin-benefits"])
ROOT = Path(__file__).resolve().parents[3]
WEB_DB = ROOT / "web_dashboard.db"
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Historical-only categories should not clutter the benefit picker.
_HIDDEN_BENEFIT_CATEGORIES = {"general", "basic", "fun"}


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


def _benefit_catalog_options() -> tuple[list[dict], list[dict]]:
    rules: list[dict] = []
    used_categories: set[str] = set()

    for rule_key, rule in ORDER_RULES.items():
        category = str(getattr(rule, "category", "") or "").strip()
        if category in _HIDDEN_BENEFIT_CATEGORIES:
            continue
        if not is_order_product_active(rule_key):
            continue
        used_categories.add(category)
        rules.append(
            {
                "key": str(rule_key),
                "label": str(getattr(rule, "label", rule_key) or rule_key),
                "category": category,
                "category_label": CATEGORY_LABELS.get(category, category),
            }
        )

    categories = [
        {"key": key, "label": CATEGORY_LABELS.get(key, key)}
        for key in CATEGORY_LABELS
        if key in used_categories and key not in _HIDDEN_BENEFIT_CATEGORIES
    ]
    categories.sort(key=lambda item: (item["label"], item["key"]))
    rules.sort(key=lambda item: (item["category_label"], item["label"], item["key"]))
    return categories, rules


def _template_rules_from_form(form) -> dict:
    scope_type = str(form.get("scope_type") or "all").strip()
    if scope_type == "category":
        scope_values = [str(value) for value in form.getlist("scope_category_values")]
    elif scope_type == "rule":
        scope_values = [str(value) for value in form.getlist("scope_rule_values")]
    else:
        scope_values = []

    effect_kind = str(form.get("effect_kind") or EFFECT_FIXED_CASH)
    high_risk = (
        effect_kind == EFFECT_FREE_ORDER
        or str(form.get("high_risk") or "") == "1"
    )
    return {
        "effect_kind": effect_kind,
        "effect_value": form.get("effect_value") or 0,
        "funding": str(form.get("funding") or FUNDING_STORE),
        "min_order_amount": form.get("min_order_amount") or 0,
        "scope_type": scope_type,
        "scope_values": scope_values,
        "excluded_rule_keys": [
            str(value) for value in form.getlist("excluded_rule_keys")
        ],
        "valid_days": form.get("valid_days") or None,
        "usage_limit": form.get("usage_limit") or 1,
        "consume_mode": form.get("consume_mode") or "one_shot",
        "seat_mode": form.get("seat_mode") or "one_seat",
        "include_specify_fee": str(form.get("include_specify_fee") or "") == "1",
        "allow_vip_discount": str(form.get("allow_vip_discount") or "") == "1",
        "allow_points": False,
        "is_high_risk": high_risk,
    }


def _redirect(
    message: str = "",
    *,
    customer_id: str = "",
    edit_template: int | str | None = None,
) -> RedirectResponse:
    params = {}
    if message:
        params["message"] = message
    if customer_id:
        params["customer"] = customer_id
    if edit_template:
        params["edit_template"] = str(edit_template)
    query = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"/admin/benefits{query}", status_code=303)


@router.get("/admin/benefits")
async def benefits_center(
    request: Request,
    customer: str = "",
    message: str = "",
    edit_template: int | None = None,
):
    user = _admin(request)
    if user is None:
        return RedirectResponse(url="/", status_code=303)

    ensure_promotion_benefit_tables()
    issued = list_issued_benefits(limit=300)
    template_rows = list_templates(include_inactive=True)
    editing_template = get_template(edit_template) if edit_template else None
    category_options, rule_options = _benefit_catalog_options()

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
            "templates": template_rows,
            "editing_template": editing_template,
            "issued": issued,
            "customers": _customer_options(),
            "selected_customer": str(customer or "").strip(),
            "message": str(message or ""),
            "effect_labels": effect_labels,
            "funding_labels": funding_labels,
            "category_options": category_options,
            "rule_options": rule_options,
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
    try:
        template_id = create_template(
            name=str(form.get("name") or ""),
            rules=_template_rules_from_form(form),
            actor_discord_id=user.get("id"),
        )
    except ValueError as exc:
        return _redirect(str(exc))
    return _redirect(f"已建立福利模板 #{template_id}。")


@router.post("/admin/benefits/templates/{template_id}")
async def update_benefit_template(request: Request, template_id: int):
    user = _admin(request)
    if user is None:
        return RedirectResponse(url="/", status_code=303)
    if not bool(user.get("is_manager")):
        return _redirect("只有管理員可以建立或修改福利模板。")

    form = await request.form()
    try:
        result = update_template(
            template_id,
            name=str(form.get("name") or ""),
            rules=_template_rules_from_form(form),
            is_active=str(form.get("is_active") or "") == "1",
            sync_unused_issued=str(form.get("sync_unused_issued") or "") == "1",
            actor_discord_id=user.get("id"),
        )
    except ValueError as exc:
        return _redirect(str(exc), edit_template=template_id)

    synced = int(result.get("synced_count") or 0)
    suffix = f"，並同步更新 {synced} 張尚未使用的舊福利" if synced else ""
    return _redirect(f"已更新福利模板 #{template_id}{suffix}。")


@router.post("/admin/benefits/issue")
async def issue_customer_benefit(request: Request):
    user = _admin(request)
    if user is None:
        return RedirectResponse(url="/", status_code=303)

    form = await request.form()
    customer_ids = [
        str(value or "").strip()
        for value in form.getlist("customer_discord_ids")
        if str(value or "").strip()
    ]
    legacy_customer_id = str(form.get("customer_discord_id") or "").strip()
    if legacy_customer_id:
        customer_ids.append(legacy_customer_id)
    customer_ids = list(dict.fromkeys(customer_ids))
    selected_customer = customer_ids[0] if len(customer_ids) == 1 else ""
    if not customer_ids:
        return _redirect("請至少選擇一位要發放的會員。")

    template_id = str(form.get("template_id") or "").strip()
    template = get_template(template_id) if template_id else None
    if template is None:
        return _redirect("請選擇有效的福利模板。", customer_id=selected_customer)
    if bool(template.get("is_high_risk")) and not bool(user.get("is_manager")):
        return _redirect("這是高風險福利模板，只能由管理員發放。", customer_id=selected_customer)

    note = str(form.get("note") or "")
    expires_at = str(form.get("expires_at") or "").strip() or None
    issued_count = 0
    issue_failed = 0
    dm_failed = 0

    for customer_id in customer_ids:
        try:
            issued_id = issue_benefit(
                template_id=template_id,
                customer_discord_id=customer_id,
                actor_discord_id=user.get("id"),
                note=note,
                expires_at=expires_at,
            )
        except ValueError:
            issue_failed += 1
            continue

        issued_count += 1
        try:
            item = next(
                (
                    benefit
                    for benefit in list_customer_promotion_benefits(
                        customer_id,
                        active_only=False,
                        limit=20,
                    )
                    if int(benefit.get("id") or 0) == int(issued_id)
                ),
                None,
            )
            if item is None:
                raise RuntimeError("issued benefit could not be reloaded")
            await asyncio.to_thread(
                send_direct_message,
                customer_id,
                content=build_benefit_grant_dm(item),
            )
        except Exception as exc:
            dm_failed += 1
            print(
                f"[benefits] DM failed customer={customer_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )

    if issued_count == 0:
        return _redirect("福利發放失敗，請重新確認會員與模板。", customer_id=selected_customer)

    message = f"已發放福利給 {issued_count} 位會員"
    if issue_failed:
        message += f"，另有 {issue_failed} 位發放失敗"
    if dm_failed:
        message += f"；其中 {dm_failed} 位 Discord 私訊未送達，但福利仍已入帳"
    else:
        message += "；Discord 私訊通知已送出"
    return _redirect(message + "。", customer_id=selected_customer)


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
