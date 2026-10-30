from __future__ import annotations

import asyncio
import re
import time
from dataclasses import replace
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import aiohttp

from services.news.base import GameNewsFeed, NewsArticle

SOURCE_NAME = "Garena 三角洲行動官方"
SOURCE_URL = "https://deltaforce.garena.com/zh_tw/news/all"
_ORIGIN = "https://deltaforce.garena.com"
_TTL = 600
_DATE = re.compile(r"(?P<y>20\d{2})[/-](?P<m>\d{1,2})[/-](?P<d>\d{1,2})")
_PATH = re.compile(r"^/zh_tw/news/(?P<category>[a-z-]+)/(?P<id>[A-Za-z0-9_-]+)$")
_LABEL = {"system": "版本資訊", "announcement": "公告", "event": "活動"}


def _text(value: str) -> str:
    return " ".join(str(value or "").split())


def _cut(value: str, limit: int) -> str:
    value = _text(value)
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.articles: list[NewsArticle] = []
        self.href: str | None = None
        self.parts: list[str] = []
        self.heading: list[str] = []
        self.heading_depth = 0
        self.seen: set[str] = set()

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "a" and self.href is None:
            href = dict(attrs).get("href")
            if not href:
                return
            url = urljoin(_ORIGIN, href)
            parsed = urlparse(url)
            if parsed.scheme == "https" and parsed.netloc == "deltaforce.garena.com" and _PATH.match(parsed.path):
                self.href, self.parts, self.heading = url, [], []
        elif self.href and tag in {"h1", "h2", "h3", "h4", "strong"}:
            self.heading_depth += 1

    def handle_data(self, data: str) -> None:
        if not self.href:
            return
        value = _text(data)
        if value:
            self.parts.append(value)
            if self.heading_depth:
                self.heading.append(value)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.href and tag in {"h1", "h2", "h3", "h4", "strong"}:
            self.heading_depth = max(0, self.heading_depth - 1)
        if tag == "a" and self.href:
            self._finish()

    def _finish(self) -> None:
        url, full, heading = self.href, _text(" ".join(self.parts)), _text(" ".join(self.heading))
        self.href, self.parts, self.heading, self.heading_depth = None, [], [], 0
        if not url or not full or url in self.seen:
            return
        match = _PATH.match(urlparse(url).path)
        if not match:
            return
        date_match = _DATE.search(full)
        published = None
        if date_match:
            try:
                published = date(int(date_match.group("y")), int(date_match.group("m")), int(date_match.group("d")))
            except ValueError:
                pass
        body = full[date_match.end():].strip() if date_match else full
        body = re.sub(r"\s*閱讀更多\s*$", "", body).strip()
        title = _cut(heading or body, 140)
        if not title:
            return
        excerpt = body[len(heading):].strip(" -|｜:：") if heading and body.startswith(heading) else ""
        category = match.group("category")
        self.articles.append(NewsArticle(
            article_id=match.group("id"), title=title, url=url,
            category_key=category, category_label=_LABEL.get(category, "官方消息"),
            published_on=published, excerpt=_cut(excerpt, 220),
        ))
        self.seen.add(url)


def parse_garena_news_html(html: str) -> tuple[NewsArticle, ...]:
    parser = _Parser()
    parser.feed(str(html or ""))
    parser.close()
    return tuple(sorted(
        parser.articles,
        key=lambda row: (row.published_on is not None, row.published_on or date.min, row.article_id),
        reverse=True,
    ))


_cache: GameNewsFeed | None = None
_deadline = 0.0
_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def _fetch() -> GameNewsFeed:
    timeout = aiohttp.ClientTimeout(total=10, connect=5)
    headers = {"Accept-Language": "zh-TW,zh;q=0.9", "User-Agent": "MowanEntertainment-NewsBot/1.0"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        async with session.get(SOURCE_URL, allow_redirects=True) as response:
            if response.status != 200 or urlparse(str(response.url)).netloc != "deltaforce.garena.com":
                raise RuntimeError("Garena news source unavailable")
            articles = parse_garena_news_html(await response.text(errors="replace"))
    if not articles:
        raise RuntimeError("Garena news page contained no recognized articles")
    return GameNewsFeed(
        game_key="delta_force", status="ready", source_name=SOURCE_NAME, source_url=SOURCE_URL,
        fetched_at=datetime.now(timezone.utc), articles=articles[:40],
        message="消息由 Garena 三角洲行動台灣官方網站同步。",
    )


async def get_delta_force_news(*, force: bool = False) -> GameNewsFeed:
    global _cache, _deadline
    if not force and _cache is not None and time.monotonic() < _deadline:
        return _cache
    async with _get_lock():
        if not force and _cache is not None and time.monotonic() < _deadline:
            return _cache
        try:
            fresh = await _fetch()
        except Exception:
            if _cache is not None and _cache.articles:
                return replace(_cache, status="stale", message="Garena 官方消息暫時無法更新，以下保留最近一次成功同步內容。")
            return GameNewsFeed(
                game_key="delta_force", status="unavailable", source_name=SOURCE_NAME, source_url=SOURCE_URL,
                message="Garena 官方消息目前暫時無法讀取，稍後重新整理即可再次嘗試。",
            )
        _cache, _deadline = fresh, time.monotonic() + _TTL
        return fresh
