from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    file_path = ROOT / path
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"anchor missing in {path}: {old[:120]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Keep zero-payment routing decisions in a tiny pure policy module. Payment review
# and wallet services continue rejecting zero-value financial transactions.
(ROOT / "services/order_payment_policy.py").write_text(
    '''from __future__ import annotations

from services.payment_methods import WALLET_PAYMENT_METHOD


EXTERNAL_REVIEW_PAYMENT_METHODS = frozenset({"街口", "轉帳"})


def is_zero_amount_order(amount: int | None) -> bool:
    return int(amount or 0) == 0


def requires_external_payment_review(payment_method: str | None, amount: int | None) -> bool:
    return int(amount or 0) > 0 and str(payment_method or "") in EXTERNAL_REVIEW_PAYMENT_METHODS


def requires_wallet_debit(payment_method: str | None, amount: int | None) -> bool:
    return int(amount or 0) > 0 and str(payment_method or "") == WALLET_PAYMENT_METHOD
''',
    encoding="utf-8",
)

replace_once(
    "services/order_payment_runtime.py",
    "from services.payment_methods import WALLET_PAYMENT_METHOD\n",
    "from services.payment_methods import WALLET_PAYMENT_METHOD\n"
    "from services.order_payment_policy import (\n"
    "    is_zero_amount_order,\n"
    "    requires_external_payment_review,\n"
    "    requires_wallet_debit,\n"
    ")\n",
)

replace_once(
    "services/order_payment_runtime.py",
    '''    external_review_methods = {"街口", "轉帳"}\n\n    if str(payment_method) in external_review_methods and not data.get("payment_review_approved"):\n''',
    '''    zero_amount_order = is_zero_amount_order(amount)\n    if zero_amount_order:\n        # A fully discounted order still goes through the normal submit/finalize\n        # lifecycle, but it must not create a meaningless 0T payment review.\n        data["payment_zero_amount"] = True\n        data["payment_review_pending"] = False\n    else:\n        data.pop("payment_zero_amount", None)\n\n    if requires_external_payment_review(payment_method, amount) and not data.get("payment_review_approved"):\n''',
)

replace_once(
    "services/order_payment_runtime.py",
    '''        if payment_method == WALLET_PAYMENT_METHOD:\n            existing_wallet_tx_id = data.get("wallet_transaction_id")\n''',
    '''        if requires_wallet_debit(payment_method, amount):\n            existing_wallet_tx_id = data.get("wallet_transaction_id")\n''',
)

replace_once(
    "services/order_payment_runtime.py",
    '''        data["status"] = "active"\n        data["closed"] = False\n        data.pop("payment_processing", None)\n''',
    '''        data["status"] = "active"\n        data["closed"] = False\n        if zero_amount_order:\n            data["payment_zero_amount_completed_at"] = get_taipei_now_iso()\n        else:\n            data.pop("payment_zero_amount_completed_at", None)\n        data.pop("payment_processing", None)\n''',
)

replace_once(
    "services/order_lifecycle_runtime.py",
    "from services.payment_methods import WALLET_PAYMENT_METHOD\n",
    "from services.payment_methods import WALLET_PAYMENT_METHOD\n"
    "from services.order_payment_policy import is_zero_amount_order\n",
)

replace_once(
    "services/order_lifecycle_runtime.py",
    '''    payment_status_text = (\n        "已確認收款"\n        if payment_method == WALLET_PAYMENT_METHOD\n        or bool(order_data.get("payment_review_approved"))\n        else "已送出，待客服確認"\n    )\n''',
    '''    if is_zero_amount_order(amount):\n        payment_status_text = "免付款／已完成"\n    else:\n        payment_status_text = (\n            "已確認收款"\n            if payment_method == WALLET_PAYMENT_METHOD\n            or bool(order_data.get("payment_review_approved"))\n            else "已送出，待客服確認"\n        )\n''',
)

