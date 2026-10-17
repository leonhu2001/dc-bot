from __future__ import annotations

import json
import sqlite3

from services import promotion_benefits as benefits


def _make_template(db_path, **overrides) -> int:
    rules = {
        "effect_kind": benefits.EFFECT_FIXED_CASH,
        "effect_value": 1500,
        "funding": benefits.FUNDING_STORE,
        "min_order_amount": 0,
        "scope_type": "all",
        "scope_values": [],
        "excluded_rule_keys": [],
        "valid_days": 30,
        "usage_limit": 1,
        "consume_mode": "one_shot",
        "seat_mode": "one_seat",
        "include_specify_fee": False,
        "allow_vip_discount": True,
        "allow_points": False,
    }
    rules.update(overrides)
    return benefits.create_template(
        name="主播宣傳 1500T",
        rules=rules,
        actor_discord_id="manager",
        web_db=db_path,
    )


def test_selection_id_round_trip():
    encoded = benefits.encode_selection_id(42)
    assert encoded < -1_000_000_000
    assert benefits.decode_selection_id(encoded) == 42
    assert benefits.decode_selection_id(42) is None


def test_issued_benefit_freezes_template_snapshot(tmp_path):
    db_path = tmp_path / "benefits.db"
    template_id = _make_template(db_path)
    issued_id = benefits.issue_benefit(
        template_id=template_id,
        customer_discord_id="123",
        actor_discord_id="manager",
        web_db=db_path,
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE promotion_benefit_templates SET effect_value=999 WHERE id=?",
            (template_id,),
        )
        row = conn.execute(
            "SELECT rules_snapshot_json FROM promotion_issued_benefits WHERE id=?",
            (issued_id,),
        ).fetchone()
        conn.commit()

    snapshot = json.loads(row[0])
    assert snapshot["effect_value"] == 1500


def test_minimum_and_scope_are_revalidated(tmp_path):
    db_path = tmp_path / "benefits.db"
    template_id = _make_template(
        db_path,
        min_order_amount=2000,
        scope_type="category",
        scope_values=["valorant"],
    )
    issued_id = benefits.issue_benefit(
        template_id=template_id,
        customer_discord_id="123",
        web_db=db_path,
    )

    assert benefits.list_applicable_issued_benefits(
        "123",
        rule_key="valorant_entertain",
        category="valorant",
        original_service_amount=1999,
        web_db=db_path,
    ) == []

    applicable = benefits.list_applicable_issued_benefits(
        "123",
        rule_key="valorant_entertain",
        category="valorant",
        original_service_amount=2000,
        web_db=db_path,
    )
    assert len(applicable) == 1
    assert applicable[0]["issued_benefit_id"] == issued_id

    assert benefits.list_applicable_issued_benefits(
        "123",
        rule_key="apex_entertain",
        category="apex",
        original_service_amount=5000,
        web_db=db_path,
    ) == []


def test_store_funded_fixed_benefit_calculates_expected_discount(tmp_path):
    db_path = tmp_path / "benefits.db"
    template_id = _make_template(db_path)
    benefits.issue_benefit(
        template_id=template_id,
        customer_discord_id="123",
        web_db=db_path,
    )
    item = benefits.list_applicable_issued_benefits(
        "123",
        rule_key="any",
        category="basic",
        original_service_amount=1200,
        web_db=db_path,
    )[0]

    # The customer may pay zero, but funding semantics are carried separately;
    # checkout keeps worker/CS payout basis unchanged for store-funded benefits.
    assert item["funding"] == benefits.FUNDING_STORE
    assert benefits.calculate_discount_amount(
        item,
        service_amount_after_percent=1200,
        original_service_amount=1200,
        specify_fee=0,
        quantity=1,
        staff_count=1,
    ) == 1200


def test_percent_and_waive_specify_effects(tmp_path):
    db_path = tmp_path / "benefits.db"
    percent_template = _make_template(
        db_path,
        effect_kind=benefits.EFFECT_PERCENT,
        effect_value=25,
        funding=benefits.FUNDING_SHARED,
    )
    benefits.issue_benefit(
        template_id=percent_template,
        customer_discord_id="p",
        web_db=db_path,
    )
    percent_item = benefits.list_applicable_issued_benefits(
        "p", rule_key="x", category="basic", original_service_amount=1000, web_db=db_path
    )[0]
    assert benefits.calculate_discount_amount(
        percent_item,
        service_amount_after_percent=1000,
        original_service_amount=1000,
        specify_fee=0,
        quantity=1,
        staff_count=1,
    ) == 250

    specify_template = _make_template(
        db_path,
        effect_kind=benefits.EFFECT_WAIVE_SPECIFY,
        effect_value=0,
        include_specify_fee=True,
    )
    benefits.issue_benefit(
        template_id=specify_template,
        customer_discord_id="s",
        web_db=db_path,
    )
    specify_item = benefits.list_applicable_issued_benefits(
        "s", rule_key="x", category="basic", original_service_amount=1000, web_db=db_path
    )[0]
    assert benefits.calculate_discount_amount(
        specify_item,
        service_amount_after_percent=1000,
        original_service_amount=1000,
        specify_fee=100,
        quantity=1,
        staff_count=1,
    ) == 100
