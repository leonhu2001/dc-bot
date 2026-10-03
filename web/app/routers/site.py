from __future__ import annotations
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from web.app.config import config

from web.app.services.discord_service import (
    get_dashboard_access,
    get_member_role_ids,
)
from web.app.services.site_data import (
    VIP_CUSTOM_ORDER_RULES,
    VIP_GENERAL_RULES,
    VIP_LEVELS_PUBLIC,
    VIP_PRIVATE_CHANNEL_RULES,
    VIP_REBATE_RULES,
    get_member_summary,
    get_order_categories,
    list_order_catalog,
    get_popular_order_groups,
    get_public_staff,
    get_public_staff_role_filters,
    list_public_staff,
    toggle_favorite,
)


from web.app.services.order_groups import (
    get_grouped_order_catalog,
    get_public_order_categories,
)

from web.app.services.public_checkout import (
    build_public_quote,
)

from web.app.services.checkout_preview import (
    build_checkout_options,
    build_checkout_preview,
)

from web.app.services.checkout_preview import build_staff_order_filter

from web.app.services.customer_portal import (
    build_customer_portal_snapshot,
    get_customer_order,
)


from web.app.services.marketing_funnel import (
    capture_first_touch,
    ensure_marketing_session,
    record_marketing_event,
)

from web.app.services.seo import (
    build_robots_txt,
    build_seo,
    build_sitemap_xml,
    delta_force_schema,
)

router = APIRouter(
    tags=["site"]
)

TEMPLATES_DIR = (
    Path(__file__).resolve().parents[1]
    / "templates"
)

templates = Jinja2Templates(
    directory=str(
        TEMPLATES_DIR
    )
)


def get_current_user(
    request: Request,
) -> dict | None:
    return request.session.get(
        "user"
    )


def _site_context(
    request: Request,
    **extra,
) -> dict:
    user = get_current_user(
        request
    )

    ensure_marketing_session(
        request.session
    )
    capture_first_touch(
        request.session,
        query_params=request.query_params,
        referrer=request.headers.get("referer"),
    )

    context = {
        "user": user,
    }

    context.update(
        extra
    )

    if "seo" not in context:
        path = request.url.path
        noindex = (
            path.startswith("/me")
            or path.startswith("/auth")
        )
        context["seo"] = build_seo(
            path=path,
            title=str(
                context.get("title")
                or "魔丸娛樂"
            ),
            description=str(
                context.get("seo_description")
                or "魔丸娛樂提供遊戲陪玩、護航、娛樂開黑與多種遊戲服務。"
            ),
            noindex=noindex,
        )

    return context


def _record_site_funnel(
    request: Request,
    event_name: str,
    *,
    properties: dict | None = None,
    event_key: str | None = None,
) -> None:
    try:
        user = get_current_user(request)
        customer_id = (
            str(user.get("id") or "")
            if user
            else None
        )
        record_marketing_event(
            session=request.session,
            event_name=event_name,
            path=request.url.path,
            customer_discord_id=customer_id,
            properties=properties,
            event_key=event_key,
        )
    except Exception as exc:
        print(
            f"[marketing] {event_name} skipped: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )


def _refresh_staff_access(
    request: Request,
) -> dict | None:
    user = get_current_user(
        request
    )

    if not user:
        return None

    discord_id = str(
        user.get(
            "id"
        )
        or ""
    ).strip()

    if not discord_id:
        return None

    try:
        role_ids = (
            get_member_role_ids(
                discord_id
            )
        )

        access = (
            get_dashboard_access(
                role_ids
            )
        )

    except Exception:
        return None

    is_customer_service = bool(
        access.get(
            "is_customer_service",
            False,
        )
    )

    is_worker = bool(
        access.get(
            "is_worker",
            False,
        )
    )

    is_companion = bool(
        access.get(
            "is_companion",
            False,
        )
    )

    is_employee = bool(
        is_customer_service
        or is_worker
        or is_companion
    )

    user.update(
        {
            "role_ids": role_ids,
            "is_admin": (
                is_customer_service
            ),
            "is_customer_service": (
                is_customer_service
            ),
            "is_worker": is_worker,
            "is_companion": (
                is_companion
            ),
            "is_employee": (
                is_employee
            ),
        }
    )

    request.session["user"] = user

    return user


@router.get("/")
async def home(
    request: Request,
):
    from web.app.services.staff_service import (
        refresh_staff_members_if_stale,
    )
    from web.app.services.staff_roster_sync import (
        ensure_staff_roster_profiles,
    )

    try:
        refresh_staff_members_if_stale(
            max_age_seconds=60
        )
    except Exception as exc:
        print(
            "[home_staff_sync]",
            repr(
                exc
            ),
        )

    try:
        ensure_staff_roster_profiles()
    except Exception as exc:
        print(
            "[home_roster_profiles]",
            repr(
                exc
            ),
        )

    home_crew_groups = [
        {
            "key":
                "entertainment_female",
            "title":
                "娛樂女陪",
            "eyebrow":
                "ENTERTAINMENT",
            "description":
                "持有女陪身分，主打聊天、娛樂與氣氛互動。",
            "profiles":
                list_public_staff(
                    role_filter=
                        "entertainment_female",
                )[:6],
        },
        {
            "key":
                "entertainment_male",
            "title":
                "娛樂男陪",
            "eyebrow":
                "ENTERTAINMENT",
            "description":
                "持有男陪身分，適合輕鬆開黑與聊天娛樂。",
            "profiles":
                list_public_staff(
                    role_filter=
                        "entertainment_male",
                )[:6],
        },
        {
            "key":
                "strong_player",
            "title":
                "強力打手",
            "eyebrow":
                "TOP TIER",
            "description":
                "頂護、菁英、頂獵、輻能，直接找高階技術人員。",
            "profiles":
                list_public_staff(
                    role_filter=
                        "strong_player",
                )[:6],
        },
    ]

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context=_site_context(
            request,
            title="魔丸娛樂｜遊戲陪玩、護航與娛樂開黑",
            seo_description="魔丸娛樂提供三角洲、特戰英豪、英雄聯盟、APEX 等遊戲陪玩、護航與娛樂開黑服務。",
            page_name="home",
            popular_services=(
                get_popular_order_groups(
                    limit=3
                )
            ),
            home_crew_groups=
                home_crew_groups,
        ),
    )


