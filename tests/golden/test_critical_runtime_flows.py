from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace

import discord

from services import order_lifecycle_runtime, order_payment_runtime, self_service_runtime
from services.payment_methods import WALLET_PAYMENT_METHOD
from shared import db as shared_db
from shared import order_acceptance
from shared import web_order_sync
from shared.order_state import WAITING_ACCEPTANCE
from services import order_rules


class _FakeMessage:
    def __init__(self, message_id: int, channel_id: int):
        self.id = int(message_id)
        self.jump_url = f"https://discord.com/channels/123/{channel_id}/{message_id}"
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)
        return self


class _FakeTextChannel:
    def __init__(self, channel_id: int):
        self.id = int(channel_id)
        self.mention = f"<#{channel_id}>"
        self.sent = []
        self.last_message = None

    async def send(self, **kwargs):
        self.sent.append(kwargs)
        self.last_message = _FakeMessage(7001, self.id)
        return self.last_message


class _FakeGuild:
    def __init__(self, source_channel, dispatch_channel):
        self.id = 123
        self._channels = {
            int(source_channel.id): source_channel,
            int(dispatch_channel.id): dispatch_channel,
        }

    def get_channel(self, channel_id):
        return self._channels.get(int(channel_id))

    def get_member(self, _member_id):
        return None

    async def fetch_member(self, _member_id):
        return None


class _FakeConnection:
    def execute(self, *_args, **_kwargs):
        return SimpleNamespace(rowcount=1)


class _FakeEngine:
    @contextmanager
    def begin(self):
        yield _FakeConnection()


def _price_adjustment() -> dict:
    return {
        "price_formula_version": 2,
        "manual_discount_mode": "pay_rate",
        "service_original_amount": 1000,
        "discount_rate_percent": 100,
        "percent_discount_amount": 0,
        "fixed_discount_amount": 0,
        "manual_discount_reason": None,
        "cash_coupon_reason": None,
        "specified_fee_before_waiver": 0,
        "effective_specify_fee": 0,
        "manual_staff_amount": None,
        "manual_staff_price_reason": None,
        "rule_original_amount": 1000,
        "original_amount": 1000,
        "manual_discount_percent": 100,
        "manual_discount_amount": 0,
        "payout_base_amount": 1000,
        "cash_coupon_amount": 0,
        "point_benefit_key": None,
        "point_benefit_name": None,
        "point_benefit_cost": 0,
        "point_discount_coupon_amount": 0,
        "point_waived_specify_fee": 0,
        "point_free_first_hour_amount": 0,
        "point_extra_hours": 0,
        "point_extra_games": 0,
        "benefit_coupon_id": None,
        "benefit_coupon_title": None,
        "benefit_service_value": None,
        "benefit_service_note": None,
        "store_absorbed_amount": 0,
        "customer_pay_amount": 1000,
        "service_bonus_text": None,
        "service_quantity": 1,
        "service_bonus_quantity": 0,
        "service_promotion_text": None,
        "manual_price_missing": False,
    }


