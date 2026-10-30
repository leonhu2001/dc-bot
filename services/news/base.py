from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class NewsArticle:
    article_id: str
    title: str
    url: str
    category_key: str
    category_label: str
    published_on: date | None = None
    excerpt: str = ""


@dataclass(frozen=True)
class GameNewsFeed:
    game_key: str
    status: str
    source_name: str
    source_url: str
    fetched_at: datetime | None = None
    articles: tuple[NewsArticle, ...] = field(default_factory=tuple)
    message: str = ""
