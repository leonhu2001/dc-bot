from pathlib import Path
import re


path = Path("tests/test_game_service_rules.py")
text = path.read_text(encoding="utf-8")

replacement = '''def test_new_game_orders_split_entertainment_and_technical_point_rewards():
    common = dict(point_balance=999, quantity=1, has_specified_staff=False)

    for rule_key in ("valorant_entertain_ng", "lol_entertain_ng"):
        assert point_item_status(
            rule_key=rule_key,
            point_item_key="discount_50",
            **common,
        )["allowed"] is True

        assert point_item_status(
            rule_key=rule_key,
            point_item_key="entertain_service_small",
            **common,
        )["allowed"] is True

        assert point_item_status(
            rule_key=rule_key,
            point_item_key="tech_service_small",
            **common,
        )["allowed"] is False

        # 沒有指定陪玩時，不應出現免指定費兌換。
        assert point_item_status(
            rule_key=rule_key,
            point_item_key="free_specify_fee",
            **common,
        )["allowed"] is False


def test_game_priced_entertainment_rewards_are_one_and_two_games():
    options = {
        item["key"]: item
        for item in list_point_options(
            rule_key="valorant_entertain_ranked",
            point_balance=999,
            quantity=1,
            has_specified_staff=False,
        )
    }

    small = options["entertain_service_small"]
    assert small["allowed"] is True
    assert small["name"] == "娛樂陪加贈｜1 局"
    assert small["kind"] == "extra_games"
    assert small["games"] == 1
    assert small["cost"] == 80

    large = options["entertain_service_large"]
    assert large["allowed"] is True
    assert large["name"] == "娛樂陪加贈｜2 局"
    assert large["kind"] == "extra_games"
    assert large["games"] == 2
    assert large["cost"] == 140

    assert options["tech_service_small"]["allowed"] is False
    assert options["tech_service_large"]["allowed"] is False
    assert "extra_game_1" not in options
    assert "extra_game_2" not in options


def test_hourly_entertainment_rewards_are_30_minutes_and_one_hour():
    options = {
        item["key"]: item
        for item in list_point_options(
            rule_key="lol_entertain_aram",
            point_balance=999,
            quantity=1,
            has_specified_staff=False,
        )
    }

    small = options["entertain_service_small"]
    assert small["allowed"] is True
    assert small["name"] == "娛樂陪加贈｜30 分鐘"
    assert small["kind"] == "extra_hours"
    assert small["hours"] == 0.5
    assert small["cost"] == 80

    large = options["entertain_service_large"]
    assert large["allowed"] is True
    assert large["name"] == "娛樂陪加贈｜1 小時"
    assert large["kind"] == "extra_hours"
    assert large["hours"] == 1
    assert large["cost"] == 140

    assert options["tech_service_small"]["allowed"] is False
    assert options["tech_service_large"]["allowed"] is False
    assert "extra_hour_30m" not in options
    assert "extra_hour_1h" not in options


'''

pattern = re.compile(
    r"def test_new_game_orders_split_hourly_and_game_point_rewards\(\):.*?(?=def test_all_new_game_orders_have_exact_receiver_roles\(\):)",
    re.S,
)
updated, count = pattern.subn(replacement, text, count=1)
if count != 1:
    raise RuntimeError(f"expected one point reward test block, replaced {count}")

path.write_text(updated, encoding="utf-8")
