from pathlib import Path

from services import order_credential_runtime as credentials


ROOT = Path(__file__).resolve().parents[1]


def test_credential_placeholder_api_updates_named_field():
    field = credentials.OrderCredentialModal.login_note
    original = field.placeholder
    try:
        assert credentials.set_order_credential_note_placeholder("測試登入備註") is True
        assert field.placeholder == "測試登入備註"
    finally:
        credentials.set_order_credential_note_placeholder(original or "登入方式／備註")


def test_aw_catalog_uses_public_credential_api_not_deprecated_label_introspection():
    source = (ROOT / "services" / "aw_collision_catalog.py").read_text(encoding="utf-8")
    assert "set_order_credential_note_placeholder" in source
    assert 'getattr(item, "label"' not in source
    assert "__modal_children_items__" not in source
