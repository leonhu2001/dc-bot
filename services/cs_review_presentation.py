"""One presentation contract for Discord customer-service review notices.

Only the embed/CTA appearance lives here.  Review authorization, durable
outbox/retries, destination channels and financial transitions stay owned by
their existing services.  Pure dict output supports both discord.py and the
Web worker's Discord REST sender without importing the Bot runtime.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Any


REVIEW_FOOTER = "魔丸娛樂｜客服審核中心 · 請以後台審核結果為準"
REVIEW_ACTION_LABEL = "前往審核"
COLOR_PENDING = 0xE7B95B
COLOR_SUCCESS = 0x45B891
COLOR_REJECTED = 0xE47474
COLOR_NEUTRAL = 0x8693A8
COLOR_WARNING = 0xEFA35F

_DONE = frozenset({
    "approved", "applied", "completed", "crediting",
    "approved_pending_apply", "approved_pending_credit",
})
_FAILED = frozenset({"rejected", "reject", "denied", "declined"})
_NEUTRAL = frozenset({"cancelled", "canceled"})
_WARNING = frozenset({"apply_error", "error", "failed"})


def review_color(status: str) -> int:
    current = str(status or "").strip().lower()
    if current in _DONE:
        return COLOR_SUCCESS
    if current in _FAILED:
        return COLOR_REJECTED
    if current in _NEUTRAL:
        return COLOR_NEUTRAL
    if current in _WARNING:
        return COLOR_WARNING
    return COLOR_PENDING


def _safe(value: Any, *, limit: int = 1024) -> str:
    raw = str(value if value is not None else "").strip()
    if not raw:
        raw = "—"
    # Display names and user-supplied notes must not trigger unexpected mentions.
    raw = (raw.replace("@everyone", "@\u200beveryone")
           .replace("@here", "@\u200bhere")
           .replace("<@", "<@\u200b"))
    return raw[:limit]


def review_embed_payload(
    *,
    category: str,
    status: str,
    status_label: str,
    description: str,
    reference: str | None = None,
    applicant: str | None = None,
    amount: int | None = None,
    fields: Iterable[tuple[str, object, bool]] = (),
    footer_note: str | None = None,
) -> dict:
    """Same readable hierarchy: type/status -> identity -> amount -> details."""
    output = {
        "title": f"📋 客服審核｜{_safe(category, limit=48)}｜{_safe(status_label, limit=48)}",
        "description": _safe(description, limit=2048),
        "color": review_color(status),
        "fields": [],
        "footer": {"text": REVIEW_FOOTER},
    }
    if footer_note:
        output["footer"]["text"] = _safe(
            REVIEW_FOOTER + " · " + str(footer_note), limit=2048,
        )
    if reference:
        output["fields"].append({
            "name": "案件編號", "value": _safe(reference), "inline": True,
        })
    if applicant:
        output["fields"].append({
            "name": "申請人／老闆", "value": _safe(applicant), "inline": True,
        })
    if amount is not None:
        output["fields"].append({
            "name": "金額", "value": f"{int(amount):,}T", "inline": True,
        })
    for name, value, inline in fields:
        if len(output["fields"]) >= 25:
            break
        output["fields"].append({
            "name": _safe(name, limit=256),
            "value": _safe(value),
            "inline": bool(inline),
        })
    return output


def review_link_components(url: str) -> list[dict]:
    """Native Discord link button; no direct approval or permission bypass."""
    if not str(url).startswith("https://"):
        raise ValueError("審核網址必須是 HTTPS")
    return [{
        "type": 1,
        "components": [{
            "type": 2, "style": 5,
            "label": REVIEW_ACTION_LABEL, "url": str(url),
        }],
    }]


def review_notification_text(category: str, *, reference: str | None = None) -> str:
    """Short announcement above the embed; details belong inside fields."""
    suffix = f"｜{_safe(reference, limit=90)}" if reference else ""
    return f"📋 {str(category)}待審核{suffix}"
