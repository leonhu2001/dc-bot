from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bot.py"
SERVICE = ROOT / "services" / "order_lifecycle_runtime.py"
BUDGET = ROOT / "tests" / "test_architecture_growth_budget.py"
SMOKE = ROOT / "tools" / "runtime_import_smoke.py"
TEST = ROOT / "tests" / "test_order_lifecycle_runtime_extraction.py"

START = "async def ensure_payment_submit_receipt("
END = "# ========= 自助下單資料 ========="

IMPORT_ANCHOR = "from services.payment_review_runtime import ensure_payment_review_worker_started\n"
CONFIG_ANCHOR = "configure_order_runtime(globals())\nconfigure_self_service_runtime(globals())"

SERVICE_IMPORT = '''from services.order_lifecycle_runtime import (\n    configure_order_lifecycle_runtime,\n    ensure_payment_submit_receipt,\n    ReceiptModal,\n    get_stored_order_amount_or_none,\n    close_order_without_receipt_modal,\n    ConfirmCloseOrderView,\n    CANCEL_REASON_OPTIONS,\n    OrderCancellationReasonSelect,\n    ConfirmCancelOrderView,\n)\n'''

SERVICE_HEADER = '''from __future__ import annotations\n\nfrom typing import Any, Mapping\n\nimport asyncio\nimport discord\n\n\n_REQUIRED_DEPENDENCIES = (\n    "RECEIPT_CHANNEL_ID",\n    "SELF_SERVICE_ORDER_SELECTIONS",\n    "ORDER_CATEGORY_LABELS",\n    "_to_int",\n    "format_t_amount",\n    "parse_receipt_amount",\n    "generate_order_receipt_id",\n    "get_taipei_now",\n    "get_taipei_now_iso",\n    "get_taipei_now_text",\n    "remember_order_data",\n    "send_order_log",\n    "is_customer_staff",\n    "get_order_customer_id_from_channel",\n    "get_order_summary_from_channel",\n    "sync_web_order_closed_from_bot",\n    "sync_web_order_cancelled_from_bot",\n    "refresh_staff_profile_panels_for_order",\n    "lock_dispatch_claim_panel",\n    "delete_dispatch_claim_panel_for_order",\n    "rename_ticket_channel",\n    "build_post_close_status_embed",\n    "ReviewButtonView",\n)\n\n_CONFIGURED = False\n\n\ndef configure_order_lifecycle_runtime(namespace: Mapping[str, Any]) -> None:\n    \"\"\"Bind the bot-owned lifecycle adapters after bot.py finishes defining them.\"\"\"\n    global _CONFIGURED\n\n    missing = [name for name in _REQUIRED_DEPENDENCIES if name not in namespace]\n    if missing:\n        raise RuntimeError(\n            "order lifecycle runtime missing dependencies: " + ", ".join(missing)\n        )\n\n    for name in _REQUIRED_DEPENDENCIES:\n        globals()[name] = namespace[name]\n\n    _CONFIGURED = True\n\n\n'''


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    source = BOT.read_text(encoding="utf-8")
    require(START in source, "order lifecycle start anchor missing")
    require(END in source, "order lifecycle end anchor missing")
    require(IMPORT_ANCHOR in source, "payment review import anchor missing")
    require(CONFIG_ANCHOR in source, "runtime configure anchor missing")
    require("from services.order_lifecycle_runtime import (" not in source, "lifecycle runtime already extracted")

    start = source.index(START)
    end = source.index(END, start)
    block = source[start:end].rstrip() + "\n"

    required_symbols = (
        "async def ensure_payment_submit_receipt(",
        "class ReceiptModal(",
        "def get_stored_order_amount_or_none(",
        "async def close_order_without_receipt_modal(",
        "class ConfirmCloseOrderView(",
        "CANCEL_REASON_OPTIONS = [",
        "class OrderCancellationReasonSelect(",
        "class ConfirmCancelOrderView(",
    )
    for symbol in required_symbols:
        require(symbol in block, f"extraction block missing {symbol}")

    SERVICE.write_text(SERVICE_HEADER + block, encoding="utf-8")

    replacement = (
        "# ========= 訂單收據 / 結單 / 取消 lifecycle 已移至 services/order_lifecycle_runtime.py =========\n\n"
    )
    source = source[:start] + replacement + source[end:]
    source = source.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + SERVICE_IMPORT, 1)
    source = source.replace(
        CONFIG_ANCHOR,
        "configure_order_runtime(globals())\nconfigure_order_lifecycle_runtime(globals())\nconfigure_self_service_runtime(globals())",
        1,
    )
    BOT.write_text(source, encoding="utf-8")

    budget_source = BUDGET.read_text(encoding="utf-8")
    budget_source = budget_source.replace('"bot.py": 260_000,', '"bot.py": 235_000,', 1)
    budget_source = budget_source.replace(
        '"services/vip_voice_runtime.py": 12_000,',
        '"services/vip_voice_runtime.py": 12_000,\n    "services/order_lifecycle_runtime.py": 36_000,',
        1,
    )
    BUDGET.write_text(budget_source, encoding="utf-8")

    smoke_source = SMOKE.read_text(encoding="utf-8")
    smoke_source = smoke_source.replace(
        '    "services.order_runtime",',
        '    "services.order_runtime",\n    "services.order_lifecycle_runtime",',
        1,
    )
    SMOKE.write_text(smoke_source, encoding="utf-8")

    TEST.write_text(
        '''from __future__ import annotations\n\nimport importlib\nfrom pathlib import Path\n\n\nROOT = Path(__file__).resolve().parents[1]\nBOT = ROOT / "bot.py"\nSERVICE = ROOT / "services" / "order_lifecycle_runtime.py"\n\n\ndef test_order_lifecycle_is_canonical_in_service():\n    bot_source = BOT.read_text(encoding="utf-8")\n    service_source = SERVICE.read_text(encoding="utf-8")\n\n    assert "from services.order_lifecycle_runtime import (" in bot_source\n    assert "configure_order_lifecycle_runtime(globals())" in bot_source\n\n    for symbol in (\n        "async def ensure_payment_submit_receipt(",\n        "class ReceiptModal(",\n        "def get_stored_order_amount_or_none(",\n        "async def close_order_without_receipt_modal(",\n        "class ConfirmCloseOrderView(",\n        "class OrderCancellationReasonSelect(",\n        "class ConfirmCancelOrderView(",\n    ):\n        assert symbol not in bot_source\n        assert symbol in service_source\n\n\ndef test_order_lifecycle_runtime_import_smoke():\n    module = importlib.import_module("services.order_lifecycle_runtime")\n    assert callable(module.configure_order_lifecycle_runtime)\n    assert callable(module.ensure_payment_submit_receipt)\n    assert issubclass(module.ConfirmCloseOrderView, module.discord.ui.View)\n    assert issubclass(module.ConfirmCancelOrderView, module.discord.ui.View)\n\n\ndef test_lifecycle_runtime_uses_explicit_dependency_contract():\n    source = SERVICE.read_text(encoding="utf-8")\n    assert "_REQUIRED_DEPENDENCIES" in source\n    assert "import bot" not in source\n    assert "from bot import" not in source\n''',
        encoding="utf-8",
    )

    print("order lifecycle runtime extracted")
    print("bot.py bytes:", BOT.stat().st_size)
    print("order_lifecycle_runtime.py bytes:", SERVICE.stat().st_size)


if __name__ == "__main__":
    main()
