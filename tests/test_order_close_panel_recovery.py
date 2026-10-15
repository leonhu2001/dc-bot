import pytest

from services.order_close_panel_recovery import is_order_already_closed


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
