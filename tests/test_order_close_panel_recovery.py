import inspect

import pytest

from services.order_close_panel_recovery import (
    ensure_post_close_panel,
    is_order_already_closed,
)
from services.order_lifecycle_runtime import close_order_without_receipt_modal


@pytest.mark.parametrize(
    "order_data",
    [
        {"status": "closed"},
        {"status": "completed"},
        {"status": "done"},
        {"status": "active", "closed": True},
    ],
)
def test_is_order_already_closed(order_data):
    assert is_order_already_closed(order_data)


@pytest.mark.parametrize(
    "order_data",
    [
        {"status": "active"},
        {"status": "accepted_pending_pay"},
        {"status": "stored"},
        {},
    ],
)
def test_is_order_already_closed_rejects_non_closed(order_data):
    assert not is_order_already_closed(order_data)


def test_post_close_panel_is_sent_to_public_ticket_channel():
    source = inspect.getsource(ensure_post_close_panel)

    assert "order_channel.send(" in source
    assert 'order_data["post_close_panel_message_id"]' in source
    assert "interaction.followup" not in source


def test_reclosing_closed_order_repairs_panel_before_returning_guard_error():
    source = inspect.getsource(close_order_without_receipt_modal)

    recovery = source.index("if is_order_already_closed(order_data):")
    guard_reply = source.index("await interaction.response.send_message(str(exc), ephemeral=True)")

    assert recovery < guard_reply
    assert "await _recover_closed_order_panel(" in source
