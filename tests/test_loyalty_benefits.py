from pathlib import Path

from services.loyalty_benefits import (
    get_customer_benefit_snapshot,
    list_available_coupons,
    record_paid_service,
    reserve_coupon,
    consume_coupon,
    restore_coupon,
)
from services.order_rules import ORDER_RULES, OrderRule


def _install_rule(monkeypatch, key="test_loyalty_hourly", pricing_type="hourly", threshold=10, reward=0.5):
    rule = OrderRule(
        category="basic", key=key, label="測試福利", pricing_type=pricing_type,
        price=300, point_benefits_allowed=True,
        loyalty_threshold_units=threshold, loyalty_reward_units=reward,
    )
    monkeypatch.setitem(ORDER_RULES, key, rule)
    return rule


def test_hourly_progress_starts_only_after_paid_service_and_issues_at_ten(monkeypatch, tmp_path):
    _install_rule(monkeypatch)
    db = tmp_path / "loyalty.db"
    assert get_customer_benefit_snapshot("1", db_file=db)["progress"] == []
    first = record_paid_service(
        customer_id="1", rule_key="test_loyalty_hourly", player_count=1,
        paid_units=9, source_order_key="WEB-1", completed_at="2026-10-10T10:00:00+08:00", db_file=db,
    )
    assert first["issued"] == []
    snapshot = get_customer_benefit_snapshot("1", db_file=db)
    assert len(snapshot["progress"]) == 1
    assert snapshot["progress"][0]["paid_units"] == 9
    second = record_paid_service(
        customer_id="1", rule_key="test_loyalty_hourly", player_count=1,
        paid_units=1, source_order_key="WEB-2", completed_at="2026-10-10T11:00:00+08:00", db_file=db,
    )
    assert len(second["issued"]) == 1
    assert second["progress"]["paid_units"] == 0


def test_game_twenty_to_one_and_duplicate_order_is_idempotent(monkeypatch, tmp_path):
    _install_rule(monkeypatch, key="test_game", pricing_type="game", threshold=20, reward=1)
    db = tmp_path / "loyalty.db"
    result = record_paid_service(
        customer_id="2", rule_key="test_game", player_count=2,
        paid_units=20, source_order_key="DC-99", completed_at="2026-10-11T00:00:00+08:00", db_file=db,
    )
    assert len(result["issued"]) == 1
    duplicate = record_paid_service(
        customer_id="2", rule_key="test_game", player_count=2,
        paid_units=20, source_order_key="DC-99", completed_at="2026-10-11T00:00:00+08:00", db_file=db,
    )
    assert duplicate["duplicate"] is True
    assert len(list_available_coupons("2", rule_key="test_game", player_count=2, db_file=db)) == 1


def test_pre_program_orders_do_not_backfill(monkeypatch, tmp_path):
    _install_rule(monkeypatch)
    db = tmp_path / "loyalty.db"
    result = record_paid_service(
        customer_id="3", rule_key="test_loyalty_hourly", player_count=1,
        paid_units=100, source_order_key="OLD", completed_at="2026-10-09T23:59:59+08:00", db_file=db,
    )
    assert result["eligible"] is False
    assert get_customer_benefit_snapshot("3", db_file=db)["progress"] == []


def test_coupon_reserve_consume_restore_lifecycle(monkeypatch, tmp_path):
    _install_rule(monkeypatch, key="test_game", pricing_type="game", threshold=20, reward=1)
    db = tmp_path / "loyalty.db"
    issued = record_paid_service(
        customer_id="4", rule_key="test_game", player_count=3,
        paid_units=20, source_order_key="WEB-4", completed_at="2026-10-12T10:00:00+08:00", db_file=db,
    )["issued"][0]
    reserve_coupon(
        issued["id"], customer_id="4", rule_key="test_game", player_count=3,
        reservation_key="WEB-5", db_file=db,
    )
    consume_coupon(issued["id"], customer_id="4", used_order_key="WEB-5", db_file=db)
    assert list_available_coupons("4", db_file=db) == []
    assert restore_coupon(issued["id"], customer_id="4", db_file=db) is True
    assert len(list_available_coupons("4", rule_key="test_game", player_count=3, db_file=db)) == 1