replace_once(
    "services/rewards.py",
    '''    amount = parse_receipt_amount(amount_text)\n    if amount is None or amount <= 0:\n        return "會員消費未累積：收據金額欄位沒有可辨識的數字。"\n\n    item = str(order_data.get("item") or "").strip()\n''',
    '''    amount = parse_receipt_amount(amount_text)\n    if amount is None:\n        return "會員消費未累積：收據金額欄位沒有可辨識的數字。"\n\n    if amount <= 0:\n        # 0T is a valid final customer-pay amount (for example a fully covered\n        # member coupon), not a parse failure. Mark reward handling complete so\n        # closing the order does not warn that reward processing was skipped.\n        # Keep reward_excluded=False so a later amount correction can still add\n        # the proper spend/points through sync_reward_counted_order_amount().\n        order_data["reward_counted"] = True\n        order_data["reward_amount"] = 0\n        order_data["reward_zero_amount"] = True\n        order_data["reward_excluded"] = False\n        order_data["reward_excluded_reason"] = ""\n        order_data["reward_counted_at"] = get_taipei_now_iso()\n        if _SAVE_BOT_DATA is not None:\n            _SAVE_BOT_DATA()\n        return "顧客實付為 0T，本單不增加會員累積消費或點數。"\n\n    item = str(order_data.get("item") or "").strip()\n''',
)

# A focused policy/reward regression covers the exact business semantics.
(ROOT / "tests/test_zero_amount_checkout.py").write_text(
    '''from __future__ import annotations

import asyncio
from types import SimpleNamespace

import services.rewards as rewards
from services.order_payment_policy import (
    is_zero_amount_order,
    requires_external_payment_review,
    requires_wallet_debit,
)


def test_zero_amount_payment_routing_skips_money_movement_but_positive_orders_do_not():
    assert is_zero_amount_order(0) is True
    assert is_zero_amount_order(1) is False

    assert requires_external_payment_review("轉帳", 0) is False
    assert requires_external_payment_review("街口", 0) is False
    assert requires_external_payment_review("轉帳", 1) is True
    assert requires_external_payment_review("街口", 1) is True

    assert requires_wallet_debit("我的錢包", 0) is False
    assert requires_wallet_debit("我的錢包", 1) is True


def test_zero_customer_pay_marks_reward_handling_complete_without_adding_spend_or_points():
    customer_id = 7001
    channel_id = 8001
    customer_rewards = {}
    order_data = {
        "customer_id": customer_id,
        "payment_method": "轉帳",
        "item": "娛樂陪〈端遊〉｜單陪",
    }
    orders = {channel_id: order_data}
    saves = []

    rewards.configure_reward_storage(customer_rewards)
    rewards.configure_reward_order_context(orders, lambda: saves.append(True))
    rewards.configure_rewards(
        member_levels=[{"name": "普通魔丸", "threshold": 0}],
        reward_point_divisor=100,
    )

    reward_data = rewards.get_customer_reward_data(customer_id)
    reward_data["total_spent"] = 2000
    reward_data["points"] = 20

    result = asyncio.run(
        rewards.add_customer_reward_from_order(
            guild=SimpleNamespace(),
            order_channel_id=channel_id,
            customer_id=customer_id,
            amount_text="0",
            notify_channel=None,
        )
    )

    assert "實付為 0T" in result
    assert reward_data["total_spent"] == 2000
    assert rewards.get_current_reward_points(reward_data) == 20
    assert order_data["reward_counted"] is True
    assert order_data["reward_amount"] == 0
    assert order_data["reward_zero_amount"] is True
    assert order_data["reward_excluded"] is False
    assert saves


def test_zero_reward_marker_can_be_corrected_to_positive_amount_later():
    customer_id = 7002
    rewards.configure_reward_storage({})
    rewards.configure_rewards(
        member_levels=[{"name": "普通魔丸", "threshold": 0}],
        reward_point_divisor=100,
    )
    order_data = {
        "customer_id": customer_id,
        "amount": 0,
        "total_amount": 0,
        "reward_counted": True,
        "reward_amount": 0,
        "reward_excluded": False,
    }

    result = rewards.sync_reward_counted_order_amount(order_data, 500)

    assert result is not None
    assert result["delta"] == 500
    assert rewards.get_customer_reward_data(customer_id)["total_spent"] == 500
    assert order_data["reward_amount"] == 500
''',
    encoding="utf-8",
)

