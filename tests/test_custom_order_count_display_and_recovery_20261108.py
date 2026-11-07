from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from services import custom_order_quick_entry as custom
from services import self_service_ui_runtime as ui
from services.orders import get_order_item_details_for_group
from services.self_service_selection_state import sync_custom_order_headcount_detail


def test_custom_order_count_is_one_source_of_truth_and_preserves_quote():
    draft = {
        "order_rule_key": "custom_custom_order",
        "category": "custom",
        "item_detail_value": "players_1",
        "player_count": 2,
        "custom_order_companion_count": 1,
        "manual_staff_amount": 2500,
        "manual_discount_percent": 90,
        "specified_staff_ids": ["200000000000000000"],
    }
    assert sync_custom_order_headcount_detail(draft)
    assert draft["item_detail_value"] == "players_2"
    assert draft["custom_order_companion_count"] == 2
    assert draft["manual_staff_amount"] == 2500
    assert draft["manual_discount_percent"] == 90
    assert draft["specified_staff_ids"] == ["200000000000000000"]
    assert not sync_custom_order_headcount_detail(draft)


def test_custom_order_selector_offers_four_counts_not_four_different_specs():
    details = get_order_item_details_for_group("custom", "自訂")
    assert [d["value"] for d in details] == [
        "players_1", "players_2", "players_3", "players_4",
    ]
    assert [d["label"] for d in details] == [
        "1 位陪玩", "2 位陪玩", "3 位陪玩", "4 位陪玩",
    ]


def test_existing_custom_order_draft_realigns_count_without_resetting_staff_price(monkeypatch):
    ticket_id = 700001
    original = {
        "category": "custom",
        "item_group": "自訂",
        "item": "自訂單",
        "order_rule_key": "custom_custom_order",
        "item_detail_value": "players_1",
        "player_count": 2,
        "quantity": 1,
        "manual_staff_amount": 3000,
        "manual_discount_percent": 90,
    }
    remembered = []
    monkeypatch.setattr(ui, "SELF_SERVICE_ORDER_SELECTIONS", {ticket_id: original})
    monkeypatch.setattr(
        "core.database.remember_order_data",
        lambda channel, data: remembered.append((channel, dict(data))),
    )
    result = custom._seed_custom_order_self_service(
        ticket_id, customer_id=123456, companion_count=2
    )
    assert result["player_count"] == 2
    assert result["item_detail_value"] == "players_2"
    assert result["custom_order_companion_count"] == 2
    assert result["manual_staff_amount"] == 3000
    assert result["manual_discount_percent"] == 90
    assert remembered and remembered[-1][0] == ticket_id


def test_custom_order_embed_displays_custom_spec_and_actual_count(monkeypatch):
    monkeypatch.setattr(ui, "add_self_service_quote_preview", lambda embed, data, guild: embed)
    data = {
        "category": "custom",
        "item_group": "自訂",
        "order_rule_key": "custom_custom_order",
        "item_detail_value": "players_1",
        "item": "自訂單",
        "player_count": 2,
        "quantity": 1,
    }
    embed = ui.build_self_service_panel_embed(1234, data)
    specs = [f.value for f in embed.fields if "規格" in f.name]
    assert specs == ["自訂"]
    assert data["item_detail_value"] == "players_2"
    custom_embed = custom._build_custom_order_self_service_embed(1234, data, None)
    assert "目前陪玩人數：**2 位**" in custom_embed.description
    assert "規格統一顯示「自訂」" in custom_embed.description


def test_recovery_clears_outdated_setup_warning_after_panel_is_restored(monkeypatch):
    class FakeCategory:
        text_channels = []

    class FakeMessage:
        def __init__(self, content="", embeds=None):
            self.author = SimpleNamespace(id=77)
            self.content = content
            self.embeds = embeds or []
            self.components = []
            self.edit = AsyncMock()

    stale_panel = FakeMessage(
        embeds=[
            SimpleNamespace(
                title="自助下單｜自訂單",
                fields=[SimpleNamespace(name="第三欄｜規格", value="陪玩1名")],
            )
        ]
    )
    warning = FakeMessage(content="⚠️ 自訂單票口已建立，但部分下單資訊初始化失敗。")

    class FakeChannel:
        id = 54321
        topic = "custom_order_request=1;custom_order_customer_id=1234;custom_order_companion_count=2;order_customer_id=1234"
        guild = SimpleNamespace(get_role=lambda _id: None)

        async def history(self, *, limit=50):
            yield warning
            yield stale_panel

    channel = FakeChannel()
    category = FakeCategory()
    category.text_channels = [channel]
    monkeypatch.setattr(custom.discord, "CategoryChannel", FakeCategory)
    monkeypatch.setattr(custom, "_seed_custom_order_self_service", lambda *args, **kwargs: {
        "order_rule_key": "custom_custom_order",
        "item_detail_value": "players_2",
        "player_count": 2,
    })
    monkeypatch.setattr(custom, "_build_custom_order_self_service_embed", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(ui, "SelfServiceOrderView", lambda **kwargs: SimpleNamespace())
    monkeypatch.setattr(custom, "_order_control_view", lambda _bot: None)

    bot = SimpleNamespace(
        user=SimpleNamespace(id=77),
        get_channel=lambda _id: category,
        wait_until_ready=AsyncMock(),
    )
    asyncio.run(custom.repair_existing_custom_order_ticket_controls(bot))
    assert stale_panel.edit.await_count == 1
    assert warning.edit.await_count == 1
    assert "初始化警告已解除" in warning.edit.await_args.kwargs["content"]
