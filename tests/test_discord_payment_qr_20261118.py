"""Cathay/JKO payment QR stays on the one canonical Discord payment embed."""
from __future__ import annotations

from pathlib import Path

import discord
import pytest

from services.order_flow import build_payment_method_embed, get_payment_method_info
from services.payment_qr_assets import (
    PAYMENT_QR_ATTACHMENT_NAME,
    PAYMENT_QR_ASSET_DIR,
    PAYMENT_QR_FILES,
    prepare_payment_qr_attachment,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("method,filename", [
    ("轉帳", "cathay_qr.jpg"),
    ("街口", "jkopay_qr.jpg"),
])
def test_existing_real_qr_filename_is_loaded_in_correct_payment_embed(
    tmp_path: Path, method: str, filename: str,
) -> None:
    # The actual QR scans remain on the VPS; use a tiny JPEG header in CI.
    (tmp_path / filename).write_bytes(b"\xff\xd8\xff\xe0" + b"test jpeg")
    embed = build_payment_method_embed(
        customer_id=123, category_label="三角洲", item="洗幣",
        quantity=1, amount=2480, payment_method=method,
    )
    qr_file = prepare_payment_qr_attachment(
        embed, payment_method=method, amount=2480, asset_dir=tmp_path,
    )
    assert qr_file is not None
    try:
        assert qr_file.filename == PAYMENT_QR_ATTACHMENT_NAME
        assert qr_file.fp.name.endswith(filename)
        assert embed.to_dict()["image"]["url"] == (
            "attachment://" + PAYMENT_QR_ATTACHMENT_NAME
        )
        assert any(field.name == "付款資訊" for field in embed.fields)
        assert any(field.name == "付款 QR Code" for field in embed.fields)
        assert get_payment_method_info(method).splitlines()[0] in embed.description + " ".join(
            field.value for field in embed.fields
        )
    finally:
        qr_file.close()


@pytest.mark.parametrize("method,amount", [
    ("我的錢包", 2480),
    ("轉帳", 0),
    ("街口", 0),
    (None, 2480),
    ("待付款", 2480),
    ("等待接單人數補滿", 2480),
    ("未知方式", 2480),
])
def test_non_external_or_zero_amount_never_shows_a_payment_qr(
    tmp_path: Path, method: str | None, amount: int,
) -> None:
    embed = discord.Embed(title="付款方式")
    qr_file = prepare_payment_qr_attachment(
        embed, payment_method=method, amount=amount, asset_dir=tmp_path,
    )
    assert qr_file is None
    assert "image" not in embed.to_dict()
    assert not embed.fields


@pytest.mark.parametrize("method", ["轉帳", "街口"])
def test_missing_real_qr_is_visible_to_customer_without_changing_payment_account(
    tmp_path: Path, method: str,
) -> None:
    embed = build_payment_method_embed(
        customer_id=123, category_label="三角洲",
        item="服務", quantity=1, payment_method=method, amount=2480,
    )
    original_info = get_payment_method_info(method)
    assert original_info is not None
    qr_file = prepare_payment_qr_attachment(
        embed, payment_method=method, amount=2480, asset_dir=tmp_path,
    )
    assert qr_file is None
    assert "image" not in embed.to_dict()
    assert "QR Code" in embed.fields[-1].name
    assert "無法顯示" in embed.fields[-1].value
    assert original_info in embed.fields[0].value


def test_invalid_jpeg_is_not_uploaded_or_displayed_as_scan_code(tmp_path: Path):
    (tmp_path / "jkopay_qr.jpg").write_text("not actually a QR", encoding="utf-8")
    embed = discord.Embed(title="付款方式")
    qr_file = prepare_payment_qr_attachment(
        embed, payment_method="街口", amount=1, asset_dir=tmp_path,
    )
    assert qr_file is None
    assert "image" not in embed.to_dict()
    assert "無法顯示" in embed.fields[-1].value


def test_asset_paths_and_ignored_payment_images_are_preserved():
    assert PAYMENT_QR_FILES == {
        "轉帳": "cathay_qr.jpg",
        "街口": "jkopay_qr.jpg",
    }
    assert PAYMENT_QR_ASSET_DIR == ROOT / "web/app/static/images/payment"
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for filename in PAYMENT_QR_FILES.values():
        assert "web/app/static/images/payment/" + filename in gitignore


def test_all_payment_message_paths_attach_or_clear_the_previous_qr():
    sources = {
        path: (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "services/acceptance/payment_panel.py",
            "services/order_runtime.py",
            "services/order_payment_review_submission.py",
            "services/order_payment_runtime.py",
        )
    }
    for path in ("services/acceptance/payment_panel.py",
                 "services/order_payment_review_submission.py"):
        source = sources[path]
        assert "prepare_payment_qr_attachment(" in source, path
        assert "attachments=[qr_file] if qr_file is not None else []" in source, path
    assert "edit_payment_qr_interaction(" in sources["services/order_runtime.py"]
    assert "edit_payment_qr_message(" in sources["services/order_payment_runtime.py"]
    qr_helper = (ROOT / "services/payment_qr_assets.py").read_text(encoding="utf-8")
    assert "attachments=[image] if image is not None else []" in qr_helper
    panel = sources["services/acceptance/payment_panel.py"]
    assert 'send_kwargs["file"] = qr_file' in panel
    assert "attachments=[]" in panel  # invalidated acceptances clear stale QR


def test_qr_fix_does_not_alter_pricing_or_payment_destination_text():
    bank = get_payment_method_info("轉帳")
    jko = get_payment_method_info("街口")
    assert bank is not None and bank.startswith("銀行轉帳-國泰")
    assert jko is not None and jko.startswith("街口支付")
    assert get_payment_method_info("我的錢包") is None