# The Golden gate runs the real payment finalizer. External payment review and
# wallet debit are armed to fail if a 0T order accidentally reaches them.
golden = ROOT / "tests/golden/test_critical_runtime_flows.py"
golden_text = golden.read_text(encoding="utf-8")
golden_text = golden_text.replace(
    "from services import order_lifecycle_runtime, self_service_runtime\n",
    "from services import order_lifecycle_runtime, order_payment_runtime, self_service_runtime\n",
    1,
)
golden_text += r'''


def test_zero_amount_checkout_runs_real_payment_finalizer_without_review_or_wallet_debit(monkeypatch):
    from services import payment_reviews

    class FakeResponse:
        def __init__(self):
            self.done = False
            self.messages = []

        def is_done(self):
            return self.done

        async def defer(self, **_kwargs):
            self.done = True

        async def send_message(self, message, **_kwargs):
            self.done = True
            self.messages.append(message)

    class FakeFollowup:
        def __init__(self):
            self.messages = []

        async def send(self, message, **_kwargs):
            self.messages.append(message)

    class FakePaymentMessage:
        def __init__(self, message_id, channel):
            self.id = int(message_id)
            self.channel = channel
            self.jump_url = f"https://discord.com/channels/123/{channel.id}/{message_id}"
            self.edits = []

        async def edit(self, **kwargs):
            self.edits.append(kwargs)

    class FakePaymentChannel:
        def __init__(self, channel_id):
            self.id = int(channel_id)
            self.mention = f"<#{channel_id}>"
            self.sent = []
            self.messages = {}

        async def send(self, *args, **kwargs):
            self.sent.append((args, kwargs))
            message = FakePaymentMessage(9000 + len(self.sent), self)
            self.messages[message.id] = message
            return message

        async def fetch_message(self, message_id):
            return self.messages.setdefault(int(message_id), FakePaymentMessage(message_id, self))

    class FakePaymentGuild:
        def __init__(self, *channels):
            self._channels = {channel.id: channel for channel in channels}

        def get_channel(self, channel_id):
            return self._channels.get(int(channel_id))

        def get_member(self, _member_id):
            return None

    source = FakePaymentChannel(8101)
    dispatch = FakePaymentChannel(8102)
    dispatch.messages[8201] = FakePaymentMessage(8201, dispatch)
    guild = FakePaymentGuild(source, dispatch)

    monkeypatch.setattr(order_payment_runtime.discord, "TextChannel", FakePaymentChannel)
    monkeypatch.setattr(payment_reviews, "create_payment_review", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("0T must not create a payment review")))

    async def noop_async(*_args, **_kwargs):
        return None

    async def reward_zero(**_kwargs):
        return "顧客實付為 0T，本單不增加會員累積消費或點數。"

    async def receipt_zero(**_kwargs):
        assert _kwargs["amount"] == 0
        return "MO-ZERO", None

    async def redeem_zero(**_kwargs):
        return None

    orders = {}
    remembered = []
    for method in ("轉帳", "我的錢包"):
        channel_id = source.id
        orders[channel_id] = {
            "status": "accepted_pending_pay",
            "payment_method": method,
            "amount": 0,
            "total_amount": 0,
            "dispatch_message_id": 8201,
            "dispatch_channel_id": dispatch.id,
            "category": "delta_desktop_basic",
            "category_label": "三角洲 基礎單<端遊>",
            "item": "娛樂陪〈端遊〉｜單陪",
            "quantity": 1,
            "customer_id": 7001,
            "payout_base_amount": 320,
            "original_amount": 320,
        }

        monkeypatch.setattr(order_payment_runtime, "SELF_SERVICE_ORDER_SELECTIONS", orders, raising=False)
        monkeypatch.setattr(order_payment_runtime, "ORDER_CLAIMS", {}, raising=False)
        monkeypatch.setattr(order_payment_runtime, "ORDER_CATEGORY_LABELS", {"delta_desktop_basic": "三角洲 基礎單<端遊>"}, raising=False)
        monkeypatch.setattr(order_payment_runtime, "DISPATCH_CHANNEL_ID", dispatch.id, raising=False)
        monkeypatch.setattr(order_payment_runtime, "_to_int", lambda value, default=None: int(value) if value not in (None, "") else default, raising=False)
        monkeypatch.setattr(order_payment_runtime, "precheck_order_point_benefit_for_payment", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(order_payment_runtime, "redeem_order_point_benefit_on_payment", redeem_zero)
        monkeypatch.setattr(order_payment_runtime, "adjust_customer_wallet_balance", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("0T must not debit wallet")), raising=False)
        monkeypatch.setattr(order_payment_runtime, "add_customer_reward_from_order", reward_zero, raising=False)
        monkeypatch.setattr(order_payment_runtime, "ensure_payment_submit_receipt", receipt_zero, raising=False)
        monkeypatch.setattr(order_payment_runtime, "fetch_member_safely", noop_async, raising=False)
        monkeypatch.setattr(order_payment_runtime, "rename_ticket_channel", noop_async, raising=False)
        monkeypatch.setattr(order_payment_runtime, "send_order_log", noop_async, raising=False)
        monkeypatch.setattr(order_payment_runtime, "send_wallet_log", noop_async, raising=False)
        monkeypatch.setattr(order_payment_runtime, "remember_order_data", lambda *args: remembered.append(args), raising=False)
        monkeypatch.setattr(order_payment_runtime, "remember_claim_data", lambda *_args: None, raising=False)
        monkeypatch.setattr(order_payment_runtime, "save_bot_data", lambda: None, raising=False)
        monkeypatch.setattr(order_payment_runtime, "get_taipei_now_iso", lambda: "2026-10-14T19:00:00+08:00", raising=False)
        monkeypatch.setattr(order_payment_runtime, "format_t_amount", lambda amount: f"{amount:,}T", raising=False)
        monkeypatch.setattr(order_payment_runtime, "_build_receiver_text_from_claim_data", lambda _data: "陪玩A", raising=False)
        monkeypatch.setattr(order_payment_runtime, "build_self_service_order_embed", lambda **_kwargs: discord.Embed(title="zero"), raising=False)
        monkeypatch.setattr(order_payment_runtime, "add_self_service_financial_breakdown_fields", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(order_payment_runtime, "build_payment_method_embed", lambda **_kwargs: discord.Embed(title="payment"), raising=False)
        monkeypatch.setattr(order_payment_runtime, "DispatchClaimView", lambda **_kwargs: object(), raising=False)
        monkeypatch.setattr(order_payment_runtime, "PaymentMethodView", lambda **_kwargs: object(), raising=False)
        monkeypatch.setattr(order_payment_runtime, "StaffOrderOperationView", lambda: object(), raising=False)
        monkeypatch.setattr(order_payment_runtime, "_order_requires_credentials", lambda _data: False)

        # Keep the Golden test independent from the real acceptance DB.
        monkeypatch.setattr(
            order_acceptance,
            "find_acceptance_order_id_by_dispatch_message_id",
            lambda _message_id: None,
        )

        response = FakeResponse()
        followup = FakeFollowup()
        interaction = SimpleNamespace(
            guild=guild,
            channel=source,
            user=SimpleNamespace(id=6001, display_name="Golden CS"),
            response=response,
            followup=followup,
        )

        asyncio.run(
            order_payment_runtime.finalize_accepted_pending_payment(
                interaction=interaction,
                customer_id=7001,
                channel_id=channel_id,
            )
        )

        data = orders[channel_id]
        assert data["status"] == "active"
        assert data["payment_zero_amount"] is True
        assert data["payment_review_pending"] is False
        assert data["receipt_id"] == "MO-ZERO"
        assert "payment_finalizing" not in data
        assert "payment_processing" not in data
        assert any("訂單正式成立" in message for message in followup.messages)
'''
golden.write_text(golden_text, encoding="utf-8")

print("zero-amount checkout patch applied")
