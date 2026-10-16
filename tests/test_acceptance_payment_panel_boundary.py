from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SOURCE = (ROOT / "services/acceptance/runtime.py").read_text(encoding="utf-8")
DISPATCH_REFRESH_SOURCE = (
    ROOT / "services/acceptance/dispatch_refresh.py"
).read_text(encoding="utf-8")
REPAIR_SOURCE = (ROOT / "services/acceptance/repair_runtime.py").read_text(encoding="utf-8")
PAYMENT_SOURCE = (ROOT / "services/acceptance/payment_panel.py").read_text(encoding="utf-8")


def test_acceptance_payment_panel_has_single_owner():
    assert "from services.order_flow import build_payment_method_embed" not in RUNTIME_SOURCE
    assert "from services.order_flow import build_payment_method_embed" not in DISPATCH_REFRESH_SOURCE
    assert "from services.order_flow import build_payment_method_embed" not in REPAIR_SOURCE
    assert "from services.order_flow import build_payment_method_embed" in PAYMENT_SOURCE

    assert "ensure_acceptance_payment_panel(" not in RUNTIME_SOURCE
    assert "ensure_acceptance_payment_panel(" in DISPATCH_REFRESH_SOURCE
    assert "ensure_acceptance_payment_panel(" in REPAIR_SOURCE
    assert "invalidate_acceptance_payment_panel(" not in RUNTIME_SOURCE
    assert "invalidate_acceptance_payment_panel(" in DISPATCH_REFRESH_SOURCE


def test_repair_runtime_does_not_own_payment_message_persistence():
    for legacy_fragment in (
        "payment_message = await ticket_channel.send(",
        "existing_message.edit(",
        "data[\"payment_message_id\"] =",
        "data[\"payment_channel_id\"] =",
    ):
        assert legacy_fragment not in REPAIR_SOURCE


def test_payment_panel_module_owns_normal_restore_and_invalidation_paths():
    expected_fragments = (
        "async def ensure_acceptance_payment_panel(",
        "reuse_existing: bool = False",
        "async def invalidate_acceptance_payment_panel(",
        "data[\"payment_message_id\"] = int(payment_message.id)",
        "data.pop(\"payment_message_id\", None)",
        "remember_order_data(channel_id, data)",
        "save_bot_data()",
    )

    for fragment in expected_fragments:
        assert fragment in PAYMENT_SOURCE
