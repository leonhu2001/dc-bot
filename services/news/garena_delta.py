from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup, Tag


SOURCE_NAME = "Garena 三角洲行動官方"
SOURCE_URL = "https://deltaforce.garena.com/zh_tw/news/all"
SOURCE_HOST = "deltaforce.garena.com"
_ALLOWED_CATEGORIES = {"all", "system", "announcement", "event"}
_CATEGORY_LABELS = {
    "system": "版本資訊",
    "announcement": "公告",
    "event": "活動",
}
_ARTICLE_PATH_RE = re.compile(
    r"^/zh_tw/news/(?P<category>system|announcement|event)/(?P<article_id>[A-Za-z0-9_-]+)/*$"
)
_DATE_RE = re.compile(r"(?P<year>20\d{2})[/-](?P<month>\d{1,2})[/-](?P<day>\d{1,2})")
_WHITESPACE_RE = re.compile(r"\s+")
_CACHE_LOCK = threading.RLock()
_CACHE_FEED: "GameNewsFeed | None" = None
_CACHE_MONOTONIC = 0.0


@dataclass(frozen=True)
class GameNewsItem:
    article_id: str
    category: str
    category_label: str
    title: str
    summary: str
    published_on: date
    url: str


@dataclass(frozen=True)
class GameNewsFeed:
    status: str
    fetched_at: datetime | None
    items: tuple[GameNewsItem, ...]
    message: str
    source_name: str = SOURCE_NAME
    source_url: str = SOURCE_URL


class NewsSourceUnavailable(RuntimeError):
    pass


def _cache_seconds() -> int:
    try:
        return max(120, min(3600, int(os.getenv("DELTA_NEWS_CACHE_SECONDS", "600"))))
    except (TypeError, ValueError):
        return 600


def _clean_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "")).strip()


def _class_text(tag: Tag) -> str:
    raw = tag.get("class") or []
    if isinstance(raw, str):
        return raw.casefold()
    return " ".join(str(part) for part in raw).casefold()


def _date_from_text(value: str) -> date | None:
    match = _DATE_RE.search(value)
    if not match:
        return None
    try:
        return date(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
        )
    except ValueError:
        return None


def _find_text_by_class(anchor: Tag, needles: tuple[str, ...], *, max_length: int) -> str:
    for node in anchor.find_all(True):
        classes = _class_text(node)
        if not classes or not any(needle in classes for needle in needles):
            continue
        text = _clean_text(node.get_text(" ", strip=True))
        if 2 <= len(text) <= max_length:
            return text
    return ""


def _extract_title(anchor: Tag, full_text: str, published_on: date) -> str:
    for heading in anchor.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        text = _clean_text(heading.get_text(" ", strip=True))
        if 2 <= len(text) <= 220:
            return text

    class_title = _find_text_by_class(
        anchor,
        ("title", "headline", "name"),
        max_length=220,
    )
    if class_title and _date_from_text(class_title) != published_on:
        return class_title

    fallback = full_text
    date_match = _DATE_RE.search(fallback)
    if date_match and date_match.start() <= 4:
        fallback = fallback[date_match.end():].strip()
    fallback = re.sub(r"閱讀更多\s*$", "", fallback).strip()
    if not fallback:
        return "Garena 三角洲行動官方消息"
    # A selector-free fallback may contain the card summary too. Keep it short
    # rather than mirror arbitrary amounts of official copy into our website.
    return fallback[:160].rstrip()


def _extract_summary(anchor: Tag, title: str) -> str:
    summary = _find_text_by_class(
        anchor,
        ("summary", "desc", "description", "intro", "brief"),
        max_length=360,
    )
    if not summary or summary == title:
        return ""
    summary = re.sub(r"閱讀更多\s*$", "", summary).strip()
    return summary[:240].rstrip()