@router.get("/me")
async def member_center(
    request: Request,
):
    user = get_current_user(
        request
    )

    if not user:
        return RedirectResponse(
            url="/auth/discord/login?next=/me",
            status_code=303,
        )

    customer_id = str(
        user.get(
            "id"
        )
        or ""
    )

    member = get_member_summary(
        customer_id
    )

    portal = build_customer_portal_snapshot(
        customer_id,
        guild_id=config.DISCORD_GUILD_ID,
    )

    return templates.TemplateResponse(
        request=request,
        name="member_center.html",
        context=_site_context(
            request,
            title="我的專區｜魔丸娛樂",
            page_name="member",
            member=member,
            portal=portal,
        ),
    )


@router.get("/me/orders")
async def member_orders(
    request: Request,
):
    user = get_current_user(
        request
    )

    if not user:
        return RedirectResponse(
            url="/auth/discord/login?next=/me/orders",
            status_code=303,
        )

    customer_id = str(
        user.get(
            "id"
        )
        or ""
    )

    portal = build_customer_portal_snapshot(
        customer_id,
        guild_id=config.DISCORD_GUILD_ID,
    )

    return templates.TemplateResponse(
        request=request,
        name="member_orders.html",
        context=_site_context(
            request,
            title="我的訂單｜魔丸娛樂",
            page_name="member_orders",
            portal=portal,
        ),
    )


@router.get("/me/orders/{order_id}")
async def member_order_detail(
    request: Request,
    order_id: int,
):
    user = get_current_user(
        request
    )

    if not user:
        return RedirectResponse(
            url=f"/auth/discord/login?next=/me/orders/{int(order_id)}",
            status_code=303,
        )

    order = get_customer_order(
        str(
            user.get(
                "id"
            )
            or ""
        ),
        int(order_id),
        guild_id=config.DISCORD_GUILD_ID,
    )

    if order is None:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "找不到訂單",
                "message": "這筆訂單不存在，或不屬於目前登入的 Discord 帳號。",
                "user": user,
            },
            status_code=404,
        )

    return templates.TemplateResponse(
        request=request,
        name="member_order_detail.html",
        context=_site_context(
            request,
            title=f"{order['order_no']}｜我的訂單",
            page_name="member_orders",
            order=order,
        ),
    )


@router.get("/order")
async def public_order(
    request: Request,
    category: str = "all",
    staff: str | None = None,
    view: str | None = None,
    focus: str | None = None,
):
    user = get_current_user(request)
    customer_id = str(user.get("id") or "") if user else None
    selected_staff = get_public_staff(str(staff), customer_id=customer_id) if staff else None
    categories = get_public_order_categories()
    valid_categories = {item["key"] for item in categories}
    if category not in valid_categories:
        category = "all"

    view_key = str(view or "").strip().lower()
    category_filter = category
    all_groups = get_grouped_order_catalog("all")

    focus_key = str(
        focus
        or ""
    ).strip()

    focused_groups = [
        group
        for group
        in all_groups
        if str(
            group.get(
                "key"
            )
            or ""
        )
        == focus_key
    ]

    if (
        focus_key
        and focused_groups
    ):
        groups = focused_groups
        category_filter = str(
            focused_groups[
                0
            ].get(
                "category"
            )
            or "all"
        )

    elif view_key == "technical":
        excluded_group_keys = {
            "exbar_gamble",
            "teaching",
            "entertain",
            "oil",
            "bet",
            "trial",
        }
        excluded_categories = {
            "delta_desktop_fun",
            "farm",
        }

        groups = [
            group
            for group
            in all_groups
            if (
                str(
                    group.get(
                        "category"
                    )
                    or ""
                )
                not in excluded_categories
                and str(
                    group.get(
                        "key"
                    )
                    or ""
                )
                not in excluded_group_keys
                and not str(
                    group.get("key")
                    or ""
                ).endswith(("_sweet", "_teaching"))
                and "娛樂陪"
                not in str(
                    group.get(
                        "label"
                    )
                    or ""
                )
            )
        ]
        category_filter = "all"

    elif view_key == "entertainment":
        groups = [
            group
            for group
            in all_groups
            if "娛樂陪"
            in str(
                group.get(
                    "label"
                )
                or ""
            )
        ]
        category_filter = "all"

    elif view_key == "teaching":
        groups = [
            group
            for group
            in all_groups
            if str(
                group.get(
                    "key"
                )
                or ""
            )
            .endswith("_teaching")
        ]
        category_filter = "all"

    else:
        groups = get_grouped_order_catalog(category)

    return templates.TemplateResponse(
        request=request,
        name="order_catalog.html",
        context=_site_context(
            request,
            title="遊戲陪玩與護航價目｜魔丸娛樂",
            seo_description="查看魔丸娛樂三角洲、特戰英豪、英雄聯盟、APEX 等陪玩、護航、技術陪與娛樂陪方案。",
            page_name="order",
            categories=categories,
            category_filter=category_filter,
            groups=groups,
            selected_staff=selected_staff,
        ),
    )


