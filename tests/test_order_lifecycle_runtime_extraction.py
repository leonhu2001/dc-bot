from __future__ import annotations

import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bot.py"
SERVICE = ROOT / "services" / "order_lifecycle_runtime.py"


def test_order_lifecycle_is_canonical_in_service():
    bot_source = BOT.read_text(encoding="utf-8")
    service_source = SERVICE.read_text(encoding="utf-8")

    assert "from services.order_lifecycle_runtime import (" in bot_source
    assert "configure_order_lifecycle_runtime(globals())" in bot_source

    for symbol in (
        "async def ensure_payment_submit_receipt(",
        "class ReceiptModal(",
        "def get_stored_order_amount_or_none(",
        "async def close_order_without_receipt_modal(",
        "class ConfirmCloseOrderView(",
        "class OrderCancellationReasonSelect(",
        "class ConfirmCancelOrderView(",
    ):
        assert symbol not in bot_source
        assert symbol in service_source


def test_order_lifecycle_runtime_import_smoke():
    module = importlib.import_module("services.order_lifecycle_runtime")
    assert callable(module.configure_order_lifecycle_runtime)
    assert callable(module.ensure_payment_submit_receipt)
    assert issubclass(module.ConfirmCloseOrderView, module.discord.ui.View)
    assert issubclass(module.ConfirmCancelOrderView, module.discord.ui.View)


def test_lifecycle_runtime_uses_explicit_dependency_contract():
    source = SERVICE.read_text(encoding="utf-8")
    assert "_REQUIRED_DEPENDENCIES" in source
    assert "import bot" not in source
    assert "from bot import" not in source
