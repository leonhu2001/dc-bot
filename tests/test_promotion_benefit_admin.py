from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from services import promotion_benefits as benefits
from services.promotion_benefit_admin import update_template
from services.self_service_financial_copy import _rewrite_quote_text


def _rules(amount: int = 1500) -> dict:
    return {
        "effect_kind": benefits.EFFECT_FIXED_CASH,
        "effect_value": amount,
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


def _issued_row(db_path, issued_id: int) -> dict:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM promotion_issued_benefits WHERE id=?",
            (issued_id,),
        ).fetchone()
    assert row is not None
    return dict(row)


def test_template_update_can_sync_only_untouched_active_issued_benefits(tmp_path):
    db_path = tmp_path / "benefits.db"
    template_id = benefits.create_template(
        name="舊主播券",
        rules=_rules(1500),
        actor_discord_id="manager",
        web_db=db_path,
    )
    untouched = benefits.issue_benefit(
        template_id=template_id,
        customer_discord_id="1",
        web_db=db_path,
    )
    reserved = benefits.issue_benefit(
        template_id=template_id,
        customer_discord_id="2",
        web_db=db_path,
    )
    partially_used = benefits.issue_benefit(
        template_id=template_id,
        customer_discord_id="3",
        web_db=db_path,
    )
    expired = benefits.issue_benefit(
        template_id=template_id,
        customer_discord_id="4",
        expires_at="2000-01-01T00:00:00+08:00",
        web_db=db_path,
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE promotion_issued_benefits SET status='reserved', reserved_order_id=99 WHERE id=?",
            (reserved,),
        )
        conn.execute(
            "UPDATE promotion_issued_benefits SET redeemed_order_id=77 WHERE id=?",
            (partially_used,),
        )
        conn.commit()

    new_rules = _rules(500)
    new_rules.update(
        {
            "funding": benefits.FUNDING_SHARED,
            "scope_type": "category",
            "scope_values": ["valorant"],
            "excluded_rule_keys": ["valorant_ranked"],
            "usage_limit": 2,
        }
    )
    result = update_template(
        template_id,
        name="新版 500T 券",
        rules=new_rules,
        sync_unused_issued=True,
        actor_discord_id="manager",
        web_db=db_path,
    )

    assert result["synced_count"] == 1
    untouched_row = _issued_row(db_path, untouched)
    untouched_rules = json.loads(untouched_row["rules_snapshot_json"])
    assert untouched_row["title"] == "新版 500T 券"
    assert untouched_row["remaining_uses"] == 2
    assert untouched_rules["effect_value"] == 500
    assert untouched_rules["funding"] == benefits.FUNDING_SHARED
    assert untouched_rules["scope_values"] == ["valorant"]

    for issued_id in (reserved, partially_used, expired):
        row = _issued_row(db_path, issued_id)
        old_rules = json.loads(row["rules_snapshot_json"])
        assert old_rules["effect_value"] == 1500
        assert row["title"] == "舊主播券"

    template = benefits.get_template(template_id, web_db=db_path)
    assert template is not None
    assert template["name"] == "新版 500T 券"
    assert template["effect_value"] == 500
    assert template["scope_values"] == ["valorant"]


def test_admin_benefits_ui_uses_normal_selects_and_checkbox_pickers():
    root = Path(__file__).resolve().parents[1]
    template = (root / "web/app/templates/admin_benefits.html").read_text(encoding="utf-8")
    css = (root / "web/app/static/css/pages/admin_benefits.css").read_text(encoding="utf-8")
    workspace_js = (root / "web/app/static/js/pages/admin_order_detail_inline_1.js").read_text(encoding="utf-8")

    assert "<datalist" not in template
    assert 'name="scope_category_values"' in template
    assert 'name="scope_rule_values"' in template
    assert 'name="excluded_rule_keys"' in template
    assert 'name="sync_unused_issued"' in template
    assert "input[type=checkbox]" in css
    assert "新制 +3%" in workspace_js
    assert "前月已發放薪資達 5000T" in workspace_js


def test_checkout_copy_keeps_shared_cash_and_store_promotion_distinct():
    original = (
        "點數折價 -50（店內吸收）｜"
        "固定折扣 -100（活動，店內吸收，不影響打手分潤）｜"
        "累積福利 -500（店內吸收，不影響打手分潤）"
    )

    store_text = _rewrite_quote_text(original, promotion_funding="store")
    assert "點數折價 -50（共同分攤，折後金額計入分潤基準）" in store_text
    assert "固定折扣 -100（活動，共同分攤，折後金額計入分潤基準）" in store_text
    assert "累積福利 -500（店家吸收，不降低打手／客服分潤基準）" in store_text

    shared_text = _rewrite_quote_text(original, promotion_funding="shared")
    assert "累積福利 -500（共同分攤，折後金額計入分潤基準）" in shared_text
