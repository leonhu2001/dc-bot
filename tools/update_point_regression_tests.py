from pathlib import Path


def main() -> None:
    dispatch = Path("tests/test_dispatch_claim_access.py")
    text = dispatch.read_text(encoding="utf-8")
    old = '''                    "point": {
                        "key": "extra_10",
                        "name": "加時 30 分鐘",
                        "cost": 15,
                    },'''
    new = '''                    "point": {
                        "key": "extra_hour_30m",
                        "name": "加時 30 分鐘",
                        "cost": 60,
                    },'''
    if old not in text:
        raise SystemExit("nested dispatch point fixture not found")
    dispatch.write_text(text.replace(old, new, 1), encoding="utf-8")

    game = Path("tests/test_game_service_rules.py")
    text = game.read_text(encoding="utf-8")
    start_marker = "def test_new_game_orders_allow_points_except_extra_game_and_unusable_specify_fee():"
    end_marker = "def test_all_new_game_orders_have_exact_receiver_roles():"
    start = text.index(start_marker)
    end = text.index(end_marker, start)

    replacement = '''def test_new_game_orders_split_hourly_and_game_point_rewards():
    common = dict(point_balance=999, quantity=1, has_specified_staff=False)

    for rule_key in ("valorant_entertain_ng", "lol_entertain_ng"):
        assert point_item_status(
            rule_key=rule_key,
            point_item_key="discount_20",
            **common,
        )["allowed"] is True

        assert point_item_status(
            rule_key=rule_key,
            point_item_key="extra_hour_30m",
            **common,
        )["allowed"] is True

        assert point_item_status(
            rule_key=rule_key,
            point_item_key="extra_game_1",
            **common,
        )["allowed"] is False

        # 沒有指定陪玩時，不應出現免指定費兌換。
        assert point_item_status(
            rule_key=rule_key,
            point_item_key="free_specify_fee",
            **common,
        )["allowed"] is False


def test_game_priced_point_rewards_are_one_and_two_games_only():
    options = {
        item["key"]: item
        for item in list_point_options(
            rule_key="valorant_entertain_ranked",
            point_balance=999,
            quantity=1,
            has_specified_staff=False,
        )
    }

    assert options["extra_game_1"]["allowed"] is True
    assert options["extra_game_1"]["name"] == "加 1 局"
    assert options["extra_game_1"]["kind"] == "extra_games"
    assert options["extra_game_1"]["games"] == 1
    assert options["extra_game_1"]["cost"] == 40

    assert options["extra_game_2"]["allowed"] is True
    assert options["extra_game_2"]["name"] == "加 2 局"
    assert options["extra_game_2"]["kind"] == "extra_games"
    assert options["extra_game_2"]["games"] == 2
    assert options["extra_game_2"]["cost"] == 70

    assert "extra_hour_30m" not in options
    assert "extra_hour_1h" not in options
    assert "extra_15" not in options


def test_hourly_point_rewards_are_30_minutes_and_one_hour_only():
    options = {
        item["key"]: item
        for item in list_point_options(
            rule_key="lol_entertain_aram",
            point_balance=999,
            quantity=1,
            has_specified_staff=False,
        )
    }

    assert options["extra_hour_30m"]["name"] == "加時 30 分鐘"
    assert options["extra_hour_30m"]["kind"] == "extra_hours"
    assert options["extra_hour_30m"]["hours"] == 0.5
    assert options["extra_hour_30m"]["cost"] == 60

    assert options["extra_hour_1h"]["name"] == "加時 1 小時"
    assert options["extra_hour_1h"]["kind"] == "extra_hours"
    assert options["extra_hour_1h"]["hours"] == 1
    assert options["extra_hour_1h"]["cost"] == 110

    assert "extra_game_1" not in options
    assert "extra_game_2" not in options


'''
    game.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


if __name__ == "__main__":
    main()