# === PHASE 3B PUBLIC QUOTE ===

@router.post("/order/quote")
async def public_order_quote(
    request: Request,
):
    user = get_current_user(
        request
    )


    if not user:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "請先使用 Discord 登入。",
            },
            status_code=401,
        )


    try:

        payload = await request.json()

    except Exception:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "送出的資料格式錯誤。",
            },
            status_code=400,
        )


    if not isinstance(
        payload,
        dict,
    ):

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "送出的資料格式錯誤。",
            },
            status_code=400,
        )


    try:

        quote = build_public_quote(
            rule_key=
                payload.get(
                    "rule_key"
                ),

            quantity=
                payload.get(
                    "quantity"
                ),

            player_count=
                payload.get(
                    "player_count"
                ),

            customer_adjustments=
                payload.get(
                    "customer_adjustments"
                ),

            specified_staff_id=
                payload.get(
                    "specified_staff_id"
                ),
        )


    except ValueError as exc:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    str(exc),
            },
            status_code=422,
        )


    quote[
        "customer_discord_id"
    ] = str(
        user.get(
            "id"
        )
        or ""
    )

    _record_site_funnel(
        request,
        "quote",
        properties={
            "rule_key": payload.get("rule_key"),
            "quantity": payload.get("quantity") or 1,
            "player_count": payload.get("player_count") or 1,
            "total_amount": quote.get("total_amount"),
        },
    )


    return JSONResponse(
        {
            "ok": True,
            "quote": quote,
        }
    )

# === /PHASE 3B PUBLIC QUOTE ===


# === PHASE 3B2 CHECKOUT PREVIEW ===

@router.post("/order/checkout/options")
async def public_checkout_options(
    request: Request,
):
    user = get_current_user(
        request
    )


    if not user:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "請先使用 Discord 登入。",
            },
            status_code=401,
        )


    try:

        payload = await request.json()

    except Exception:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "送出的資料格式錯誤。",
            },
            status_code=400,
        )


    try:

        data = build_checkout_options(
            customer_id=
                str(
                    user.get(
                        "id"
                    )
                    or ""
                ),

            rule_key=
                payload.get(
                    "rule_key"
                ),

            quantity=
                payload.get(
                    "quantity"
                )
                or 1,

            player_count=
                payload.get(
                    "player_count"
                )
                or 1,

            customer_adjustments=
                payload.get(
                    "customer_adjustments"
                ),

            preselected_staff_id=
                payload.get(
                    "preselected_staff_id"
                ),
        )


    except ValueError as exc:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    str(exc),
            },
            status_code=422,
        )


    _record_site_funnel(
        request,
        "checkout",
        properties={
            "rule_key": payload.get("rule_key"),
            "quantity": payload.get("quantity") or 1,
            "player_count": payload.get("player_count") or 1,
        },
    )

    return JSONResponse(
        {
            "ok": True,
            "data": data,
        }
    )


@router.post("/order/checkout/preview")
async def public_checkout_preview(
    request: Request,
):
    user = get_current_user(
        request
    )


    if not user:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "請先使用 Discord 登入。",
            },
            status_code=401,
        )


    try:

        payload = await request.json()

    except Exception:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "送出的資料格式錯誤。",
            },
            status_code=400,
        )


    try:

        data = build_checkout_preview(
            customer_id=
                str(
                    user.get(
                        "id"
                    )
                    or ""
                ),

            rule_key=
                payload.get(
                    "rule_key"
                ),

            quantity=
                payload.get(
                    "quantity"
                )
                or 1,

            player_count=
                payload.get(
                    "player_count"
                )
                or 1,

            customer_adjustments=
                payload.get(
                    "customer_adjustments"
                ),

            specified_staff_ids=
                payload.get(
                    "specified_staff_ids"
                ),

            point_item_key=
                payload.get(
                    "point_item_key"
                ),

            use_wallet=
                bool(
                    payload.get(
                        "use_wallet"
                    )
                ),

            payment_method=
                payload.get(
                    "payment_method"
                ),
        )


    except ValueError as exc:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    str(exc),
            },
            status_code=422,
        )


    return JSONResponse(
        {
            "ok": True,
            "data": data,
        }
    )

