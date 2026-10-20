from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from services import self_service_retract_runtime_fix as retract_fix
from services import vip_timer_selector_order_v3 as v3


def test_v3_gameplay_labels_match_requested_layers():
    assert v3._gameplay_label(
        source_group="娛樂陪",
        detail_label="單陪",
        variant="基礎",
        service_type="單陪",
    ) == "娛樂"
    assert v3._gameplay_label(
        source_group="技術陪",
        detail_label="機密雙陪",
        variant="基礎",
        service_type="雙陪",
    ) == "技術｜機密"
    assert v3._gameplay_label(
        source_group="技術陪",
        detail_label="絕密單陪",
        variant="基礎",
        service_type="單陪",
    ) == "技術｜絕密"
    assert v3._gameplay_label(
        source_group="超凡陪",
        detail_label="NG｜陪玩2名",
        variant="",
        service_type="雙陪",
    ) == "技術｜超凡"
    assert v3._gameplay_label(
        source_group="甜蜜單",
        detail_label="女單陪",
        variant="",
        service_type="女單陪",
    ) == "甜蜜"
    assert v3._gameplay_label(
        source_group="教學單",
        detail_label="1對1教學",
        variant="",
        service_type="1對1教學",
    ) == "教學"


def test_v3_fourth_layer_uses_headcount_for_normal_gameplay():
    rule = SimpleNamespace(required_staff_count="player_count", min_player_count=1, label="娛樂陪")
    assert v3._headcount_service_type("娛樂陪", {"player_count": 1}, rule) == "單陪"
    assert v3._headcount_service_type("娛樂陪", {"player_count": 2}, rule) == "雙陪"
    assert v3._headcount_service_type("娛樂陪", {"player_count": 3}, rule) == "三陪"
    assert v3._headcount_service_type("娛樂陪", {"player_count": 4}, rule) == "四陪"
    assert v3._headcount_service_type("娛樂陪", {"player_count": 5}, rule) == "不支援"


def test_v3_fourth_layer_preserves_sweet_gender_packages():
    cases = [
        ("女單陪", 1),
        ("男單陪", 1),
        ("女雙陪", 2),
        ("男雙陪", 2),
    ]
    for label, count in cases:
        rule = SimpleNamespace(required_staff_count=count, label=f"三角洲端遊｜甜蜜單｜{label}")
        assert v3._headcount_service_type("甜蜜單", {"label": label}, rule) == label

    any_rule = SimpleNamespace(required_staff_count=2, label="三角洲端遊｜甜蜜單｜雙陪(不限)")
    assert v3._headcount_service_type("甜蜜單", {"label": "雙陪(不限)"}, any_rule) == "不支援"


def test_v3_fourth_layer_teaching_is_explicit_one_to_one():
    rule = SimpleNamespace(required_staff_count=1, label="APEX｜教學單｜1對1")
    assert v3._headcount_service_type("教學單", {"label": "1對1"}, rule) == "1對1教學"


def test_v3_gameplay_order_places_entertainment_then_technical_then_sweet_teaching():
    groups = [
        {"label": "教學", "min_rate": 300},
        {"label": "技術｜絕密", "min_rate": 500},
        {"label": "甜蜜", "min_rate": 520},
        {"label": "娛樂", "min_rate": 300},
        {"label": "技術｜機密", "min_rate": 400},
    ]
    assert [row["label"] for row in sorted(groups, key=v3._group_sort_key)] == [
        "娛樂",
        "技術｜機密",
        "技術｜絕密",
        "甜蜜",
        "教學",
    ]


def test_retract_fix_defers_before_reading_refactored_runtime(monkeypatch):
    from services import self_service_retract
    from services import self_service_runtime as runtime

    deferred = {"value": False}

    class Response:
        async def defer(self, **kwargs):
            deferred["value"] = True

        async def send_message(self, *args, **kwargs):
            raise AssertionError("authorized path should defer, not send before runtime lookup")

    class Followup:
        def __init__(self):
            self.send = AsyncMock()

    fake_state = SimpleNamespace(
        order_selections={123: {"customer_id": 456}},
        order_claims={},
        dispatch_channel_id=789,
    )

    def require_state():
        assert deferred["value"] is True
        return fake_state

    async def fake_retract(*args, **kwargs):
        return "已撤回派單"

    monkeypatch.setattr(retract_fix, "is_customer_staff", lambda user: True)
    monkeypatch.setattr(retract_fix, "is_manager_or_admin", lambda user: False)
    monkeypatch.setattr(runtime, "_require_runtime_state", require_state)
    monkeypatch.setattr(self_service_retract, "retract_self_service_dispatch", fake_retract)

    user = MagicMock(spec=discord.Member)
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 123
    interaction = SimpleNamespace(
        user=user,
        channel=channel,
        guild=MagicMock(),
        response=Response(),
        followup=Followup(),
        message=None,
    )

    asyncio.run(retract_fix._fixed_retract_dispatch(object(), interaction, object()))

    assert deferred["value"] is True
    interaction.followup.send.assert_awaited_once()
    assert interaction.followup.send.await_args.args[0].startswith("已撤回派單")


def test_retract_view_install_replaces_persistent_button_callback():
    from services.self_service_retract import SelfServiceDispatchedView

    retract_fix.install_self_service_retract_runtime_fix()
    view = SelfServiceDispatchedView()
    button = next(
        item for item in view.children
        if str(getattr(item, "custom_id", "")) == "self_service_retract_dispatch_button"
    )
    assert getattr(button.callback, "__module__", "") == retract_fix.__name__
