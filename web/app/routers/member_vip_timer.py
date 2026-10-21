from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from services.vip_timer import VIP_TIMER_CATEGORY
from web.app.routers import site as site_module
from web.app.routers.vip_timer import _is_gold_or_above, _vip_group
from web.app.services.order_groups import get_grouped_order_catalog as _base_order_catalog


router = APIRouter(tags=["site"])
_INSTALLED = False


def _retire_black_diamond_site_copy(site) -> None:
    for level in getattr(site, "VIP_LEVELS_PUBLIC", []) or []:
        if str(level.get("name") or "") != "黑鑽魔丸":
            continue
        level["benefits"] = [
            str(text)
            for text in level.get("benefits", [])
            if not (
                "機密航天保底1000w" in str(text)
                or "娛樂陪 2H" in str(text)
                or "娛樂陪2H" in str(text)
            )
        ]


def install(site) -> None:
    """Keep VIP timer checkout available only from the member area."""

    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    original_categories = site.get_public_order_categories
    original_catalog = site.get_grouped_order_catalog

    def member_only_categories():
        return [
            row
            for row in original_categories()
            if str(row.get("key") or "") != VIP_TIMER_CATEGORY
        ]

    def member_only_catalog(category: str = "all"):
        key = str(category or "all").strip() or "all"
        if key == VIP_TIMER_CATEGORY:
            return []
        return [
            group
            for group in original_catalog(key)
            if (
                str(group.get("category") or "") != VIP_TIMER_CATEGORY
                and str(group.get("key") or "") != "vip_timer_order"
            )
        ]

    site.get_public_order_categories = member_only_categories
    site.get_grouped_order_catalog = member_only_catalog
    _retire_black_diamond_site_copy(site)


@router.get("/me/vip-timer")
def member_vip_timer(request: Request):
    user = site_module.get_current_user(request)
    if not user:
        return RedirectResponse(
            url="/auth/discord/login?next=/me/vip-timer",
            status_code=303,
        )

    customer_id = str(user.get("id") or "").strip()
    if not _is_gold_or_above(customer_id):
        return RedirectResponse(
            url="/me?denied=vip_timer",
            status_code=303,
        )

    group = _vip_group(_base_order_catalog)
    group["variant_count"] = len(group.get("variants") or [])

    return site_module.templates.TemplateResponse(
        request=request,
        name="order_catalog.html",
        context=site_module._site_context(
            request,
            title="VIP 自由計時｜我的專區｜魔丸娛樂",
            seo_description="金級會員以上專屬 VIP 自由計時服務。",
            page_name="member",
            categories=[],
            category_filter=VIP_TIMER_CATEGORY,
            groups=[group],
            selected_staff=None,
        ),
    )


__all__ = ["install", "router"]