# === /PHASE 3B2 CHECKOUT PREVIEW ===



# === PHASE 3C-3A FORMAL ORDER CREATE ===

SERVICE_TERMS_VERSION = "2026-09-02-v1"


@router.get("/robots.txt")
async def public_robots():
    return PlainTextResponse(
        build_robots_txt(),
        media_type="text/plain",
    )


@router.get("/sitemap.xml")
async def public_sitemap():
    return Response(
        content=build_sitemap_xml(),
        media_type="application/xml",
    )


@router.get("/games/delta-force")
async def delta_force_landing(
    request: Request,
):
    all_groups = get_grouped_order_catalog(
        "all"
    )

    groups = [
        group
        for group in all_groups
        if (
            str(group.get("category") or "")
            in {
                "delta_desktop_basic",
                "delta_mobile_basic",
                "delta_desktop_fun",
                "farm",
            }
        )
    ][:9]

    faq_items = [
        {
            "question": "三角洲娛樂陪和技術陪差在哪？",
            "answer": "娛樂陪偏聊天、氣氛與輕鬆遊玩；技術陪則依機密、絕密與陪玩人數選擇方案，更偏向技術配合。",
        },
        {
            "question": "三角洲手遊也可以點嗎？",
            "answer": "可以。官網目前同時提供三角洲端遊與手遊的娛樂陪、技術陪方案。",
        },
        {
            "question": "可以指定陪玩或護航嗎？",
            "answer": "支援指定的商品可以在下單流程選擇指定人員；實際資格與指定費會由伺服器重新驗證。",
        },
        {
            "question": "價格會在送單前確認嗎？",
            "answer": "會。官網先依商品、數量、人數、指定與點數福利重新驗價，確認後才建立正式訂單。",
        },
        {
            "question": "付款是在官網完成嗎？",
            "answer": "目前官網負責建立訂單，付款方式與付款流程統一在 Discord 訂單流程中處理。",
        },
        {
            "question": "沒有人接單怎麼辦？",
            "answer": "訂單建立後會進入魔丸的派單與智慧通知流程；需要協助時也可以在票口使用客服鈴呼叫真人客服。",
        },
    ]

    seo = build_seo(
        path="/games/delta-force",
        title="三角洲陪玩、護航與技術陪｜魔丸娛樂",
        description="魔丸娛樂三角洲行動陪玩服務：端遊／手遊娛樂陪、機密與絕密技術陪、趣味玩法、代解與護航方案。",
        schemas=delta_force_schema(
            faq_items=faq_items,
        ),
    )

    return templates.TemplateResponse(
        request=request,
        name="game_delta_force.html",
        context=_site_context(
            request,
            title=seo["title"],
            seo=seo,
            page_name="game_delta_force",
            groups=groups,
            faq_items=faq_items,
        ),
    )


@router.get("/service-rules")
async def public_service_rules(
    request: Request,
):
    return templates.TemplateResponse(
        request=request,
        name="service_rules.html",
        context=_site_context(
            request,
            title="服務規章｜魔丸娛樂",
            page_name="service_rules",
            terms_version=
                SERVICE_TERMS_VERSION,
        ),
    )


