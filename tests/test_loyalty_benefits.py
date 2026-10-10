from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text

from services import loyalty_benefits as loyalty
from services.order_rules import ORDER_RULES, get_service_quantity


def test_same_order_five_for_one_is_disabled():
    assert get_service_quantity(ORDER_RULES["basic_entertain_single"], 5) == 5
    assert ORDER_RULES["basic_entertain_single"].loyalty_benefits_enabled is True


def test_old_valorant_rules_are_removed():
    assert "valorant_entertain" not in ORDER_RULES
    assert "valorant_tech" not in ORDER_RULES
    assert "valorant_top_tech" not in ORDER_RULES


def test_zero_progress_is_not_listed(monkeypatch, tmp_path: Path):
    db = tmp_path / "loyalty.db"
    test_engine = create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(loyalty, "engine", test_engine)
    loyalty.ensure_loyalty_tables(test_engine)
    assert loyalty.list_customer_loyalty("1")["progress"] == []


def test_coupon_value_uses_normal_list_price_not_vip_discount():
    coupon = {"benefit_kind": "extra_hours", "benefit_units": 0.5}
    value = loyalty.calculate_coupon_service_value(
        rule_key="basic_entertain_single",
        player_count=1,
        coupon=coupon,
    )
    assert value == 160
