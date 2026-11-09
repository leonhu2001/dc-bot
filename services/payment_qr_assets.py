"""Discord attachment helpers for customer-payment QR images.

QR files belong in web/app/static/images/payment/, but are attached to
Discord messages directly (no assumption that the dashboard URL is public).
The public account text remains available when an image is absent.
"""
from __future__ import annotations

from pathlib import Path

import discord

_PAYMENT_IMAGE_DIR = (
    Path(__file__).resolve().parents[1]
    / "web" / "app" / "static" / "images" / "payment"
)
PAYMENT_QR_FILENAMES = {
    "轉帳": "cathay_qr.jpg",
    "街口": "jkopay_qr.jpg",
}
_ATTACHMENT_NAME = "payment_qr.jpg"


def payment_qr_path(method: str | None) -> Path | None:
    name = PAYMENT_QR_FILENAMES.get(str(method or "").strip())
    if name is None:
        return None
    path = _PAYMENT_IMAGE_DIR / name
    return path if path.is_file() else None


def payment_qr_file(method: str | None) -> discord.File | None:
    path = payment_qr_path(method)
    return discord.File(path, filename=_ATTACHMENT_NAME) if path else None


def apply_payment_qr_embed(embed: discord.Embed, method: str | None) -> discord.Embed:
    if payment_qr_path(method) is not None:
        embed.set_image(url=f"attachment://{_ATTACHMENT_NAME}")
    return embed


def payment_qr_send_kwargs(method: str | None) -> dict:
    image = payment_qr_file(method)
    return {"file": image} if image is not None else {}


def payment_qr_edit_kwargs(method: str | None) -> dict:
    # Explicitly replace old attachments when changing from bank to JKO,
    # or remove them if customer switches to wallet.
    image = payment_qr_file(method)
    return {"attachments": [image] if image is not None else []}