@router.post("/order/create")
async def public_order_create(
    request: Request,
):
    import json as _json

    from datetime import (
        datetime as _datetime,
        timezone as _timezone,
    )

    from sqlalchemy import (
        text as _sql_text,
    )

    from shared.db import (
        SessionLocal as _SessionLocal,
    )

    from web.app.services.public_order_create import (
        create_public_order as _create_public_order,
    )


    user = get_current_user(
        request
    )


    if not user:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "請先使用 Discord 登入。",
            },
            status_code=401,
        )


    try:

        payload = await request.json()

    except Exception:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "送出的資料格式錯誤。",
            },
            status_code=400,
        )


    if not isinstance(
        payload,
        dict,
    ):

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "送出的資料格式錯誤。",
            },
            status_code=400,
        )


    if (
        payload.get(
            "terms_accepted"
        )
        is not True
    ):

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "請先閱讀並同意服務規章。",
            },
            status_code=422,
        )


    incoming_terms_version = str(
        payload.get(
            "terms_version"
        )
        or ""
    ).strip()


    if (
        incoming_terms_version
        != SERVICE_TERMS_VERSION
    ):

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "服務規章版本已更新，"
                    "請重新閱讀並再次確認。",
                "terms_version":
                    SERVICE_TERMS_VERSION,
            },
            status_code=409,
        )


    request_key = str(
        payload.get(
            "request_key"
        )
        or ""
    ).strip()


    if not request_key:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "缺少送單識別碼，"
                    "請重新整理後再試一次。",
            },
            status_code=400,
        )


    if len(
        request_key
    ) > 120:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "送單識別碼格式錯誤。",
            },
            status_code=400,
        )


    extra_requirements = str(
        payload.get(
            "extra_requirements"
        )
        or ""
    ).strip()


    if (
        len(
            extra_requirements
        )
        > 500
    ):

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "附加需求最多 500 字。",
            },
            status_code=422,
        )


    customer_id = str(
        user.get(
            "id"
        )
        or ""
    ).strip()


    customer_display_name = str(
        user.get(
            "display_name"
        )
        or user.get(
            "global_name"
        )
        or user.get(
            "username"
        )
        or user.get(
            "name"
        )
        or customer_id
    ).strip()


    order_payload = dict(
        payload
    )


    order_payload.pop(
        "request_key",
        None,
    )


    order_payload.pop(
        "terms_accepted",
        None,
    )


    order_payload.pop(
        "terms_version",
        None,
    )


    order_payload[
        "extra_requirements"
    ] = extra_requirements


    order_payload[
        "service_terms_version"
    ] = SERVICE_TERMS_VERSION


    db = _SessionLocal()


    try:

        # 官網只負責建立訂單。
        # 付款方式與錢包付款統一留到 Discord。
        order_payload.pop(
            "payment_method",
            None,
        )

        order_payload["use_wallet"] = False
        # 官網不讓客人決定付款方式。
        # 這個值只用來相容目前既有的價格預覽／正式驗價。
        order_payload["payment_method"] = "轉帳"

        # 官網不直接使用錢包付款。
        order_payload["use_wallet"] = False
        order = _create_public_order(
            db,
            customer_id=
                customer_id,
            customer_display_name=
                customer_display_name,
            payload=
                order_payload,
            request_key=
                request_key,
        )
        # zYao 3C3B2R3 pending CS gate v1

        # create_public_order 已完成完整伺服器驗價。
        # 從這裡開始官網不保留付款方式。
        order_payload.pop(
            "payment_method",
            None,
        )

        order_payload["use_wallet"] = False

        order.payment_method = "待付款"

        if (
            str(
                getattr(
                    order,
                    "status",
                    "",
                )
                or ""
            )
            == "waiting_acceptance"

            and not getattr(
                order,
                "dispatch_message_id",
                None,
            )
        ):

            order.status = (
                "pending_cs_dispatch"
            )

            db.execute(
                _sql_text(
                    """
                    UPDATE order_acceptance_meta

                    SET status =
                            :status,

                        updated_at =
                            CURRENT_TIMESTAMP

                    WHERE order_id =
                            :order_id
                    """
                ),
                {
                    "status":
                        "pending_cs_dispatch",

                    "order_id":
                        int(
                            order.id
                        ),
                },
            )

        db.flush()
        # zYao 3C3B2R pending CS dispatch gate v1
        if (
            str(
                getattr(
                    order,
                    "status",
                    "",
                )
                or ""
            )
            == "waiting_acceptance"

            and not getattr(
                order,
                "dispatch_message_id",
                None,
            )
        ):

            order.status = (
                "pending_cs_dispatch"
            )

            db.execute(
                _sql_text(
                    """
                    UPDATE order_acceptance_meta

                    SET status =
                            :status,

                        updated_at =
                            CURRENT_TIMESTAMP

                    WHERE order_id =
                            :order_id
                    """
                ),
                {
                    "status":
                        "pending_cs_dispatch",

                    "order_id":
                        int(
                            order.id
                        ),
                },
            )

            db.flush()


        db.flush()


        order_id = int(
            order.id
        )


        accepted_at = (
            _datetime.now(
                _timezone.utc
            )
            .isoformat()
        )


        db.execute(
            _sql_text(
                """
                CREATE TABLE IF NOT EXISTS
                web_order_submission_meta (
                    order_id INTEGER PRIMARY KEY,
                    customer_discord_id TEXT NOT NULL,
                    request_key TEXT NOT NULL,
                    terms_version TEXT NOT NULL,
                    terms_accepted_at TEXT NOT NULL,
                    extra_requirements TEXT NOT NULL
                        DEFAULT '',
                    submission_payload_json TEXT NOT NULL
                        DEFAULT '{}'
                )
                """
            )
        )


        submission_payload_json = (
            _json.dumps(
                order_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(
                    ",",
                    ":",
                ),
            )
        )


        db.execute(
            _sql_text(
                """
                INSERT INTO
                web_order_submission_meta (
                    order_id,
                    customer_discord_id,
                    request_key,
                    terms_version,
                    terms_accepted_at,
                    extra_requirements,
                    submission_payload_json
                )
                VALUES (
                    :order_id,
                    :customer_discord_id,
                    :request_key,
                    :terms_version,
                    :terms_accepted_at,
                    :extra_requirements,
                    :submission_payload_json
                )
                ON CONFLICT(order_id)
                DO UPDATE SET
                    customer_discord_id =
                        excluded.customer_discord_id,
                    request_key =
                        excluded.request_key,
                    terms_version =
                        excluded.terms_version,
                    terms_accepted_at =
                        excluded.terms_accepted_at,
                    extra_requirements =
                        excluded.extra_requirements,
                    submission_payload_json =
                        excluded.submission_payload_json
                """
            ),
            {
                "order_id":
                    order_id,

                "customer_discord_id":
                    customer_id,

                "request_key":
                    request_key,

                "terms_version":
                    SERVICE_TERMS_VERSION,

                "terms_accepted_at":
                    accepted_at,

                "extra_requirements":
                    extra_requirements,

                "submission_payload_json":
                    submission_payload_json,
            },
        )


        # Capture response values before commit,
        # because SQLAlchemy may expire model state.
        order_status = str(
            getattr(
                order,
                "status",
                "",
            )
            or ""
        )


        bot_order_no = (
            getattr(
                order,
                "bot_order_no",
                None,
            )
        )


        customer_pay_amount = int(
            getattr(
                order,
                "customer_pay_amount",
                0,
            )
            or getattr(
                order,
                "amount",
                0,
            )
            or 0
        )


        db.commit()

        _record_site_funnel(
            request,
            "order_created",
            event_key=f"order:{order_id}",
            properties={
                "order_id": order_id,
                "rule_key": order_payload.get("rule_key"),
                "customer_pay_amount": customer_pay_amount,
                "status": order_status,
            },
        )


        return JSONResponse(
            {
                "ok": True,

                "data": {
                    "order_id":
                        order_id,

                    "bot_order_no":
                        bot_order_no,

                    "status":
                        order_status,

                    "customer_pay_amount":
                        customer_pay_amount,

                    "terms_version":
                        SERVICE_TERMS_VERSION,

                    "discord_ticket_pending":
                        True,
                },
            }
        )


    except ValueError as exc:

        db.rollback()


        return JSONResponse(
            {
                "ok": False,
                "error":
                    str(exc),
            },
            status_code=422,
        )


    except Exception as exc:

        db.rollback()


        print(
            "[PUBLIC ORDER CREATE ERROR]",
            repr(
                exc
            ),
        )


        return JSONResponse(
            {
                "ok": False,
                "error":
                    "建立訂單失敗，"
                    "本次交易已取消，"
                    "請稍後再試或聯絡客服。",
            },
            status_code=500,
        )


    finally:

        db.close()