def test_discord_self_service_submit_reaches_waiting_acceptance_and_is_idempotent(monkeypatch):
    """Run the real Discord submit runtime that previously failed only in production.

    This intentionally exercises the actual create_waiting_acceptance_order_from_self_service
    function instead of manufacturing a WebOrder directly. External Discord/storage seams are
    faked, while the runtime state boundary is still exercised by the real submit adapter.
    """

    source_channel = _FakeTextChannel(6001)
    dispatch_channel = _FakeTextChannel(6002)
    guild = _FakeGuild(source_channel, dispatch_channel)
    interaction = SimpleNamespace(
        guild=guild,
        channel=source_channel,
        user=SimpleNamespace(id=5001, display_name="Golden Customer"),
    )

    rule = SimpleNamespace(
        key="golden_discord_submit",
        category="delta",
        label="甜蜜單",
        min_protector_count=0,
        point_benefits_allowed=True,
        player_count_enabled=False,
    )
    selection = {
        "category": "delta",
        "item": "甜蜜單",
        "order_rule_key": rule.key,
        "quantity": 3,
        "player_count": 1,
        "specified_staff_ids": [],
        "companion_preference": "女單陪",
    }

    remembered_orders = []
    remembered_claims = []
    web_upserts = []
    acceptance_writes = []
    order_claims = {}

    monkeypatch.setattr(self_service_runtime.discord, "TextChannel", _FakeTextChannel)
    monkeypatch.setattr(self_service_runtime, "json", json, raising=False)
    monkeypatch.setattr(
        self_service_runtime,
        "_RUNTIME_STATE",
        self_service_runtime._SelfServiceRuntimeState(
            customer_category_id=0,
            customer_role_id=0,
            dispatch_channel_id=dispatch_channel.id,
            order_claims=order_claims,
            point_redeem_items=[],
            point_redeem_items_by_key={},
            order_selections={source_channel.id: selection},
            order_control_view_type=object,
        ),
    )
    monkeypatch.setattr(self_service_runtime, "ORDER_CATEGORY_LABELS", {"delta": "三角洲"}, raising=False)
    monkeypatch.setattr(
        self_service_runtime,
        "_to_int",
        lambda value, default=0: int(value) if value not in (None, "") else default,
        raising=False,
    )
    monkeypatch.setattr(self_service_runtime, "_get_rule_from_self_service_data", lambda _data: rule)
    monkeypatch.setattr(self_service_runtime, "normalize_self_service_staff_count", lambda _data: None, raising=False)

    async def _resolve_roles(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(self_service_runtime, "_resolve_specified_roles_for_price", _resolve_roles)
    monkeypatch.setattr(
        self_service_runtime,
        "apply_self_service_financials_to_order_data",
        lambda *_args, **_kwargs: _price_adjustment(),
    )
    monkeypatch.setattr(
        self_service_runtime,
        "build_self_service_order_embed",
        lambda **_kwargs: discord.Embed(title="Golden self-service submit"),
        raising=False,
    )
    monkeypatch.setattr(
        self_service_runtime,
        "add_self_service_financial_breakdown_fields",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        self_service_runtime,
        "prepare_initial_smart_dispatch",
        lambda *_args, **_kwargs: {
            "content": "golden dispatch",
            "ranked_candidate_ids": [],
            "initial_notified_ids": [],
        },
        raising=False,
    )
    monkeypatch.setattr(self_service_runtime, "DispatchClaimView", lambda **_kwargs: object(), raising=False)

    async def _noop_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr(self_service_runtime, "send_initial_smart_dispatch_alert", _noop_async, raising=False)
    monkeypatch.setattr(self_service_runtime, "create_smart_dispatch_plan", lambda **_kwargs: None, raising=False)
    monkeypatch.setattr(self_service_runtime, "get_taipei_now_iso", lambda: "2026-10-13T18:00:00+08:00", raising=False)
    monkeypatch.setattr(self_service_runtime, "get_self_service_quantity_unit", lambda *_args, **_kwargs: "小時", raising=False)
    monkeypatch.setattr(self_service_runtime, "remember_order_data", lambda *args: remembered_orders.append(args), raising=False)
    monkeypatch.setattr(self_service_runtime, "remember_claim_data", lambda *args: remembered_claims.append(args), raising=False)
    monkeypatch.setattr(self_service_runtime, "save_bot_data", lambda: None, raising=False)
    monkeypatch.setattr(self_service_runtime, "send_order_log", _noop_async, raising=False)
    monkeypatch.setattr(self_service_runtime, "log_self_service_proxy_action", _noop_async, raising=False)
    monkeypatch.setattr(self_service_runtime, "is_customer_staff", lambda _member: False, raising=False)

    monkeypatch.setattr(order_rules, "calculate_price", lambda *_args, **_kwargs: SimpleNamespace(required_staff_count=1))
    monkeypatch.setattr(order_rules, "get_allowed_role_ids", lambda _rule: [])
    monkeypatch.setattr(order_rules, "get_required_game_role_ids", lambda _rule: [])
    monkeypatch.setattr(order_rules, "get_required_staff_count", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(order_rules, "build_order_rule_snapshot", lambda *_args, **_kwargs: {"version": 1})
    monkeypatch.setattr(order_rules, "rule_role_labels", lambda _rule: "女陪")

    def _fake_web_upsert(**kwargs):
        web_upserts.append(kwargs)
        return SimpleNamespace(id=321)

    monkeypatch.setattr(web_order_sync, "upsert_web_order_from_dispatch", _fake_web_upsert)
    monkeypatch.setattr(
        order_acceptance,
        "create_or_update_acceptance_meta",
        lambda **kwargs: acceptance_writes.append(kwargs),
    )
    monkeypatch.setattr(shared_db, "engine", _FakeEngine())

    first = asyncio.run(
        self_service_runtime.create_waiting_acceptance_order_from_self_service(
            interaction,
            customer_id=5001,
            channel_id=source_channel.id,
        )
    )

    assert first == "已送出等待接單：https://discord.com/channels/123/6002/7001"
    assert len(dispatch_channel.sent) == 1
    assert dispatch_channel.sent[0]["view"] is None
    assert dispatch_channel.last_message is not None
    assert len(dispatch_channel.last_message.edits) == 1
    assert dispatch_channel.last_message.edits[0]["view"] is not None
    assert len(web_upserts) == 1
    assert web_upserts[0]["status"] == WAITING_ACCEPTANCE
    assert len(acceptance_writes) == 1
    assert acceptance_writes[0]["order_id"] == 321
    assert acceptance_writes[0]["status"] == WAITING_ACCEPTANCE
    assert selection["dispatch_message_id"] == 7001
    assert selection["dispatch_channel_id"] == 6002
    assert selection["web_order_id"] == 321
    assert selection["status"] == WAITING_ACCEPTANCE
    assert order_claims[7001]["status"] == WAITING_ACCEPTANCE
    assert remembered_orders
    assert remembered_claims

    second = asyncio.run(
        self_service_runtime.create_waiting_acceptance_order_from_self_service(
            interaction,
            customer_id=5001,
            channel_id=source_channel.id,
        )
    )

    assert "這張單已經送出等待接單" in second
    assert "https://discord.com/channels/123/6002/7001" in second
    assert len(dispatch_channel.sent) == 1
    assert len(web_upserts) == 1
    assert len(acceptance_writes) == 1


def test_wallet_receipt_runtime_has_canonical_payment_method_in_defining_scope():
    """Keep the live wallet-receipt NameError inside the Golden Flow gate."""

    assert WALLET_PAYMENT_METHOD == "我的錢包"
    assert order_lifecycle_runtime.WALLET_PAYMENT_METHOD == WALLET_PAYMENT_METHOD
    assert (
        order_lifecycle_runtime.ensure_payment_submit_receipt.__globals__["WALLET_PAYMENT_METHOD"]
        == WALLET_PAYMENT_METHOD
    )



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
    promoted_order_ids = []
    for method in ("轉帳", "我的錢包"):
        channel_id = source.id
        orders[channel_id] = {
            "status": "accepted_pending_pay",
            "payment_method": method,
            "amount": 0,
            "total_amount": 0,
            "dispatch_message_id": 8201,
            "dispatch_channel_id": dispatch.id,
            "web_order_id": 321,
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

        # Keep the Golden test independent from the real acceptance DB while
        # preserving the production invariant that every finalized payment has
        # a canonical WebOrder and runs assignment/payout promotion.
        monkeypatch.setattr(
            order_acceptance,
            "find_acceptance_order_id_by_dispatch_message_id",
            lambda _message_id: 321,
        )
        monkeypatch.setattr(
            order_acceptance,
            "promote_acceptance_claims_to_assignments",
            lambda **kwargs: promoted_order_ids.append(int(kwargs["order_id"])) or 1,
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
        assert data["promoted_assignment_count"] == 1
        assert "payment_finalizing" not in data
        assert "payment_processing" not in data
        assert any("訂單正式成立" in message for message in followup.messages)

    assert promoted_order_ids == [321, 321]
