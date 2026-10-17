from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def remove_between(path: str, start: str, end: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    start_index = text.find(start)
    end_index = text.find(end, start_index)
    if start_index < 0 or end_index < 0:
        raise RuntimeError(f"{path}: remove markers not found")
    target.write_text(text[:start_index] + text[end_index:], encoding="utf-8")


(ROOT / "services/wallet_discord_runtime.py").write_text(
    '''from __future__ import annotations

import discord

from services.logging_service import send_order_log
from services.rewards import format_t_amount
from services.wallet_service import adjust_wallet_balance


def adjust_customer_wallet_balance(
    *,
    customer_id,
    amount: int,
    tx_type: str,
    operator=None,
    order_channel_id=None,
    order_no=None,
    note: str | None = None,
    allow_negative: bool = False,
) -> dict:
    """Discord-facing adapter around the canonical wallet transaction service."""
    operator_id = getattr(operator, "id", None)
    operator_name = (
        getattr(operator, "display_name", None)
        or getattr(operator, "name", None)
        or (str(operator_id) if operator_id is not None else None)
    )
    normalized_type = str(tx_type or "adjustment").strip() or "adjustment"
    return adjust_wallet_balance(
        customer_id=customer_id,
        amount=amount,
        tx_type=normalized_type,
        operator_discord_id=operator_id,
        operator_display_name=operator_name,
        order_channel_id=order_channel_id,
        order_no=order_no,
        note=note,
        allow_negative=allow_negative,
    )


async def send_wallet_log(
    guild: discord.Guild | None,
    *,
    title: str,
    customer: discord.Member,
    operator: discord.Member | discord.User,
    tx: dict,
) -> None:
    try:
        await send_order_log(
            guild,
            title=title,
            fields=[
                ("顧客", customer.mention, True),
                ("操作人員", getattr(operator, "mention", str(getattr(operator, "id", "未知"))), True),
                ("異動金額", format_t_amount(int(tx["amount"])), True),
                ("原餘額", format_t_amount(int(tx["balance_before"])), True),
                ("新餘額", format_t_amount(int(tx["balance_after"])), True),
                ("備註", str(tx.get("note") or "未填寫"), False),
            ],
            color=discord.Color.gold(),
        )
    except Exception as exc:
        print(f"錢包日誌送出失敗：{exc}")
''',
    encoding="utf-8",
)

(ROOT / "services/order_payment_composition.py").write_text(
    '''from __future__ import annotations

from core.database import remember_claim_data, remember_order_data, save_bot_data
from core.time_utils import get_taipei_now_iso
from services.acceptance.runtime import _build_receiver_text_from_claim_data
from services.logging_service import send_order_log
from services.order_dispatch_runtime import DispatchClaimView
from services.order_flow import build_payment_method_embed
from services.order_lifecycle_runtime import ensure_payment_submit_receipt
from services.order_payment_runtime import configure_order_payment_runtime
from services.orders import ORDER_CATEGORY_LABELS, _to_int, build_self_service_order_embed
from services.rewards import add_customer_reward_from_order, fetch_member_safely, format_t_amount
from services.ticket_identity import rename_ticket_channel
from services.wallet_discord_runtime import adjust_customer_wallet_balance, send_wallet_log


def configure_order_payment_composition(
    dispatch_channel_id,
    order_claims,
    order_selections,
    staff_order_operation_view,
) -> None:
    """Wire payment runtime using bot-owned state only."""
    # PaymentMethodView still lives in the transitional order UI module. Import it
    # lazily so composition does not create an import cycle during module startup.
    from services.order_runtime import PaymentMethodView

    configure_order_payment_runtime(
        dispatch_channel_id=dispatch_channel_id,
        dispatch_claim_view=DispatchClaimView,
        order_category_labels=ORDER_CATEGORY_LABELS,
        order_claims=order_claims,
        payment_method_view=PaymentMethodView,
        self_service_order_selections=order_selections,
        staff_order_operation_view=staff_order_operation_view,
        receiver_text_builder=_build_receiver_text_from_claim_data,
        to_int=_to_int,
        customer_reward_adder=add_customer_reward_from_order,
        wallet_adjuster=adjust_customer_wallet_balance,
        payment_method_embed_builder=build_payment_method_embed,
        self_service_order_embed_builder=build_self_service_order_embed,
        payment_receipt_ensurer=ensure_payment_submit_receipt,
        fetch_member=fetch_member_safely,
        amount_formatter=format_t_amount,
        taipei_now_iso=get_taipei_now_iso,
        remember_claim=remember_claim_data,
        remember_order=remember_order_data,
        ticket_channel_renamer=rename_ticket_channel,
        save_data=save_bot_data,
        order_log_sender=send_order_log,
        wallet_log_sender=send_wallet_log,
    )
''',
    encoding="utf-8",
)

replace_once(
    "services/order_child_composition.py",
    "from services.order_dispatch_composition import configure_order_dispatch_composition\n",
    "from services.order_dispatch_composition import configure_order_dispatch_composition\nfrom services.order_payment_composition import configure_order_payment_composition\n",
)
replace_once(
    "services/order_child_composition.py",
    '''    guild_id,\n    bot_instance,\n) -> None:\n''',
    '''    guild_id,\n    bot_instance,\n    staff_order_operation_view,\n) -> None:\n''',
)
replace_once(
    "services/order_child_composition.py",
    '''    configure_order_credential_composition(\n        credential_owner_user_id,\n        guild_id,\n        order_selections,\n        bot_instance,\n    )\n''',
    '''    configure_order_credential_composition(\n        credential_owner_user_id,\n        guild_id,\n        order_selections,\n        bot_instance,\n    )\n    configure_order_payment_composition(\n        dispatch_channel_id,\n        order_claims,\n        order_selections,\n        staff_order_operation_view,\n    )\n''',
)

replace_once(
    "services/order_runtime.py",
    '''from services.order_payment_runtime import (\n    configure_order_payment_runtime,\n    finalize_accepted_pending_payment,\n)\n''',
    "from services.order_payment_runtime import finalize_accepted_pending_payment\n",
)
remove_between(
    "services/order_runtime.py",
    "    payment_keys = {\n",
    "    storage_keys = {\n",
)

replace_once(
    "bot.py",
    '''from services.wallet_service import (\n    ensure_wallet_tables as _wallet_ensure_tables,\n    get_wallet_balance as _wallet_get_balance,\n    adjust_wallet_balance as _wallet_adjust_balance,\n    get_wallet_transactions as _wallet_get_transactions,\n)\n''',
    '''from services.wallet_service import (\n    ensure_wallet_tables as _wallet_ensure_tables,\n    get_wallet_balance as _wallet_get_balance,\n    get_wallet_transactions as _wallet_get_transactions,\n)\nfrom services.wallet_discord_runtime import (\n    adjust_customer_wallet_balance,\n    send_wallet_log,\n)\n''',
)
replace_once(
    "bot.py",
    '''def adjust_customer_wallet_balance(\n    *,\n    customer_id,\n    amount: int,\n    tx_type: str,\n    operator=None,\n    order_channel_id=None,\n    order_no=None,\n    note: str | None = None,\n    allow_negative: bool = False,\n) -> dict:\n    """Discord-facing adapter around the canonical wallet transaction service."""\n    operator_id = getattr(operator, "id", None)\n    operator_name = (\n        getattr(operator, "display_name", None)\n        or getattr(operator, "name", None)\n        or (str(operator_id) if operator_id is not None else None)\n    )\n    normalized_type = str(tx_type or "adjustment").strip() or "adjustment"\n    return _wallet_adjust_balance(\n        customer_id=customer_id,\n        amount=amount,\n        tx_type=normalized_type,\n        operator_discord_id=operator_id,\n        operator_display_name=operator_name,\n        order_channel_id=order_channel_id,\n        order_no=order_no,\n        note=note,\n        allow_negative=allow_negative,\n        db_file=DB_FILE,\n    )\n\n\n''',
    "",
)
replace_once(
    "bot.py",
    '''async def send_wallet_log(\n    guild: discord.Guild | None,\n    *,\n    title: str,\n    customer: discord.Member,\n    operator: discord.Member | discord.User,\n    tx: dict,\n) -> None:\n    try:\n        await send_order_log(\n            guild,\n            title=title,\n            fields=[\n                ("顧客", customer.mention, True),\n                ("操作人員", getattr(operator, "mention", str(getattr(operator, "id", "未知"))), True),\n                ("異動金額", format_t_amount(int(tx["amount"])), True),\n                ("原餘額", format_t_amount(int(tx["balance_before"])), True),\n                ("新餘額", format_t_amount(int(tx["balance_after"])), True),\n                ("備註", str(tx.get("note") or "未填寫"), False),\n            ],\n            color=discord.Color.gold(),\n        )\n    except Exception as exc:\n        print(f"錢包日誌送出失敗：{exc}")\n\n\n''',
    "",
)
replace_once(
    "bot.py",
    "configure_order_children(BOOSTER_RECEIVER_ROLE_ID, DISPATCH_CHANNEL_ID, ORDER_CLAIMS, SELF_SERVICE_ORDER_SELECTIONS, CUSTOMER_REWARDS, CREDENTIAL_OWNER_USER_ID, GUILD_ID, bot)\n",
    "configure_order_children(BOOSTER_RECEIVER_ROLE_ID, DISPATCH_CHANNEL_ID, ORDER_CLAIMS, SELF_SERVICE_ORDER_SELECTIONS, CUSTOMER_REWARDS, CREDENTIAL_OWNER_USER_ID, GUILD_ID, bot, StaffOrderOperationView)\n",
)

replace_once(
    "tests/test_order_child_composition.py",
    "    point_kwargs = {}\n",
    "    point_kwargs = {}\n    payment_calls = []\n",
)
replace_once(
    "tests/test_order_child_composition.py",
    '''    monkeypatch.setattr(\n        composition,\n        "configure_order_credential_composition",\n        lambda *args: credential_calls.append(args),\n    )\n''',
    '''    monkeypatch.setattr(\n        composition,\n        "configure_order_credential_composition",\n        lambda *args: credential_calls.append(args),\n    )\n    monkeypatch.setattr(\n        composition,\n        "configure_order_payment_composition",\n        lambda *args: payment_calls.append(args),\n    )\n''',
)
replace_once(
    "tests/test_order_child_composition.py",
    '''    bot_instance = object()\n    composition.configure_order_children(\n        11, 22, claims, selections, rewards, 33, 44, bot_instance\n    )\n\n    assert dispatch_calls == [(11, 22, claims, selections)]\n    assert point_kwargs == {"customer_rewards": rewards, **sentinels}\n    assert credential_calls == [(33, 44, selections, bot_instance)]\n''',
    '''    bot_instance = object()\n    staff_view = object()\n    composition.configure_order_children(\n        11, 22, claims, selections, rewards, 33, 44, bot_instance, staff_view\n    )\n\n    assert dispatch_calls == [(11, 22, claims, selections)]\n    assert point_kwargs == {"customer_rewards": rewards, **sentinels}\n    assert credential_calls == [(33, 44, selections, bot_instance)]\n    assert payment_calls == [(22, claims, selections, staff_view)]\n''',
)
replace_once(
    "tests/test_order_child_composition.py",
    '''    assert "configure_order_credentials(" not in ORDER_RUNTIME_SOURCE\n    assert "credential_keys =" not in ORDER_RUNTIME_SOURCE\n    assert "configure_order_children" in BOT_SOURCE\n''',
    '''    assert "configure_order_credentials(" not in ORDER_RUNTIME_SOURCE\n    assert "credential_keys =" not in ORDER_RUNTIME_SOURCE\n    assert "configure_order_payment_runtime(" not in ORDER_RUNTIME_SOURCE\n    assert "payment_keys =" not in ORDER_RUNTIME_SOURCE\n    assert "configure_order_children" in BOT_SOURCE\n''',
)

(ROOT / "tests/test_order_payment_composition.py").write_text(
    '''from services import order_payment_composition as composition


def test_order_payment_composition_binds_service_owned_dependencies(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        composition,
        "configure_order_payment_runtime",
        lambda **kwargs: captured.update(kwargs),
    )

    claims = {}
    selections = {}
    staff_view = object()
    composition.configure_order_payment_composition(123, claims, selections, staff_view)

    from services.order_runtime import PaymentMethodView

    assert captured["dispatch_channel_id"] == 123
    assert captured["order_claims"] is claims
    assert captured["self_service_order_selections"] is selections
    assert captured["staff_order_operation_view"] is staff_view
    assert captured["payment_method_view"] is PaymentMethodView
    assert captured["dispatch_claim_view"] is composition.DispatchClaimView
    assert captured["wallet_adjuster"] is composition.adjust_customer_wallet_balance
    assert captured["wallet_log_sender"] is composition.send_wallet_log
    assert captured["receiver_text_builder"] is composition._build_receiver_text_from_claim_data
    assert captured["payment_receipt_ensurer"] is composition.ensure_payment_submit_receipt
''',
    encoding="utf-8",
)

(ROOT / "tests/test_wallet_discord_runtime.py").write_text(
    '''import asyncio
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
''',
    encoding="utf-8",
)

replace_once(
    "tests/test_wallet_service_canonicalization.py",
    '''    service_source = Path("services/wallet_service.py").read_text(encoding="utf-8")\n\n''',
    '''    service_source = Path("services/wallet_service.py").read_text(encoding="utf-8")\n    discord_runtime_source = Path("services/wallet_discord_runtime.py").read_text(encoding="utf-8")\n\n''',
)
replace_once(
    "tests/test_wallet_service_canonicalization.py",
    '''    assert "_wallet_adjust_balance(" in bot_source\n    assert "_wallet_get_transactions(" in bot_source\n\n''',
    '''    assert "_wallet_adjust_balance(" not in bot_source\n    assert "from services.wallet_discord_runtime import (" in bot_source\n    assert "_wallet_get_transactions(" in bot_source\n    assert "def adjust_customer_wallet_balance(" in discord_runtime_source\n    assert "adjust_wallet_balance(" in discord_runtime_source\n\n''',
)

replace_once(
    "tests/test_runtime_extraction_boundaries.py",
    '''    order_dispatch_composition,\n    order_payment_runtime,\n''',
    '''    order_dispatch_composition,\n    order_payment_composition,\n    order_payment_runtime,\n''',
)
replace_once(
    "tests/test_runtime_extraction_boundaries.py",
    '''    assert callable(order_dispatch_composition.configure_order_dispatch_composition)\n    assert callable(order_storage_runtime.configure_order_storage_runtime)\n''',
    '''    assert callable(order_dispatch_composition.configure_order_dispatch_composition)\n    assert callable(order_payment_composition.configure_order_payment_composition)\n    assert callable(order_storage_runtime.configure_order_storage_runtime)\n''',
)
replace_once(
    "tests/test_runtime_extraction_boundaries.py",
    '''    assert "def configure_order_payment_runtime" in payment_source\n    assert "import bot" not in payment_source\n''',
    '''    assert "def configure_order_payment_runtime" in payment_source\n    assert "configure_order_payment_runtime(" not in order_source\n    assert "payment_keys =" not in order_source\n    assert "import bot" not in payment_source\n''',
)

print("bounded payment composition patch applied")