# === /PHASE 3C-3A FORMAL ORDER CREATE ===


# === PHASE 3B-2.3 STAFF FILTER ROUTE ===

@router.get("/order/staff-filter")
async def public_order_staff_filter(
    request: Request,
):
    staff_id = str(
        request.query_params.get(
            "staff_id"
        )
        or ""
    ).strip()


    if not staff_id:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    "缺少指定人員。",
            },
            status_code=400,
        )


    try:

        data = build_staff_order_filter(
            staff_id
        )


    except ValueError as exc:

        return JSONResponse(
            {
                "ok": False,
                "error":
                    str(exc),
            },
            status_code=422,
        )


    return JSONResponse(
        {
            "ok": True,
            "data": data,
        }
    )

# === /PHASE 3B-2.3 STAFF FILTER ROUTE ===


@router.get("/staff")
async def public_staff(
    request: Request,
    role: str = "all",
):
    # === PHASE 3B-2.6 ROSTER SYNC ===
    from web.app.services.staff_service import (
        refresh_staff_members_if_stale,
    )
    from web.app.services.staff_roster_sync import (
        ensure_staff_roster_profiles,
    )

    try:
        refresh_staff_members_if_stale(
            max_age_seconds=60
        )
    except Exception as exc:
        print(
            "[public_staff_sync]",
            repr(
                exc
            ),
        )

    ensure_staff_roster_profiles()
    # === /PHASE 3B-2.6 ROSTER SYNC ===
    user = get_current_user(
        request
    )

    customer_id = None

    if user:
        customer_id = str(
            user.get(
                "id"
            )
            or ""
        )

    role_filters = (
        get_public_staff_role_filters()
    )

    valid_role_filters = {
        "all",
        "entertainment_female",
        "entertainment_male",
        "strong_player",
        *[
            item["key"]
            for item
            in role_filters
        ],
    }

    if role not in valid_role_filters:
        role = "all"

    profiles = list_public_staff(
        customer_id=customer_id,
        role_filter=role,
    )

    return templates.TemplateResponse(
        request=request,
        name="staff_list.html",
        context=_site_context(
            request,
            title="陪玩陣容｜魔丸娛樂",
            page_name="staff",
            profiles=profiles,
            role_filter=role,
            role_filters=role_filters,
        ),
    )


