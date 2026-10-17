import asyncio
from types import SimpleNamespace

from services import wallet_discord_runtime as runtime


def test_wallet_discord_adapter_preserves_operator_metadata(monkeypatch):
    captured = {}

    def fake_adjust(**kwargs):
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(runtime, "adjust_wallet_balance", fake_adjust)
    operator = SimpleNamespace(id=77, display_name="客服甲", name="fallback")

    result = runtime.adjust_customer_wallet_balance(
        customer_id=88,
        amount=-300,
        tx_type=" payment ",
        operator=operator,
        order_channel_id=99,
        order_no="MO-1",
        note="測試",
    )

    assert result == {"ok": True}
    assert captured == {
        "customer_id": 88,
        "amount": -300,
        "tx_type": "payment",
        "operator_discord_id": 77,
        "operator_display_name": "客服甲",
        "order_channel_id": 99,
        "order_no": "MO-1",
        "note": "測試",
        "allow_negative": False,
    }


def test_wallet_log_delegates_to_order_log(monkeypatch):
    captured = {}

    async def fake_log(guild, **kwargs):
        captured["guild"] = guild
        captured.update(kwargs)

    monkeypatch.setattr(runtime, "send_order_log", fake_log)
    customer = SimpleNamespace(mention="<@88>")
    operator = SimpleNamespace(id=77, mention="<@77>")
    tx = {"amount": -300, "balance_before": 1000, "balance_after": 700, "note": "測試"}

    asyncio.run(
        runtime.send_wallet_log(
            object(),
            title="錢包測試",
            customer=customer,
            operator=operator,
            tx=tx,
        )
    )

    assert captured["title"] == "錢包測試"
    assert captured["fields"][0] == ("顧客", "<@88>", True)
    assert captured["fields"][-1] == ("備註", "測試", False)
