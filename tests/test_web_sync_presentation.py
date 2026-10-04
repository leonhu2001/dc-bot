from services.web_sync import presentation


def test_build_receiver_text_keeps_boosters_before_companions():
    rows = [
        {
            "worker_discord_id": "202",
            "worker_display_name": "陪玩",
            "role_type": "companion",
        },
        {
            "worker_discord_id": "101",
            "worker_display_name": "打手",
            "role_type": "booster",
        },
        {
            "worker_discord_id": "",
            "worker_display_name": "忽略",
            "role_type": "booster",
        },
    ]

    assert presentation.build_receiver_text(rows) == "<@101>\n<@202>"
    assert presentation.build_receiver_text([]) == "尚未有人接單"


def test_parse_json_helpers_keep_existing_fallback_behavior():
    assert presentation.parse_json_object('{"a": 1}') == {"a": 1}
    assert presentation.parse_json_object("[1, 2]", {"fallback": True}) == {
        "fallback": True
    }
    assert presentation.parse_json_object("not-json") == {}

    assert presentation.parse_json_list('[" 101 ", "", 202]') == [
        "101",
        "202",
    ]
    assert presentation.parse_json_list((" 1 ", "", 2)) == ["1", "2"]
    assert presentation.parse_json_list('{"a": 1}') == []


def test_build_order_created_details_preserves_snapshot_precedence():
    bundle = {
        "order": {
            "item": "護航",
            "quantity": "2",
            "amount": "900",
            "customer_pay_amount": None,
            "category": "raw-category",
            "order_rule_key": "order-key",
            "payment_method": "order-payment",
            "rule_snapshot_json": (
                '{"key":"rule-key","category":"unknown-category",'
                '"player_count":3,"required_game_role_ids":["301"]}'
            ),
            "price_snapshot_json": (
                '{"order_rule_key":"price-key","customer_pay_amount":1200,'
                '"player_count":4,"specified_staff_ids":["101"]}'
            ),
        },
        "acceptance": {
            "required_staff_count": "2",
            "specified_staff_ids_json": "[]",
            "allowed_role_ids_json": '["201"]',
            "required_game_role_ids_json": "[]",
        },
        "submission": {
            "request_key": "req-1",
            "extra_requirements": " 要求 ",
            "terms_version": "v1",
            "terms_accepted_at": "2026-10-04T00:00:00",
            "submission_payload_json": (
                '{"payment_method":"wallet","specified_staff_ids":["999"]}'
            ),
        },
    }

    details = presentation.build_order_created_details(bundle)

    assert details["rule_key"] == "rule-key"
    assert details["category_key"] == "unknown-category"
    assert details["category_label"] == "raw-category"
    assert details["item"] == "護航"
    assert details["quantity"] == 2
    assert details["player_count"] == 4
    assert details["amount"] == 1200
    assert details["website_payment_method"] == "wallet"
    assert details["specified_staff_ids"] == ["101"]
    assert details["allowed_role_ids"] == ["201"]
    assert details["required_game_role_ids"] == ["301"]
    assert details["required_staff_count"] == 2
    assert details["request_key"] == "req-1"
    assert details["extra_requirements"] == "要求"


def test_build_order_created_details_falls_back_to_submission_staff_ids():
    bundle = {
        "order": {
            "item": "娛樂陪",
            "quantity": None,
            "amount": "500",
            "category": "custom",
            "rule_snapshot_json": "{}",
            "price_snapshot_json": "{}",
        },
        "acceptance": {},
        "submission": {
            "submission_payload_json": (
                '{"selected_staff_ids":["501","502"],'
                '"payment_method_key":"manual"}'
            ),
        },
    }

    details = presentation.build_order_created_details(bundle)

    assert details["quantity"] == 1
    assert details["player_count"] == 1
    assert details["amount"] == 500
    assert details["specified_staff_ids"] == ["501", "502"]
    assert details["website_payment_method"] == "manual"
    assert details["required_staff_count"] == 1