@router.get("/staff/{staff_id}")
async def public_staff_detail(
    request: Request,
    staff_id: str,
):
    # === PHASE 3B-2.6 ROSTER SYNC ===
    from web.app.services.staff_service import (
        refresh_staff_members_if_stale,
    )
    from web.app.services.staff_roster_sync import (
        ensure_staff_roster_profiles,
    )

    try:
        refresh_staff_members_if_stale(
            max_age_seconds=60
        )
    except Exception as exc:
        print(
            "[public_staff_detail_sync]",
            repr(
                exc
            ),
        )

    ensure_staff_roster_profiles()
    # === /PHASE 3B-2.6 ROSTER SYNC ===
    user = get_current_user(
        request
    )

    customer_id = None

    if user:
        customer_id = str(
            user.get(
                "id"
            )
            or ""
        )

    profile = get_public_staff(
        staff_id,
        customer_id=customer_id,
    )

    if profile is None:
        return templates.TemplateResponse(
            request=request,
            name="site_placeholder.html",
            context=_site_context(
                request,
                title="找不到陪玩｜魔丸娛樂",
                page_name="staff",
                heading="找不到這位陪玩",
                eyebrow="CREW",
                description=(
                    "這個個人牆可能尚未公開，"
                    "或已經停止顯示。"
                ),
                next_label="回到陪玩陣容查看其他人選",
            ),
            status_code=404,
        )

    return templates.TemplateResponse(
        request=request,
        name="staff_detail.html",
        context=_site_context(
            request,
            title=(
                f"{profile['display_name']}"
                "｜魔丸娛樂"
            ),
            page_name="staff",
            profile=profile,
        ),
    )


@router.post(
    "/staff/{staff_id}/favorite"
)
async def public_staff_favorite(
    request: Request,
    staff_id: str,
):
    user = get_current_user(
        request
    )

    if not user:
        return RedirectResponse(
            url="/auth/discord/login",
            status_code=303,
        )

    try:
        toggle_favorite(
            customer_id=str(
                user.get(
                    "id"
                )
                or ""
            ),
            staff_id=staff_id,
        )
    except ValueError:
        pass

    return RedirectResponse(
        url=f"/staff/{staff_id}",
        status_code=303,
    )


@router.get("/vip")
async def public_vip(
    request: Request,
):
    user = get_current_user(
        request
    )

    member = None

    if user:
        member = get_member_summary(
            str(
                user.get(
                    "id"
                )
                or ""
            )
        )

    return templates.TemplateResponse(
        request=request,
        name="vip.html",
        context=_site_context(
            request,
            title="VIP｜魔丸娛樂",
            page_name="vip",
            vip_levels=(
                VIP_LEVELS_PUBLIC
            ),
            custom_order_rules=(
                VIP_CUSTOM_ORDER_RULES
            ),
            rebate_rules=(
                VIP_REBATE_RULES
            ),
            private_channel_rules=(
                VIP_PRIVATE_CHANNEL_RULES
            ),
            vip_rules=(
                VIP_GENERAL_RULES
            ),
            member=member,
        ),
    )


@router.get("/employee")
async def employee_entry(
    request: Request,
):
    uid=_mwfinal_employee_user_id(request)
    if not uid:
        return RedirectResponse(url='/discord/login',status_code=303)
    bundle=_mwfinal_employee_bundle(uid)
    if bundle is None:
        return RedirectResponse(url="/me",status_code=303)
    ctx={"request":request,"title":"員工中心｜魔丸娛樂","page_name":"employee",**bundle}
    try:
        base=_site_context(request,title="員工中心｜魔丸娛樂",page_name="employee")
        if isinstance(base,dict):
            base.update(bundle); ctx=base
    except Exception:
        pass
    return templates.TemplateResponse(request=request,name="employee_center.html",context=ctx)


@router.get("/service")
async def customer_service_entry(
    request: Request,
):
    if not get_current_user(
        request
    ):
        return RedirectResponse(
            url="/auth/discord/login",
            status_code=303,
        )

    user = _refresh_staff_access(
        request
    )

    if (
        not user
        or not user.get(
            "is_customer_service"
        )
    ):
        return RedirectResponse(
            url="/me?denied=service",
            status_code=303,
        )

    return RedirectResponse(
        url="/admin",
        status_code=303,
    )

# === PHASE 3B-2.7 ORDER RULE UI META ===

