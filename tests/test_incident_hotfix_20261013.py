from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from services import self_service_runtime
from web.app.routers import admin_dashboard


def test_self_service_financial_runtime_configures_without_bot_reexport(monkeypatch):
    captured = {}

    def fake_configure_self_service_financials(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        self_service_runtime,
        "configure_self_service_financials",
        fake_configure_self_service_financials,
    )

    namespace = {
        "POINT_REDEEM_ITEMS_BY_KEY": {},
        "_to_int": lambda value, default=0: default,
        "allocate_store_absorbed_fixed_discount": lambda *args, **kwargs: None,
        "get_current_reward_points": lambda *args, **kwargs: 0,
        "get_customer_reward_data": lambda *args, **kwargs: {},
        "get_effective_member_level": lambda *args, **kwargs: {"name": "普通魔丸"},
        "get_self_service_quantity_unit": lambda *args, **kwargs: "小時",
        "get_vip_discount_pay_rate": lambda *args, **kwargs: 100,
    }

    self_service_runtime.configure_self_service_runtime(namespace)

    assert captured["order_point_benefit_specs"] is self_service_runtime.ORDER_POINT_BENEFIT_SPECS
    assert callable(captured["self_service_staff_price"])
    assert captured["self_service_staff_price"] is self_service_runtime.get_self_service_staff_price


def test_admin_dashboard_meta_loader_handles_existing_table():
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as db:
        db.execute(
            text(
                """
                CREATE TABLE web_admin_order_meta (
                    order_id INTEGER PRIMARY KEY,
                    internal_note TEXT NOT NULL DEFAULT '',
                    needs_attention INTEGER NOT NULL DEFAULT 0,
                    attention_reason TEXT NOT NULL DEFAULT ''
                )
                """
            )
        )
        db.execute(
            text(
                """
                INSERT INTO web_admin_order_meta
                    (order_id, internal_note, needs_attention, attention_reason)
                VALUES
                    (123, 'test note', 1, 'check me')
                """
            )
        )

        result = admin_dashboard._load_admin_order_meta_by_order(db)

    assert result[123]["internal_note"] == "test note"
    assert result[123]["needs_attention"] == 1


def test_admin_dashboard_meta_loader_handles_missing_table():
    engine = create_engine("sqlite:///:memory:")
    with Session(engine) as db:
        assert admin_dashboard._load_admin_order_meta_by_order(db) == {}


def test_admin_dashboard_no_longer_calls_removed_phase_helper():
    source = admin_dashboard.__file__
    from pathlib import Path

    text_source = Path(source).read_text(encoding="utf-8")
    assert "_mw4a2r6_meta_map(" not in text_source
    assert "_load_admin_order_meta_by_order(" in text_source
