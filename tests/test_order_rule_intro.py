from starlette.datastructures import FormData

from services import order_rule_store
from services.order_rule_store import (
    ensure_order_rule_store,
    publish_rule_override,
)
from services.order_rules import (
    get_base_rule,
    invalidate_rule_override_cache,
    rule_to_override_payload,
)
from web.app.routers.admin_order_rules import _payload_from_form_base
from web.app.services.order_groups import get_grouped_order_catalog


def test_admin_form_keeps_note_and_intro_separate():
    base = rule_to_override_payload(get_base_rule("fun_read_no_reply"))
    form = FormData(
        [
            ("label", "一命通關"),
            ("catalog_group_label", "一命通關"),
            ("pricing_type", "fixed"),
            ("unit_label", "單"),
            ("note", "五撤挑戰"),
            ("intro", "需連撤五把\n且都要吃 1000w"),
            ("price", "13888"),
            ("min_quantity", "1"),
            ("specify_fee_default", "0"),
            ("min_player_count", "2"),
            ("min_protector_count", "0"),
            ("required_staff_count", "2"),
            ("max_quantity", "1"),
            ("max_specified_count", "2"),
            ("specify_free_min_units", ""),
            ("max_player_count", "2"),
            ("allow_specify", "on"),
            ("allowed_roles", "top_protector"),
            ("required_game_roles", "delta_desktop"),
        ]
    )

    payload = _payload_from_form_base(base, form)

    assert payload["note"] == "五撤挑戰"
    assert payload["intro"] == "需連撤五把\n且都要吃 1000w"


def test_catalog_exposes_intro_without_replacing_card_note(
    tmp_path,
    monkeypatch,
):
    db_file = tmp_path / "web_dashboard.db"
    ensure_order_rule_store(db_file)
    monkeypatch.setattr(
        order_rule_store,
        "default_db_path",
        lambda: db_file,
    )

    key = "fun_read_no_reply"
    payload = rule_to_override_payload(get_base_rule(key))
    payload["label"] = "一命通關"
    payload["catalog_group_label"] = "一命通關"
    payload["note"] = "五撤挑戰"
    payload["intro"] = "需連撤五把\n且都要吃 1000w"

    publish_rule_override(
        rule_key=key,
        payload=payload,
        actor_discord_id="1",
        actor_display_name="Tester",
        expected_active_version=0,
        db_file=db_file,
    )
    invalidate_rule_override_cache()

    groups = get_grouped_order_catalog("delta_desktop_fun")
    group = next(item for item in groups if item["label"] == "一命通關")
    variant = next(
        item
        for item in group["variants"]
        if item["rule_key"] == key
    )

    assert variant["note"] == "五撤挑戰"
    assert variant["intro"] == "需連撤五把\n且都要吃 1000w"

    invalidate_rule_override_cache()
