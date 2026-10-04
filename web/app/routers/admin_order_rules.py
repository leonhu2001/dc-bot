from __future__ import annotations

import json
import secrets
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from services.order_rule_store import (
    create_custom_rule_definition,
    ensure_order_rule_store,
    get_active_override,
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
    build_custom_rule_definition,
    get_base_rule,
    invalidate_rule_override_cache,
    preview_rule_override,
    rule_to_override_payload,
)
from web.app.services.audit_trail import write_sqlite_audit_log


router = APIRouter(tags=["admin-order-rules"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

OPTIONAL_INT_FIELDS = {
    "max_quantity",
    "max_specified_count",
    "specify_free_min_units",
    "max_player_count",
    "service_bonus_buy",
}
INT_FIELDS = {
    "price",
    "min_quantity",
    "specify_fee_default",
    "min_player_count",
    "min_protector_count",
    "service_bonus_gift",
}
BOOL_FIELDS = {
    "allow_specify",
    "player_count_enabled",
    "price_multiply_player_count",
    "point_benefits_allowed",
}
PRICING_TYPES = {"fixed", "hourly", "game", "unit", "manual"}

# 舊分類只保留給歷史訂單與舊快照回查，不應再從後台修改。
ADMIN_HIDDEN_RULE_CATEGORIES = {"general", "basic", "fun"}

ADMIN_CREATABLE_RULE_CATEGORIES = (
    "delta_desktop_basic",
    "delta_mobile_basic",
    "delta_desktop_fun",
    "farm",
    "steam",
    "valorant",
    "lol",
    "apex",
)

CATEGORY_DEFAULT_GAME_ROLES = {
    "delta_desktop_basic": ("delta_desktop",),
    "delta_mobile_basic": ("delta_mobile",),
    "delta_desktop_fun": ("delta_desktop",),
    "farm": ("delta_desktop", "delta_mobile"),
    "steam": ("steam_game",),
    "valorant": ("valorant_game",),
    "lol": ("lol_game",),
    "apex": ("apex_game",),
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
    rule = ORDER_RULES.get(str(rule_key))
    return bool(
        rule is not None
        and str(rule.category) not in ADMIN_HIDDEN_RULE_CATEGORIES
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


def _payload_from_form(rule_key: str, form) -> dict:
    current = ORDER_RULES[str(rule_key)]
    payload = rule_to_override_payload(current)

    payload["label"] = str(form.get("label") or "").strip()
    payload["pricing_type"] = str(form.get("pricing_type") or "").strip()
    payload["unit_label"] = str(form.get("unit_label") or "").strip() or "單"
    payload["note"] = str(form.get("note") or "").strip()

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

    # Existing fee maps and advanced adjustments are intentionally preserved.
    # The first admin version exposes the high-frequency business controls while
    # leaving unusual per-role adjustment dictionaries untouched.
    return payload


def _optional_int_from_form(form, field: str) -> int | None:
    raw = str(form.get(field) or "").strip()
    return None if raw == "" else _parse_int(raw, field=field)


def _new_rule_payload_from_form(form, category: str) -> dict:
    label = str(form.get("label") or "").strip()
    pricing_type = str(form.get("pricing_type") or "").strip()
    unit_label = str(form.get("unit_label") or "").strip() or "單"

    if not label:
        raise ValueError("商品名稱不能空白。")
    if pricing_type not in PRICING_TYPES:
        raise ValueError("計價方式不正確。")

    allowed_roles = [
        str(item)
        for item in form.getlist("allowed_roles")
        if str(item).strip()
    ]
    allowed_game_roles = [
        str(item)
        for item in form.getlist("allowed_game_roles")
        if str(item).strip()
    ]
    required_game_roles = [
        str(item)
        for item in form.getlist("required_game_roles")
        if str(item).strip()
    ]
    if not required_game_roles:
        required_game_roles = list(
            CATEGORY_DEFAULT_GAME_ROLES.get(category, ())
        )

    raw_required = str(form.get("required_staff_count") or "1").strip()
    if raw_required == "player_count":
        required_staff_count: int | str = "player_count"
    else:
        required_staff_count = _parse_int(
            raw_required,
            field="required_staff_count",
        )

    player_count_enabled = "player_count_enabled" in form
    if required_staff_count == "player_count":
        player_count_enabled = True

    payload = {
        "label": label,
        "pricing_type": pricing_type,
        "price": _parse_int(form.get("price", 0), field="price"),
        "unit_label": unit_label,
        "allowed_roles": allowed_roles,
        "allowed_game_roles": allowed_game_roles,
        "required_game_roles": required_game_roles,
        "required_staff_count": required_staff_count,
        "min_quantity": _parse_int(
            form.get("min_quantity", 1),
            field="min_quantity",
        ),
        "max_quantity": _optional_int_from_form(form, "max_quantity"),
        "allow_specify": "allow_specify" in form,
        "max_specified_count": _optional_int_from_form(
            form,
            "max_specified_count",
        ),
        "specify_fee_default": _parse_int(
            form.get("specify_fee_default", 0),
            field="specify_fee_default",
        ),
        "specify_fee_by_role": {},
        "specify_free_min_units": _optional_int_from_form(
            form,
            "specify_free_min_units",
        ),
        "specify_free_basis": "quantity",
        "player_count_enabled": player_count_enabled,
        "min_player_count": _parse_int(
            form.get("min_player_count", 1),
            field="min_player_count",
        ),
        "max_player_count": _optional_int_from_form(
            form,
            "max_player_count",
        ),
        "price_multiply_player_count":
            "price_multiply_player_count" in form,
        "point_benefits_allowed": "point_benefits_allowed" in form,
        "min_protector_count": _parse_int(
            form.get("min_protector_count", 0),
            field="min_protector_count",
        ),
        "service_bonus_buy": _optional_int_from_form(
            form,
            "service_bonus_buy",
        ),
        "service_bonus_gift": _parse_int(
            form.get("service_bonus_gift", 0),
            field="service_bonus_gift",
        ),
        "staff_adjustments": {},
        "staff_adjustment_labels": {},
        "note": str(form.get("note") or "").strip(),
        "specify_fee_by_game_role": {},
    }
    return payload


def _new_custom_rule_key(category: str) -> str:
    return f"admin_{category}_{secrets.token_hex(5)}"


def _assert_new_label_available(category: str, label: str) -> None:
    wanted = str(label or "").strip().casefold()
    for rule in ORDER_RULES.values():
        if (
            str(getattr(rule, "category", "")) == str(category)
            and str(getattr(rule, "label", "")).strip().casefold() == wanted
        ):
            raise ValueError("這個分類已經有同名商品，請換一個商品名稱。")


def _rule_row(key: str) -> dict:
    rule = ORDER_RULES[key]
    meta = get_active_override(key)
    return {
        "key": key,
        "category": rule.category,
        "category_label": CATEGORY_LABELS.get(rule.category, rule.category),
        "label": rule.label,
        "price": int(rule.price or 0),
        "pricing_type": rule.pricing_type,
        "unit_label": rule.unit_label,
        "required_staff_count": rule.required_staff_count,
        "override_version": int((meta or {}).get("version") or 0),
        "is_overridden": bool(meta),
        "updated_at": str((meta or {}).get("updated_at") or ""),
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

    rule_rows = sorted(
        (
            _rule_row(str(key))
            for key, rule in ORDER_RULES.items()
            if str(rule.category) not in ADMIN_HIDDEN_RULE_CATEGORIES
        ),
        key=lambda row: (
            str(row["category_label"]),
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

    effective_payload = (
        rule_to_override_payload(selected_rule)
        if selected_rule is not None
        else {}
    )

    versions = (
        list_rule_versions(selected_key, limit=12)
        if selected_key
        else []
    )

    return templates.TemplateResponse(
        request=request,
        name="admin_order_rules.html",
        context={
            "title": "商品與規則",
            "user": user,
            "rules": rule_rows,
            "category_labels": CATEGORY_LABELS,
            "creatable_categories": [
                (key, CATEGORY_LABELS.get(key, key))
                for key in ADMIN_CREATABLE_RULE_CATEGORIES
            ],
            "selected_key": selected_key,
            "selected_rule": selected_rule,
            "selected_base": selected_base,
            "payload": preview_payload or effective_payload,
            "active_meta": active_meta,
            "active_version": active_version,
            "versions": versions,
            "qualification_groups": QUALIFICATION_GROUPS,
            "game_identity_groups": GAME_IDENTITY_GROUPS,
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
async def admin_order_rule_create(request: Request):
    user = _user(request)
    if not user or not user.get("is_manager"):
        return RedirectResponse("/admin", status_code=303)

    try:
        form = await request.form()
        category = str(form.get("category") or "").strip()
        if category not in ADMIN_CREATABLE_RULE_CATEGORIES:
            raise ValueError("請選擇可新增商品的正式分類。")

        payload = _new_rule_payload_from_form(form, category)
        _assert_new_label_available(category, payload["label"])

        rule_key = _new_custom_rule_key(category)
        rule = build_custom_rule_definition(
            rule_key,
            category,
            payload,
        )

        create_custom_rule_definition(
            rule_key=rule_key,
            category=category,
            payload=rule_to_override_payload(rule),
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
                **rule_to_override_payload(rule),
            },
        )
    except (ValueError, RuntimeError) as exc:
        return _redirect(error=str(exc))

    return _redirect(
        rule_key=rule_key,
        ok=(
            f"已新增 {rule.label}；Web 與 Discord 自助下單會自動讀取，"
            "不需要重新部署。"
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

        current_payload = rule_to_override_payload(ORDER_RULES[rule_key])
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
        before_payload = rule_to_override_payload(ORDER_RULES[rule_key])

        result = publish_rule_override(
            rule_key=rule_key,
            payload=rule_to_override_payload(rule),
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
                **rule_to_override_payload(rule),
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
        before_payload = rule_to_override_payload(ORDER_RULES[rule_key])

        result = rollback_rule_override(
            rule_key=rule_key,
            target_version=int(target_version),
            actor_discord_id=str(user.get("id") or ""),
            actor_display_name=_display_name(user),
            expected_active_version=int(expected_active_version),
        )
        invalidate_rule_override_cache()

        after_rule = preview_rule_override(rule_key, result["payload"])
        write_sqlite_audit_log(
            admin_discord_id=str(user.get("id") or ""),
            action="rollback_order_rule",
            target_type="order_rule",
            target_id=rule_key,
            before=before_payload,
            after={
                **rule_to_override_payload(after_rule),
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
        before_payload = rule_to_override_payload(ORDER_RULES[rule_key])
        base_payload = rule_to_override_payload(get_base_rule(rule_key))

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