@router.get("/order/rule-ui-meta")
async def order_rule_ui_meta(
    rule_key: str,
):
    from services.order_rules import (
        ORDER_RULES,
    )

    key = str(
        rule_key
        or ""
    ).strip()

    rule = ORDER_RULES.get(
        key
    )

    if rule is None:
        return {
            "ok": False,
            "error": "找不到這個商品方案。",
        }


    editable = bool(
        getattr(
            rule,
            "player_count_enabled",
            False,
        )
    )


    minimum = max(
        1,
        int(
            getattr(
                rule,
                "min_player_count",
                1,
            )
            or 1
        ),
    )


    maximum_raw = getattr(
        rule,
        "max_player_count",
        None,
    )


    maximum = (
        max(
            minimum,
            int(maximum_raw),
        )
        if maximum_raw is not None
        else minimum
    )


    required_raw = getattr(
        rule,
        "required_staff_count",
        1,
    )


    fixed_count = None


    if not editable:

        if isinstance(
            required_raw,
            int,
        ):
            fixed_count = max(
                1,
                int(required_raw),
            )

        elif (
            str(required_raw)
            .strip()
            .lower()
            == "player_count"
        ):
            fixed_count = minimum

        else:
            try:
                fixed_count = max(
                    1,
                    int(required_raw),
                )

            except (
                TypeError,
                ValueError,
            ):
                fixed_count = 1


        minimum = fixed_count
        maximum = fixed_count


    return {
        "ok": True,
        "data": {
            "rule_key":
                key,

            "label":
                str(
                    getattr(
                        rule,
                        "label",
                        key,
                    )
                ),

            "player_count_enabled":
                editable,

            "min_player_count":
                minimum,

            "max_player_count":
                maximum,

            "fixed_player_count":
                fixed_count,

            "required_staff_count":
                required_raw,
        },
    }

# === /PHASE 3B-2.7 ORDER RULE UI META ===

# MAWAN WEBSITE FINAL NON-ORDER V1 - EMPLOYEE CENTER
from sqlalchemy import text as _mwfinal_text
from shared.db import SessionLocal as _mwfinal_db

def _mwfinal_employee_user_id(request):
    u=request.session.get("user") or {}
    return str(u.get("id") or u.get("discord_id") or u.get("user_id") or "").strip()

def _mwfinal_employee_bundle(discord_id):
    db=_mwfinal_db()
    try:
        m=db.execute(_mwfinal_text("SELECT * FROM web_staff_members WHERE discord_id=:id LIMIT 1"),{"id":str(discord_id)}).mappings().first()
        if not m: return None
        member=dict(m)
        if not (member.get("is_worker") or member.get("is_companion") or member.get("is_customer_service")): return None
        member["name"]=str(member.get("display_name") or member.get("global_name") or member.get("username") or member.get("discord_id") or "未命名")
        p=db.execute(_mwfinal_text("SELECT * FROM staff_profiles WHERE staff_discord_id=:id LIMIT 1"),{"id":str(discord_id)}).mappings().first()
        profile=dict(p) if p else {}
        orders=[dict(r) for r in db.execute(_mwfinal_text("""
            SELECT DISTINCT wo.id,wo.bot_order_no,wo.customer_display_name,wo.customer_discord_id,wo.item,wo.category,
                   wo.status,wo.customer_pay_amount,wo.amount,wo.created_at
            FROM order_assignments oa JOIN web_orders wo ON wo.id=oa.order_id
            WHERE oa.worker_discord_id=:id ORDER BY wo.id DESC
        """),{"id":str(discord_id)}).mappings().all()]
        wp=[dict(r) for r in db.execute(_mwfinal_text(
            "SELECT * FROM worker_payouts WHERE worker_discord_id=:id ORDER BY id DESC"),{"id":str(discord_id)}).mappings().all()]
        cp=[dict(r) for r in db.execute(_mwfinal_text(
            "SELECT * FROM customer_service_payouts WHERE customer_service_discord_id=:id ORDER BY id DESC"),{"id":str(discord_id)}).mappings().all()]
        rv=db.execute(_mwfinal_text("""
            SELECT COUNT(*) total,AVG(rating) average FROM order_reviews
            WHERE staff_discord_id=:id AND COALESCE(is_hidden,0)=0
        """),{"id":str(discord_id)}).mappings().first() or {}
        fav=db.execute(_mwfinal_text("SELECT COUNT(*) FROM staff_favorites WHERE staff_discord_id=:id"),{"id":str(discord_id)}).scalar() or 0
        total=sum(int(r.get("final_payout") or 0) for r in wp)+sum(int(r.get("payout_amount") or 0) for r in cp)
        paid=sum(int(r.get("final_payout") or 0) for r in wp if str(r.get("payout_status") or "").lower()=="paid")
        paid+=sum(int(r.get("payout_amount") or 0) for r in cp if str(r.get("payout_status") or "").lower()=="paid")
        payouts=[{"kind":"服務薪資","order_id":r.get("order_id"),"amount":int(r.get("final_payout") or 0),
                  "status":str(r.get("payout_status") or ""),"created_at":str(r.get("created_at") or "")[:16]} for r in wp[:20]]
        payouts+=[{"kind":"客服薪資","order_id":r.get("order_id"),"amount":int(r.get("payout_amount") or 0),
                   "status":str(r.get("payout_status") or ""),"created_at":str(r.get("created_at") or "")[:16]} for r in cp[:20]]
        payouts.sort(key=lambda x:x.get("created_at") or "",reverse=True)
        return {"member":member,"profile":profile,"orders":orders[:30],"payouts":payouts[:20],
                "stats":{"orders":len(orders),"reviews":int(rv.get("total") or 0),
                         "rating":round(float(rv.get("average") or 0),1),"favorites":int(fav),
                         "payout_total":total,"payout_paid":paid,"payout_pending":total-paid}}
    finally: db.close()