def parse_delta_news_html(html: str, *, base_url: str = SOURCE_URL) -> tuple[GameNewsItem, ...]:
    """Parse only Garena Taiwan Delta article links from the official list page."""
    soup = BeautifulSoup(html or "", "html.parser")
    seen: set[str] = set()
    items: list[GameNewsItem] = []

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(base_url, href)
        parsed = urlsplit(absolute)
        if parsed.scheme != "https" or parsed.hostname != SOURCE_HOST:
            continue
        path_match = _ARTICLE_PATH_RE.match(parsed.path)
        if not path_match:
            continue

        article_id = path_match.group("article_id")
        category = path_match.group("category")
        dedupe_key = f"{category}:{article_id}"
        if dedupe_key in seen:
            continue

        full_text = _clean_text(anchor.get_text(" ", strip=True))
        published_on = _date_from_text(full_text)
        if published_on is None:
            date_text = _find_text_by_class(anchor, ("date", "time", "publish"), max_length=64)
            published_on = _date_from_text(date_text)
        if published_on is None:
            continue

        title = _extract_title(anchor, full_text, published_on)
        if not title:
            continue

        seen.add(dedupe_key)
        items.append(
            GameNewsItem(
                article_id=article_id,
                category=category,
                category_label=_CATEGORY_LABELS[category],
                title=title,
                summary=_extract_summary(anchor, title),
                published_on=published_on,
                url=absolute,
            )
        )

    items.sort(key=lambda item: (item.published_on, item.article_id), reverse=True)
    return tuple(items)


def _fetch_official_feed() -> GameNewsFeed:
    response = requests.get(
        SOURCE_URL,
        headers={
            "User-Agent": "MowanEntertainment-News/1.0 (+https://mowanentertainment.com)",
            "Accept": "text/html,application/xhtml+xml",
        },
        timeout=(3.05, 8),
        allow_redirects=True,
    )
    response.raise_for_status()

    final = urlsplit(response.url)
    if final.scheme != "https" or final.hostname != SOURCE_HOST:
        raise NewsSourceUnavailable("Garena news source redirected outside the official host")
    if len(response.content) > 2_500_000:
        raise NewsSourceUnavailable("Garena news source response is unexpectedly large")

    items = parse_delta_news_html(response.text, base_url=response.url)
    if not items:
        raise NewsSourceUnavailable("Garena news source returned no recognized articles")

    return GameNewsFeed(
        status="ready",
        fetched_at=datetime.now(timezone.utc),
        items=items,
        message="消息來自 Garena 台灣《三角洲行動》官方網站。",
    )


def _filtered(feed: GameNewsFeed, category: str, limit: int) -> GameNewsFeed:
    if category == "all":
        items = feed.items
    else:
        items = tuple(item for item in feed.items if item.category == category)
    return replace(feed, items=items[: max(1, min(int(limit), 60))])


def get_delta_official_news(
    category: str = "all",
    *,
    limit: int = 30,
    force_refresh: bool = False,
) -> GameNewsFeed:
    """Return a cached official Garena Taiwan news feed.

    The cache prevents per-user traffic from becoming upstream traffic. If a
    refresh fails after at least one success, the previous feed remains usable
    and is explicitly marked stale.
    """
    clean_category = str(category or "all").strip().lower()
    if clean_category not in _ALLOWED_CATEGORIES:
        clean_category = "all"

    global _CACHE_FEED, _CACHE_MONOTONIC
    with _CACHE_LOCK:
        age = time.monotonic() - _CACHE_MONOTONIC
        if (
            not force_refresh
            and _CACHE_FEED is not None
            and age < _cache_seconds()
        ):
            return _filtered(_CACHE_FEED, clean_category, limit)

        try:
            fresh = _fetch_official_feed()
        except Exception:
            if _CACHE_FEED is not None:
                stale = replace(
                    _CACHE_FEED,
                    status="stale",
                    message="Garena 官方消息暫時無法更新，目前顯示上一份成功快取。",
                )
                return _filtered(stale, clean_category, limit)
            return GameNewsFeed(
                status="unavailable",
                fetched_at=None,
                items=(),
                message="Garena 官方消息暫時無法讀取，稍後恢復後會自動更新。",
            )

        _CACHE_FEED = fresh
        _CACHE_MONOTONIC = time.monotonic()
        return _filtered(fresh, clean_category, limit)


def reset_delta_news_cache() -> None:
    global _CACHE_FEED, _CACHE_MONOTONIC
    with _CACHE_LOCK:
        _CACHE_FEED = None
        _CACHE_MONOTONIC = 0.0
