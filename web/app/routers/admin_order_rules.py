from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from services.order_product_status import (
    ensure_order_product_status_store,
    get_order_product_status,
    install_web_catalog_guards,
    set_order_product_active,
)
from services.order_rule_store import (
    create_custom_order_rule,
    ensure_order_rule_store,
    get_active_override,
    get_custom_rule_definition,
    list_rule_versions,
    publish_rule_override,
    reset_rule_override,
    rollback_rule_override,
)
from services.game_roles import (
    GAME_IDENTITY_ROLES,
    GAME_RANK_ROLES,
)
from services.order_rules import (
    CATEGORY_LABELS,
    ORDER_RULES,
    ROLE_LABELS,
    OrderRule,
    build_custom_rule,
    get_base_rule,
    invalidate_rule_override_cache,
    preview_rule_override,
    rule_to_override_payload,
)
from web.app.services.audit_trail import write_sqlite_audit_log


# main.py imports this router before the public site router. Install the live
# availability guards here so the public catalog/quote helpers that site.py
# imports afterwards already respect manager-controlled product status.
install_web_catalog_guards()

router = APIRouter(tags=["admin-order-rules"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

OPTIONAL_INT_FIELDS = {
    "max_quantity",
    "max_specified_count",
    "specify_free_min_units",
    "max_player_count",
}
INT_FIELDS = {
    "price",
    "min_quantity",
    "specify_fee_default",
    "min_player_count",
    "min_protector_count",
}
BOOL_FIELDS = {
    "allow_specify",
    "player_count_enabled",
    "price_multiply_player_count",
    "vip_discount_allowed",
    "point_benefits_allowed",
    "loyalty_benefits_enabled",
}
PRICING_TYPES = {"fixed", "hourly", "game", "unit", "manual"}

# 舊分類只保留給歷史訂單與舊快照回查，不應再從後台修改。
ADMIN_HIDDEN_RULE_CATEGORIES = {"general", "basic", "fun"}

# 只供歷史訂單 / 舊快照回查，不是現在可販售商品。
ADMIN_HISTORICAL_ONLY_RULE_KEYS = {
    "basic_tech_secret_double",
    "basic_tech_topsecret_double",
    "basic_mobile_tech_secret_double",
    "basic_mobile_tech_topsecret_double",
    "basic_entertain_double",
    "basic_entertain_female_double",
    "basic_entertain_male_double",
    "basic_mobile_entertain_double",
    "basic_mobile_entertain_female_double",
    "basic_mobile_entertain_male_double",
    "farm_season_3x3_skin",
    "farm_season_3x3_dc_skin",
    "farm_season_3x3_dc_loss",
    "farm_season_3x3_dc_skin_loss",
    "valorant_entertain",
    "valorant_tech",
    "valorant_top_tech",
}
for _legacy_prefix in ("delta_desktop", "delta_mobile", "steam", "valorant", "lol", "apex"):
    ADMIN_HISTORICAL_ONLY_RULE_KEYS.update({
        f"{_legacy_prefix}_sweet_female_single",
        f"{_legacy_prefix}_sweet_male_single",
        f"{_legacy_prefix}_sweet_female_double",
        f"{_legacy_prefix}_sweet_male_double",
        f"{_legacy_prefix}_sweet_double_any",
    })

ADMIN_PRODUCT_CATEGORIES = tuple(
    (key, label)
    for key, label in CATEGORY_LABELS.items()
    if key not in ADMIN_HIDDEN_RULE_CATEGORIES
)

CATEGORY_DEFAULT_GAME_ROLES = {
    "delta_desktop_basic": ["delta_desktop"],
    "delta_mobile_basic": ["delta_mobile"],
    "delta_desktop_fun": ["delta_desktop"],
    "farm": ["delta_desktop", "delta_mobile"],
    "steam": ["steam_game"],
    "valorant": ["valorant_game"],
    "lol": ["lol_game"],
    "apex": ["apex_game"],
    "custom": [],
}

QUALIFICATION_GROUPS = (
    {
        "key": "global",
        "label": "全局職位",
        "options": (
            {
                "field": "allowed_roles",
                "key": "male_companion",
                "label": ROLE_LABELS["male_companion"],
            },
            {
                "field": "allowed_roles",
                "key": "female_companion",
                "label": ROLE_LABELS["female_companion"],
            },
        ),
    },
    {
        "key": "delta_force",
        "label": "三角洲",
        "options": (
            {
                "field": "allowed_roles",
                "key": "top_protector",
                "label": ROLE_LABELS["top_protector"],
            },
            {
                "field": "allowed_roles",
                "key": "male_protector",
                "label": ROLE_LABELS["male_protector"],
            },
            {
                "field": "allowed_roles",
                "key": "female_protector",
                "label": ROLE_LABELS["female_protector"],
            },
        ),
    },
    {
        "key": "lol",
        "label": "英雄聯盟",
        "options": tuple(
            {
                "field": "allowed_game_roles",
                "key": role.key,
                "label": role.label,
            }
            for role in GAME_RANK_ROLES
            if role.game == "lol"
        ),
    },
    {
        "key": "apex",
        "label": "APEX",
        "options": tuple(
            {
                "field": "allowed_game_roles",
                "key": role.key,
                "label": role.label,
            }
            for role in GAME_RANK_ROLES
            if role.game == "apex"
        ),
    },
    {
        "key": "valorant",
        "label": "特戰英豪",
        "options": tuple(
            {
                "field": "allowed_game_roles",
                "key": role.key,
                "label": role.label,
            }
            for role in GAME_RANK_ROLES
            if role.game == "valorant"
        ),
    },
    {
        "key": "steam",
        "label": "Steam",
        "options": (),
    },
)

GAME_IDENTITY_GROUPS = (
    {
        "key": "delta_force",
        "label": "三角洲",
        "options": tuple(
            {"key": role.key, "label": role.label}
            for role in GAME_IDENTITY_ROLES
            if role.game == "delta_force"
        ),
    },
    {
        "key": "steam",
        "label": "Steam",
        "options": tuple(
            {"key": role.key, "label": role.label}
            for role in GAME_IDENTITY_ROLES
            if role.game == "steam"
        ),
    },
    {
        "key": "lol",
        "label": "英雄聯盟",
        "options": tuple(
            {"key": role.key, "label": role.label}
            for role in GAME_IDENTITY_ROLES
            if role.game == "lol"
        ),
    },
    {
        "key": "apex",
        "label": "APEX",
        "options": tuple(
            {"key": role.key, "label": role.label}
            for role in GAME_IDENTITY_ROLES
            if role.game == "apex"
        ),
    },
    {
        "key": "valorant",
        "label": "特戰英豪",
        "options": tuple(
            {"key": role.key, "label": role.label}
            for role in GAME_IDENTITY_ROLES
            if role.game == "valorant"
        ),
    },
)


def _is_admin_editable_rule(rule_key: str) -> bool:
    key = str(rule_key)
    rule = ORDER_RULES.get(key)
    return bool(
        rule is not None
        and str(rule.category) not in ADMIN_HIDDEN_RULE_CATEGORIES
        and key not in ADMIN_HISTORICAL_ONLY_RULE_KEYS
    )


def _user(request: Request) -> dict | None:
    return request.session.get("user")


def _display_name(user: dict) -> str:
    return str(
        user.get("display_name")
        or user.get("global_name")
        or user.get("username")
        or user.get("id")
        or "總管"
    )


def _redirect(
    *,
    rule_key: str | None = None,
    ok: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    params: list[str] = []
    if rule_key:
        params.append("edit=" + quote_plus(str(rule_key)))
    if ok:
        params.append("ok=" + quote_plus(str(ok)))
    if error:
        params.append("error=" + quote_plus(str(error)))
    suffix = ("?" + "&".join(params)) if params else ""
    return RedirectResponse("/admin/order-rules" + suffix, status_code=303)


def _parse_int(value, *, field: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必須是整數。") from exc


def _presentation_intro_from_store(rule_key: str) -> str:
    key = str(rule_key or "").strip()
    if not key:
        return ""

    try:
        active = get_active_override(key)
        active_payload = (active or {}).get("payload") or {}
        if isinstance(active_payload, dict) and "intro" in active_payload:
            return str(active_payload.get("intro") or "").strip()
    except Exception:
        pass

    try:
        custom = get_custom_rule_definition(key)
        custom_payload = (custom or {}).get("payload") or {}
        if isinstance(custom_payload, dict):
            return str(custom_payload.get("intro") or "").strip()
    except Exception:
        pass

    return ""


def _payload_with_presentation(rule_key: str, rule: OrderRule) -> dict:
    payload = rule_to_override_payload(rule)
    payload["intro"] = _presentation_intro_from_store(rule_key)
    return payload


def _payload_from_form_base(payload: dict, form) -> dict:
    payload = dict(payload)

    payload["label"] = str(form.get("label") or "").strip()
    payload["catalog_group_label"] = str(
        form.get("catalog_group_label") or ""
    ).strip()
    payload["pricing_type"] = str(form.get("pricing_type") or "").strip()
    payload["unit_label"] = str(form.get("unit_label") or "").strip() or "單"
    payload["note"] = str(form.get("note") or "").strip()
    payload["intro"] = str(form.get("intro") or "").strip()

    if not payload["label"]:
        raise ValueError("商品名稱不能空白。")
    if payload["pricing_type"] not in PRICING_TYPES:
        raise ValueError("計價方式不正確。")

    for field in INT_FIELDS:
        payload[field] = _parse_int(form.get(field, 0), field=field)

    for field in OPTIONAL_INT_FIELDS:
        raw = str(form.get(field) or "").strip()
        payload[field] = None if raw == "" else _parse_int(raw, field=field)

    raw_required = str(form.get("required_staff_count") or "").strip()
    if raw_required == "player_count":
        payload["required_staff_count"] = "player_count"
    else:
        payload["required_staff_count"] = _parse_int(
            raw_required,
            field="required_staff_count",
        )

    for field in BOOL_FIELDS:
        payload[field] = field in form

    # 舊的同單買幾送幾已全面停用。欄位只保留歷史 payload 相容，
    # 後台任何新建/修改都強制清空，避免舊 override 將活動復活。
    payload["service_bonus_buy"] = None
    payload["service_bonus_gift"] = 0

    payload["allowed_roles"] = [
        str(item)
        for item in form.getlist("allowed_roles")
        if str(item).strip()
    ]
    payload["allowed_game_roles"] = [
        str(item)
        for item in form.getlist("allowed_game_roles")
        if str(item).strip()
    ]
    payload["required_game_roles"] = [
        str(item)
        for item in form.getlist("required_game_roles")
        if str(item).strip()
    ]

    return payload


def _apply_fun_free_specify_policy(category: str, payload: dict) -> dict:
    """Allow fun orders to publish with an explicit 0T specify fee.

    The core rule validator intentionally requires every selectable role to have
    a known fee when specifying is enabled. Fun orders are the exception: 0T is
    a valid business rule, so persist explicit zero-fee entries instead of
    weakening validation for every other product category.
    """
    payload = dict(payload)
    if (
        str(category) != "delta_desktop_fun"
        or not payload.get("allow_specify")
        or int(payload.get("specify_fee_default") or 0) > 0
    ):
        return payload

    role_fees = dict(payload.get("specify_fee_by_role") or {})
    for role_key in payload.get("allowed_roles") or []:
        role_fees.setdefault(str(role_key), 0)
    payload["specify_fee_by_role"] = role_fees

    game_role_fees = dict(payload.get("specify_fee_by_game_role") or {})
    for role_key in payload.get("allowed_game_roles") or []:
        game_role_fees.setdefault(str(role_key), 0)
    payload["specify_fee_by_game_role"] = game_role_fees

    return payload


def _payload_from_form(rule_key: str, form) -> dict:
    current = ORDER_RULES[str(rule_key)]
    payload = _payload_from_form_base(
        _payload_with_presentation(str(rule_key), current),
        form,
    )
    return _apply_fun_free_specify_policy(str(current.category), payload)


def _new_product_payload(category: str, form) -> dict:
    seed = OrderRule(
        category=category,
        key="__new_product__",
        label="新商品",
        pricing_type="fixed",
    )
    payload = rule_to_override_payload(seed)
    payload["intro"] = ""

    # 新增商品不預設「所有人都可接」，避免忘記設定資格就直接上線。
    payload["allowed_roles"] = []
    payload["allowed_game_roles"] = []
    payload["required_game_roles"] = []
    payload["max_quantity"] = 24

    payload = _payload_from_form_base(payload, form)

    if not payload["required_game_roles"]:
        payload["required_game_roles"] = list(
            CATEGORY_DEFAULT_GAME_ROLES.get(category, [])
        )

    return _apply_fun_free_specify_policy(category, payload)


def _new_product_key(category: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    for _ in range(10):
        key = f"admin_{category}_{stamp}_{secrets.token_hex(2)}"
        if key not in ORDER_RULES:
            return key
    raise RuntimeError("無法產生唯一商品代碼，請再試一次。")


def _rule_row(key: str) -> dict:
    rule = ORDER_RULES[key]
    meta = get_active_override(key)
    status = get_order_product_status(key)
    return {
        "key": key,
        "category": rule.category,
        "category_label": CATEGORY_LABELS.get(rule.category, rule.category),
        "catalog_group_label": str(
            getattr(rule, "catalog_group_label", "") or ""
        ),
        "label": rule.label,
        "price": int(rule.price or 0),
        "pricing_type": rule.pricing_type,
        "unit_label": rule.unit_label,
        "required_staff_count": rule.required_staff_count,
        "vip_discount_allowed": bool(
            getattr(rule, "vip_discount_allowed", True)
        ),
        "point_benefits_allowed": bool(rule.point_benefits_allowed),
        "override_version": int((meta or {}).get("version") or 0),
        "is_overridden": bool(meta),
        "updated_at": str((meta or {}).get("updated_at") or ""),
        "is_active": bool(status.get("is_active", True)),
        "status_updated_at": str(status.get("updated_at") or ""),
    }


def _diff_payload(before: dict, after: dict) -> list[dict]:
    rows = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) == after.get(key):
            continue
        rows.append(
            {
                "field": key,
                "before": before.get(key),
                "after": after.get(key),
            }
        )
    return rows


async def _render(
    request: Request,
    *,
    edit: str = "",
    preview_payload: dict | None = None,
    preview_diff: list[dict] | None = None,
    preview_error: str = "",
):
    user = _user(request)
    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "請先登入",
                "message": "請先使用 Discord 登入。",
                "user": None,
            },
            status_code=401,
        )

    if not user.get("is_manager"):
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "商品規則管理僅限總管使用。",
                "user": user,
            },
            status_code=403,
        )

    ensure_order_rule_store()
    ensure_order_product_status_store()

    rule_rows = sorted(
        (
            _rule_row(str(key))
            for key, rule in ORDER_RULES.items()
            if _is_admin_editable_rule(str(key))
        ),
        key=lambda row: (
            str(row["category_label"]),
            str(row["catalog_group_label"]),
            str(row["label"]),
            str(row["key"]),
        ),
    )

    editable_keys = {str(row["key"]) for row in rule_rows}
    selected_key = str(edit or "").strip()
    if selected_key not in editable_keys:
        selected_key = rule_rows[0]["key"] if rule_rows else ""

    selected_rule = ORDER_RULES.get(selected_key) if selected_key else None
    selected_base = get_base_rule(selected_key) if selected_key else None
    active_meta = get_active_override(selected_key) if selected_key else None
    active_version = int((active_meta or {}).get("version") or 0)
    selected_status = (
        get_order_product_status(selected_key)
        if selected_key
        else {"is_active": True, "updated_at": ""}
    )

    effective_payload = (
        _payload_with_presentation(selected_key, selected_rule)
        if selected_rule is not None
        else {}
    )

    versions = (
        list_rule_versions(selected_key, limit=12)
        if selected_key
        else []
    )

    active_count = sum(1 for row in rule_rows if row["is_active"])

    return templates.TemplateResponse(
        request=request,
        name="admin_order_rules.html",
        context={
            "title": "商品與規則",
            "user": user,
            "rules": rule_rows,
            "active_rule_count": active_count,
            "inactive_rule_count": len(rule_rows) - active_count,
            "category_labels": CATEGORY_LABELS,
            "selected_key": selected_key,
            "selected_rule": selected_rule,
            "selected_base": selected_base,
            "selected_status": selected_status,
            "selected_is_active": bool(selected_status.get("is_active", True)),
            "payload": preview_payload or effective_payload,
            "active_meta": active_meta,
            "active_version": active_version,
            "versions": versions,
            "qualification_groups": QUALIFICATION_GROUPS,
            "game_identity_groups": GAME_IDENTITY_GROUPS,
            "product_categories": ADMIN_PRODUCT_CATEGORIES,
            "pricing_types": (
                ("fixed", "固定價"),
                ("hourly", "按小時"),
                ("game", "按局"),
                ("unit", "按單位"),
                ("manual", "客服手動報價"),
            ),
            "preview_payload": preview_payload,
            "preview_payload_json": (
                json.dumps(
                    preview_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if preview_payload
                else ""
            ),
            "preview_diff": preview_diff or [],
            "preview_error": preview_error,
            "ok": request.query_params.get("ok"),
            "error": request.query_params.get("error"),
        },
    )


@router.get("/admin/order-rules")
async def admin_order_rules(
    request: Request,
    edit: str = "",
):
    return await _render(request, edit=edit)


@router.post("/admin/order-rules/create")
async def admin_order_rule_create(
    request: Request,
):
    user = _user(request)
    if not user or not user.get("is_manager"):
        return RedirectResponse("/admin", status_code=303)

    try:
        form = await request.form()
        category = str(form.get("category") or "").strip()

        allowed_categories = {key for key, _label in ADMIN_PRODUCT_CATEGORIES}
        if category not in allowed_categories:
            raise ValueError("請選擇正確的商品分類。")

        payload = _new_product_payload(category, form)
        rule_key = _new_product_key(category)
        rule = build_custom_rule(
            rule_key,
            category,
            payload,
        )
        stored_payload = rule_to_override_payload(rule)
        stored_payload["intro"] = str(payload.get("intro") or "").strip()

        result = create_custom_order_rule(
            rule_key=rule_key,
            category=category,
            payload=stored_payload,
            actor_discord_id=str(user.get("id") or ""),
            actor_display_name=_display_name(user),
        )
        invalidate_rule_override_cache()

        write_sqlite_audit_log(
            admin_discord_id=str(user.get("id") or ""),
            action="create_order_rule",
            target_type="order_rule",
            target_id=rule_key,
            before=None,
            after={
                "category": category,
                **stored_payload,
                "version": int(result["version"]),
                "is_active": True,
            },
        )
    except (ValueError, KeyError, RuntimeError) as exc:
        return _redirect(error=str(exc))

    return _redirect(
        rule_key=rule_key,
        ok=(
            f"已新增「{rule.label}」到 "
            f"{CATEGORY_LABELS.get(category, category)}。"
            " Web 與 DC Bot 會自動讀取。"
        ),
    )


@router.post("/admin/order-rules/{rule_key}/status")
async def admin_order_rule_status(
    request: Request,
    rule_key: str,
):
    user = _user(request)
    if not user or not user.get("is_manager"):
        return RedirectResponse("/admin", status_code=303)

    if not _is_admin_editable_rule(rule_key):
        return _redirect(error="這個規則只保留給歷史資料，後台不開放修改。")

    try:
        form = await request.form()
        requested = str(form.get("is_active") or "").strip().lower()
        is_active = requested in {"1", "true", "yes", "on"}
        before_status = get_order_product_status(rule_key)

        result = set_order_product_active(
            rule_key=rule_key,
            is_active=is_active,
            actor_discord_id=str(user.get("id") or ""),
            actor_display_name=_display_name(user),
        )

        write_sqlite_audit_log(
            admin_discord_id=str(user.get("id") or ""),
            action=(
                "activate_order_rule"
                if is_active
                else "deactivate_order_rule"
            ),
            target_type="order_rule",
            target_id=rule_key,
            before={"is_active": bool(before_status.get("is_active", True))},
            after={
                "is_active": bool(result["is_active"]),
                "updated_at": result["updated_at"],
            },
        )
    except (ValueError, KeyError, RuntimeError) as exc:
        return _redirect(rule_key=rule_key, error=str(exc))

    rule = ORDER_RULES.get(rule_key)
    label = str(getattr(rule, "label", rule_key) or rule_key)
    return _redirect(
        rule_key=rule_key,
        ok=(
            f"已重新上架「{label}」，Web 與 DC Bot 會自動恢復顯示。"
            if is_active
            else f"已下架「{label}」，新訂單將不再顯示此商品；歷史訂單不受影響。"
        ),
    )


@router.post("/admin/order-rules/{rule_key}/preview")
async def admin_order_rule_preview(
    request: Request,
    rule_key: str,
):
    user = _user(request)
    if not user or not user.get("is_manager"):
        return RedirectResponse("/admin", status_code=303)

    if not _is_admin_editable_rule(rule_key):
        return _redirect(error="這個規則只保留給歷史資料，後台不開放修改。")

    try:
        form = await request.form()
        payload = _payload_from_form(rule_key, form)
        preview_rule_override(rule_key, payload)

        current_payload = _payload_with_presentation(
            rule_key,
            ORDER_RULES[rule_key],
        )
        diff = _diff_payload(current_payload, payload)
        if not diff:
            return _redirect(
                rule_key=rule_key,
                error="沒有任何變更，不需要發布。",
            )

        return await _render(
            request,
            edit=rule_key,
            preview_payload=payload,
            preview_diff=diff,
        )
    except (ValueError, RuntimeError) as exc:
        return await _render(
            request,
            edit=rule_key,
            preview_error=str(exc),
        )


@router.post("/admin/order-rules/{rule_key}/publish")
async def admin_order_rule_publish(
    request: Request,
    rule_key: str,
    payload_json: str = Form(...),
    expected_active_version: int = Form(default=0),
):
    user = _user(request)
    if not user or not user.get("is_manager"):
        return RedirectResponse("/admin", status_code=303)

    if not _is_admin_editable_rule(rule_key):
        return _redirect(error="這個規則只保留給歷史資料，後台不開放修改。")

    try:
        payload = json.loads(payload_json)
        if not isinstance(payload, dict):
            raise ValueError("規則預覽資料格式錯誤。")

        rule = preview_rule_override(rule_key, payload)
        before_payload = _payload_with_presentation(
            rule_key,
            ORDER_RULES[rule_key],
        )
        published_payload = rule_to_override_payload(rule)
        published_payload["intro"] = str(payload.get("intro") or "").strip()

        result = publish_rule_override(
            rule_key=rule_key,
            payload=published_payload,
            actor_discord_id=str(user.get("id") or ""),
            actor_display_name=_display_name(user),
            expected_active_version=int(expected_active_version),
        )
        invalidate_rule_override_cache()

        write_sqlite_audit_log(
            admin_discord_id=str(user.get("id") or ""),
            action="publish_order_rule",
            target_type="order_rule",
            target_id=rule_key,
            before=before_payload,
            after={
                **published_payload,
                "version": int(result["version"]),
            },
        )
    except (ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        return _redirect(rule_key=rule_key, error=str(exc))

    return _redirect(
        rule_key=rule_key,
        ok=f"已發布 {rule.label} v{int(result['version'])}；Web 與 DC Bot 會自動讀取。",
    )


@router.post("/admin/order-rules/{rule_key}/rollback")
async def admin_order_rule_rollback(
    request: Request,
    rule_key: str,
    target_version: int = Form(...),
    expected_active_version: int = Form(default=0),
):
    user = _user(request)
    if not user or not user.get("is_manager"):
        return RedirectResponse("/admin", status_code=303)

    if not _is_admin_editable_rule(rule_key):
        return _redirect(error="這個規則只保留給歷史資料，後台不開放修改。")

    try:
        versions = list_rule_versions(rule_key, limit=100)
        target = next(
            (
                item
                for item in versions
                if int(item.get("version") or 0) == int(target_version)
                and item.get("payload")
            ),
            None,
        )
        if target is None:
            raise ValueError("找不到可回復的版本。")

        preview_rule_override(rule_key, target["payload"])
        before_payload = _payload_with_presentation(
            rule_key,
            ORDER_RULES[rule_key],
        )

        result = rollback_rule_override(
            rule_key=rule_key,
            target_version=int(target_version),
            actor_discord_id=str(user.get("id") or ""),
            actor_display_name=_display_name(user),
            expected_active_version=int(expected_active_version),
        )
        invalidate_rule_override_cache()

        preview_rule_override(rule_key, result["payload"])
        write_sqlite_audit_log(
            admin_discord_id=str(user.get("id") or ""),
            action="rollback_order_rule",
            target_type="order_rule",
            target_id=rule_key,
            before=before_payload,
            after={
                **result["payload"],
                "version": int(result["version"]),
                "source_version": int(target_version),
            },
        )
    except (ValueError, KeyError, RuntimeError) as exc:
        return _redirect(rule_key=rule_key, error=str(exc))

    return _redirect(
        rule_key=rule_key,
        ok=(
            f"已回復到 v{int(target_version)} 的內容，"
            f"並發布為新的 v{int(result['version'])}。"
        ),
    )


@router.post("/admin/order-rules/{rule_key}/reset")
async def admin_order_rule_reset(
    request: Request,
    rule_key: str,
    expected_active_version: int = Form(default=0),
):
    user = _user(request)
    if not user or not user.get("is_manager"):
        return RedirectResponse("/admin", status_code=303)

    if not _is_admin_editable_rule(rule_key):
        return _redirect(error="這個規則只保留給歷史資料，後台不開放修改。")

    try:
        before_payload = _payload_with_presentation(
            rule_key,
            ORDER_RULES[rule_key],
        )
        base_payload = rule_to_override_payload(get_base_rule(rule_key))
        base_payload["intro"] = ""

        result = reset_rule_override(
            rule_key=rule_key,
            actor_discord_id=str(user.get("id") or ""),
            actor_display_name=_display_name(user),
            expected_active_version=int(expected_active_version),
        )
        invalidate_rule_override_cache()

        write_sqlite_audit_log(
            admin_discord_id=str(user.get("id") or ""),
            action="reset_order_rule",
            target_type="order_rule",
            target_id=rule_key,
            before=before_payload,
            after={
                **base_payload,
                "reset_from_version": int(result["source_version"]),
            },
        )
    except (ValueError, KeyError, RuntimeError) as exc:
        return _redirect(rule_key=rule_key, error=str(exc))

    return _redirect(
        rule_key=rule_key,
        ok="已清除後台覆寫，恢復程式內建規則。",
    )
