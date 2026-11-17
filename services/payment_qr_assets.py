"""Upload VPS-owned payment QR images into Discord payment embeds.

This uses the existing untracked JPGs, never rewrites payment destination data.
An attachment:// image belongs to the private ticket message and does not
depend on a public image URL being available from Discord's image proxy.
"""
from __future__ import annotations

import logging
from pathlib import Path

import discord


_LOG = logging.getLogger(__name__)
PAYMENT_QR_ATTACHMENT_NAME = "mowan_payment_qr.jpg"
PAYMENT_QR_FILES = {
    "轉帳": "cathay_qr.jpg",
    "街口": "jkopay_qr.jpg",
}
PAYMENT_QR_ASSET_DIR = (
    Path(__file__).resolve().parents[1] / "web" / "app" / "static"
    / "images" / "payment"
)


def _positive_amount(amount: int | None) -> bool:
    try:
        return int(amount or 0) > 0
    except (TypeError, ValueError, OverflowError):
        return False


def prepare_payment_qr_attachment(
    embed: discord.Embed,
    *,
    payment_method: str | None,
    amount: int | None,
    asset_dir: Path | None = None,
) -> discord.File | None:
    """Return a file for the embed image, or show a safe missing-image notice.

    Callers must pass the returned file on the *same* send/edit request.
    Edits must pass attachments=[file] (or [] for another payment method)
    to remove previous QR images when switching between methods.
    """
    method = str(payment_method or "").strip()
    filename = PAYMENT_QR_FILES.get(method)
    if filename is None or not _positive_amount(amount):
        return None

    path = (asset_dir if asset_dir is not None else PAYMENT_QR_ASSET_DIR) / filename
    try:
        with path.open("rb") as source:
            is_jpeg = source.read(3) == b"\xff\xd8\xff"
        if not is_jpeg:
            raise ValueError("not a JPEG image")
        payment_file = discord.File(str(path), filename=PAYMENT_QR_ATTACHMENT_NAME)
    except (OSError, ValueError) as exc:
        _LOG.warning("Payment QR unavailable for method=%s asset=%s: %s", method, filename, exc)
        embed.add_field(
            name="付款 QR Code",
            value=(
                "⚠️ 暫時無法顯示付款 QR Code，"
                "請依上方付款資訊核對收款帳號後付款，或通知客服協助。"
            ),
            inline=False,
        )
        return None

    embed.add_field(
        name="付款 QR Code",
        value=f"請掃描下方的**{method} QR Code**，付款前核對收款資訊。",
        inline=False,
    )
    embed.set_image(url=f"attachment://{PAYMENT_QR_ATTACHMENT_NAME}")
    return payment_file
