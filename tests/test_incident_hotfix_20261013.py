from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from services import self_service_financials, self_service_runtime
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
    monkeypatch.setattr(
        self_service_runtime,
        "configure_self_service_reorder",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        self_service_runtime,
        "configure_self_service_selection_runtime",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        self_service_runtime,
        "configure_reorder_ticket_creator",
        lambda *_args, **_kwargs: None,
    )

    point_redeem_items_by_key = {}
    self_service_runtime.configure_self_service_runtime_explicit(
        customer_category_id=1,
        customer_role_id=2,
        dispatch_channel_id=3,
        order_claims={},
        point_redeem_items=[],
        point_redeem_items_by_key=point_redeem_items_by_key,
        order_selections={},
        order_control_view_type=object,
    )

    assert captured["order_point_benefit_specs"] is self_service_runtime.ORDER_POINT_BENEFIT_SPECS
    assert captured["point_redeem_items_by_key"] is point_redeem_items_by_key
    assert captured["to_int"] is self_service_runtime._to_int
    assert (
        captured["store_absorbed_discount_allocator"]
        is self_service_runtime.allocate_store_absorbed_fixed_discount
    )
    assert captured["current_reward_points"] is self_service_runtime.get_current_reward_points
    assert captured["customer_reward_data"] is self_service_runtime.get_customer_reward_data
    assert captured["effective_member_level"] is self_service_runtime.get_effective_member_level
    assert captured["self_service_quantity_unit"] is self_service_runtime.get_self_service_quantity_unit
    assert captured["vip_discount_pay_rate"] is self_service_runtime.get_vip_discount_pay_rate
    assert "self_service_staff_price" not in captured
    assert "staff_price_required" not in captured
    assert self_service_runtime.get_self_service_staff_price is self_service_financials.get_self_service_staff_price
    assert (
        self_service_runtime.is_self_service_staff_price_required
        is self_service_financials.is_self_service_staff_price_required
    )
    assert not hasattr(self_service_runtime, "configure_self_service_runtime")


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
