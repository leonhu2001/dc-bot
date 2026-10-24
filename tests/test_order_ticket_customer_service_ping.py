from pathlib import Path
import inspect


ROOT = Path(__file__).resolve().parents[1]


def test_quick_order_ticket_pings_customer_service_without_new_version_copy():
    from services import quick_order_v2 as quick

    source = inspect.getsource(quick._create_ticket)
    entry_source = inspect.getsource(quick.build_entry_embed)

    assert "support_mention = role.mention" in source
    assert "roles=True" in source
    assert "新版快速下單票口" not in source
    assert "建立新版下單票口" not in source
    assert "新版測試中" not in entry_source


def test_custom_order_ticket_pings_customer_service():
    from services import custom_order_quick_entry as custom

    source = inspect.getsource(custom._create_custom_order_request_ticket)
    assert "support_mention = support_role.mention" in source
    assert "roles=True" in source


def test_website_order_ticket_pings_customer_service():
    from services.web_sync import order_created

    source = inspect.getsource(order_created._web_order_created_ensure_ticket)
    assert "support_mention = support_role.mention" in source
    assert "roles=True" in source


def test_reorder_ticket_already_pings_customer_service():
    source = (ROOT / "services" / "self_service_reorder.py").read_text(encoding="utf-8")
    assert "support_mention" in source
    assert "roles=True" in source
