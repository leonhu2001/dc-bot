from web.app.routers.order_history import history_resolve_status_edit


def test_history_cannot_create_cancellation_without_structured_flow():
    assert history_resolve_status_edit("stored", "cancelled") == "stored"
    assert history_resolve_status_edit("active", "cancelled") == "active"


def test_history_preserves_terminal_states():
    assert history_resolve_status_edit("closed", "active") == "closed"
    assert history_resolve_status_edit("cancelled", "stored") == "cancelled"


def test_history_still_allows_non_cancellation_maintenance():
    assert history_resolve_status_edit("stored", "active") == "active"
    assert history_resolve_status_edit("stored", "closed") == "closed"

def test_web_order_maps_closed_at_for_history_queries():
    from shared.models import WebOrder

    assert "closed_at" in WebOrder.__table__.columns
    assert WebOrder.closed_at is not None

