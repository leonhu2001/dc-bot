from __future__ import annotations

from datetime import date
from html import escape
from typing import Any


PUBLIC_BASE_URL = "https://mowanentertainment.com"
DEFAULT_OG_IMAGE = f"{PUBLIC_BASE_URL}/static/img/og-share.jpg?v=20260904-2"

PUBLIC_SITEMAP_PATHS = (
    "/",
    "/games/delta-force",
    "/order",
    "/staff",
    "/vip",
    "/service-rules",
)


def absolute_url(path: str) -> str:
    path = str(path or "/").strip() or "/"
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return PUBLIC_BASE_URL + path


def organization_schema() -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "魔丸娛樂",
        "alternateName": "MOWAN Entertainment",
        "url": PUBLIC_BASE_URL,
        "logo": absolute_url("/static/img/favicon.png?v=20260904-2"),
    }


def website_schema() -> dict[str, Any]:
    return {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "魔丸娛樂",
        "alternateName": "MOWAN Entertainment",
        "url": PUBLIC_BASE_URL,
        "inLanguage": "zh-Hant",
    }


def build_seo(
    *,
    path: str,
    title: str,
    description: str,
    image: str | None = None,
    noindex: bool = False,
    schemas: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    clean_path = str(path or "/").split("?", 1)[0] or "/"

    return {
        "title": str(title or "魔丸娛樂"),
        "description": str(description or "魔丸娛樂陪玩與遊戲服務。"),
        "canonical": absolute_url(clean_path),
        "image": image or DEFAULT_OG_IMAGE,
        "robots": "noindex, nofollow" if noindex else "index, follow",
        "schemas": schemas or [
            organization_schema(),
            website_schema(),
        ],
    }


def delta_force_schema(
    *,
    faq_items: list[dict[str, str]],
) -> list[dict[str, Any]]:
    faq_entities = [
        {
            "@type": "Question",
            "name": str(item.get("question") or ""),
            "acceptedAnswer": {
                "@type": "Answer",
                "text": str(item.get("answer") or ""),
            },
        }
        for item in faq_items
        if item.get("question") and item.get("answer")
    ]

    service = {
        "@context": "https://schema.org",
        "@type": "Service",
        "name": "三角洲行動陪玩與護航服務",
        "serviceType": "遊戲陪玩、技術陪、娛樂陪與護航服務",
        "provider": {
            "@type": "Organization",
            "name": "魔丸娛樂",
            "url": PUBLIC_BASE_URL,
        },
        "areaServed": "TW",
        "url": absolute_url("/games/delta-force"),
        "description": "魔丸娛樂提供三角洲行動端遊與手遊的娛樂陪、技術陪、趣味玩法與代解服務。",
    }

    result: list[dict[str, Any]] = [
        organization_schema(),
        website_schema(),
        service,
    ]

    if faq_entities:
        result.append(
            {
                "@context": "https://schema.org",
                "@type": "FAQPage",
                "mainEntity": faq_entities,
            }
        )

    return result


def build_sitemap_xml() -> str:
    today = date.today().isoformat()
    rows = []

    for path in PUBLIC_SITEMAP_PATHS:
        priority = "1.0" if path == "/" else ("0.9" if path == "/games/delta-force" else "0.7")
        rows.append(
            "  <url>"
            f"<loc>{escape(absolute_url(path))}</loc>"
            f"<lastmod>{today}</lastmod>"
            "<changefreq>weekly</changefreq>"
            f"<priority>{priority}</priority>"
            "</url>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(rows)
        + "\n</urlset>\n"
    )


def build_robots_txt() -> str:
    return "\n".join(
        (
            "User-agent: *",
            "Allow: /",
            "Disallow: /admin",
            "Disallow: /me",
            "Disallow: /employee",
            "Disallow: /service",
            "Disallow: /auth",
            "Disallow: /dispatch",
            "Disallow: /my",
            f"Sitemap: {absolute_url('/sitemap.xml')}",
            "",
        )
    )
