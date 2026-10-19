from pathlib import Path


SERVICE = Path("web/app/services/admin_order_workspace_field_write.py")


def test_field_write_preserves_closed_at_and_acceptance_status_rules():
    source = SERVICE.read_text(encoding="utf-8")

    assert "substr(closed_at, 1, 10) = :closed_date" in source
    assert "THEN datetime('now', '+8 hours')" in source
    assert '"completed": "closed"' in source
    assert '"done": "closed"' in source
    assert '"canceled": "cancelled"' in source


def test_field_write_resolves_existing_customer_service_when_form_is_blank():
    source = SERVICE.read_text(encoding="utf-8")

    assert 'before.get("customer_service_discord_id")' in source
    assert 'before.get("customer_service_display_name")' in source
    assert "get_staff_member_by_id(" in source
    assert "get_staff_display_name(" in source
