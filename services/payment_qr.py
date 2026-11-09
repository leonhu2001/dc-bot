from __future__ import annotations

from pathlib import Path

import discord

# Use the two JPGs uploaded by the store owner. Never synthesize bank QR codes:
# a wrong encoding would send the customer to the wrong account.
_PAYMENT_QR_FILENAMES = {
    "轉帳": "cathay_qr.jpg",
    "銀行轉帳": "cathay_qr.jpg",
    "bank_transfer": "cathay_qr.jpg",
    "街口": "jkopay_qr.jpg",
    "街口支付": "jkopay_qr.jpg",
    "jkopay": "jkopay_qr.jpg",
}
_PAYMENT_IMAGE_DIR = Path(__file__).resolve().parents[1] / "web" / "app" / "static" / "images" / "payment"


def payment_qr_path(method: str | None) -> Path | None:
    filename = _PAYMENT_QR_FILENAMES.get(str(method or "").strip())
    if filename is None:
        return None
    path = _PAYMENT_IMAGE_DIR / filename
    return path if path.is_file() else None


def payment_qr_file(method: str | None) -> discord.File | None:
    path = payment_qr_path(method)
    if path is None:
        return None
    return discord.File(path, filename=path.name)


def attach_payment_qr(embed: discord.Embed, method: str | None) -> discord.File | None:
    """Attach exact customer-supplied image to its corresponding payment embed."""
    attached = payment_qr_file(method)
    if attached is not None:
        embed.set_image(url=f"attachment://{attached.filename}")
    return attached


def payment_qr_missing(method: str | None) -> bool:
    """Bank or JKO method selected but its configured QR file isn't available."""
    return str(method or "").strip() in _PAYMENT_QR_FILENAMES and payment_qr_path(method) is None
