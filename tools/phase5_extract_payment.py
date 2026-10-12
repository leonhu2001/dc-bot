from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "services/order_runtime.py"
CHILD = ROOT / "services/order_payment_runtime.py"
TARGET = "finalize_accepted_pending_payment"

source = PARENT.read_text(encoding="utf-8")
tree = ast.parse(source)
lines = source.splitlines(keepends=True)
node = next(
    item for item in tree.body
    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == TARGET
)
implementation = "".join(lines[node.lineno - 1 : node.end_lineno]).rstrip() + "\n"

header = '''from __future__ import annotations

from typing import Callable

import discord

from services.order_credential_runtime import (
    _order_requires_credentials,
    ensure_order_credential_request,
)
from services.order_point_redemption import (
    precheck_order_point_benefit_for_payment,
    redeem_order_point_benefit_on_payment,
)
from services.self_service_financials import (
    _format_plain_amount,
    add_self_service_financial_breakdown_fields,
)


_CONFIGURED = False


def configure_order_payment_runtime(
    *,
    dispatch_channel_id: int,
    dispatch_claim_view,
    order_category_labels: dict,
    order_claims: dict,
    payment_method_view,
    self_service_order_selections: dict,
    staff_order_operation_view,
    wallet_payment_method: str,
    receiver_text_builder: Callable,
    to_int: Callable,
    customer_reward_adder: Callable,
    wallet_adjuster: Callable,
    payment_method_embed_builder: Callable,
    self_service_order_embed_builder: Callable,
    payment_receipt_ensurer: Callable,
    fetch_member: Callable,
    amount_formatter: Callable,
    taipei_now_iso: Callable,
    remember_claim: Callable,
    remember_order: Callable,
    ticket_channel_renamer: Callable,
    save_data: Callable,
    order_log_sender: Callable,
    wallet_log_sender: Callable,
) -> None:
    """Bind explicit bot/runtime APIs used by payment finalization."""
    global _CONFIGURED
    global DISPATCH_CHANNEL_ID, DispatchClaimView, ORDER_CATEGORY_LABELS, ORDER_CLAIMS
    global PaymentMethodView, SELF_SERVICE_ORDER_SELECTIONS, StaffOrderOperationView
    global WALLET_PAYMENT_METHOD, _build_receiver_text_from_claim_data, _to_int
    global add_customer_reward_from_order, adjust_customer_wallet_balance
    global build_payment_method_embed, build_self_service_order_embed
    global ensure_payment_submit_receipt, fetch_member_safely, format_t_amount
    global get_taipei_now_iso, remember_claim_data, remember_order_data
    global rename_ticket_channel, save_bot_data, send_order_log, send_wallet_log

    DISPATCH_CHANNEL_ID = int(dispatch_channel_id)
    DispatchClaimView = dispatch_claim_view
    ORDER_CATEGORY_LABELS = order_category_labels
    ORDER_CLAIMS = order_claims
    PaymentMethodView = payment_method_view
    SELF_SERVICE_ORDER_SELECTIONS = self_service_order_selections
    StaffOrderOperationView = staff_order_operation_view
    WALLET_PAYMENT_METHOD = str(wallet_payment_method)
    _build_receiver_text_from_claim_data = receiver_text_builder
    _to_int = to_int
    add_customer_reward_from_order = customer_reward_adder
    adjust_customer_wallet_balance = wallet_adjuster
    build_payment_method_embed = payment_method_embed_builder
    build_self_service_order_embed = self_service_order_embed_builder
    ensure_payment_submit_receipt = payment_receipt_ensurer
    fetch_member_safely = fetch_member
    format_t_amount = amount_formatter
    get_taipei_now_iso = taipei_now_iso
    remember_claim_data = remember_claim
    remember_order_data = remember_order
    rename_ticket_channel = ticket_channel_renamer
    save_bot_data = save_data
    send_order_log = order_log_sender
    send_wallet_log = wallet_log_sender
    _CONFIGURED = True


'''
CHILD.write_text(header + implementation, encoding="utf-8")

# Remove implementation from the parent and re-export it from the child.
del lines[node.lineno - 1 : node.end_lineno]
parent = "".join(lines)
child_import = '''from services.order_payment_runtime import (
    configure_order_payment_runtime,
    finalize_accepted_pending_payment,
)
'''
anchor = '''from services.order_point_redemption import (
    configure_order_point_redemption,
    _get_pending_order_point_benefit_info,
    precheck_order_point_benefit_for_payment,
    redeem_order_point_benefit_on_payment,
)
'''
if anchor not in parent:
    raise RuntimeError("order point import anchor not found")
parent = parent.replace(anchor, anchor + child_import, 1)

# Bind the child only when the full production dependency set exists, preserving
# the existing partial-namespace test contract.
end_anchor = "\n    _CONFIGURED = True\n"
position = parent.find(end_anchor)
if position < 0:
    raise RuntimeError("configure completion marker not found")
payment_binding = '''
    payment_keys = {
        "DISPATCH_CHANNEL_ID",
        "ORDER_CATEGORY_LABELS",
        "ORDER_CLAIMS",
        "SELF_SERVICE_ORDER_SELECTIONS",
        "StaffOrderOperationView",
        "WALLET_PAYMENT_METHOD",
        "_build_receiver_text_from_claim_data",
        "_to_int",
        "add_customer_reward_from_order",
        "adjust_customer_wallet_balance",
        "build_payment_method_embed",
        "build_self_service_order_embed",
        "ensure_payment_submit_receipt",
        "fetch_member_safely",
        "format_t_amount",
        "get_taipei_now_iso",
        "remember_claim_data",
        "remember_order_data",
        "rename_ticket_channel",
        "save_bot_data",
        "send_order_log",
        "send_wallet_log",
    }
    if payment_keys.issubset(namespace):
        configure_order_payment_runtime(
            dispatch_channel_id=namespace["DISPATCH_CHANNEL_ID"],
            dispatch_claim_view=DispatchClaimView,
            order_category_labels=namespace["ORDER_CATEGORY_LABELS"],
            order_claims=namespace["ORDER_CLAIMS"],
            payment_method_view=PaymentMethodView,
            self_service_order_selections=namespace["SELF_SERVICE_ORDER_SELECTIONS"],
            staff_order_operation_view=namespace["StaffOrderOperationView"],
            wallet_payment_method=namespace["WALLET_PAYMENT_METHOD"],
            receiver_text_builder=namespace["_build_receiver_text_from_claim_data"],
            to_int=namespace["_to_int"],
            customer_reward_adder=namespace["add_customer_reward_from_order"],
            wallet_adjuster=namespace["adjust_customer_wallet_balance"],
            payment_method_embed_builder=namespace["build_payment_method_embed"],
            self_service_order_embed_builder=namespace["build_self_service_order_embed"],
            payment_receipt_ensurer=namespace["ensure_payment_submit_receipt"],
            fetch_member=namespace["fetch_member_safely"],
            amount_formatter=namespace["format_t_amount"],
            taipei_now_iso=namespace["get_taipei_now_iso"],
            remember_claim=namespace["remember_claim_data"],
            remember_order=namespace["remember_order_data"],
            ticket_channel_renamer=namespace["rename_ticket_channel"],
            save_data=namespace["save_bot_data"],
            order_log_sender=namespace["send_order_log"],
            wallet_log_sender=namespace["send_wallet_log"],
        )
'''
parent = parent[:position] + payment_binding + parent[position:]
PARENT.write_text(parent, encoding="utf-8")

# Boundary tests: implementation lives in the payment child, remains re-exported
# from the parent, and the child must never depend on bot.py.
test_path = ROOT / "tests/test_runtime_extraction_boundaries.py"
test = test_path.read_text(encoding="utf-8")
test = test.replace(
    "    order_point_redemption,\n    order_runtime,\n",
    "    order_payment_runtime,\n    order_point_redemption,\n    order_runtime,\n",
    1,
)
test = test.replace(
    "    assert callable(order_point_redemption.configure_order_point_redemption)\n",
    "    assert callable(order_point_redemption.configure_order_point_redemption)\n    assert callable(order_payment_runtime.configure_order_payment_runtime)\n",
    1,
)
old = '''    assert "async def finalize_accepted_pending_payment" in order_source
    assert "class DispatchClaimView" in order_source
'''
new = '''    payment_source = Path("services/order_payment_runtime.py").read_text(
        encoding="utf-8"
    )

    assert "async def finalize_accepted_pending_payment" not in order_source
    assert callable(order_runtime.finalize_accepted_pending_payment)
    assert "async def finalize_accepted_pending_payment" in payment_source
    assert "def configure_order_payment_runtime" in payment_source
    assert "import bot" not in payment_source
    assert "from bot import" not in payment_source
    assert "class DispatchClaimView" in order_source
'''
if old not in test:
    raise RuntimeError("order extraction test anchor not found")
test_path.write_text(test.replace(old, new, 1), encoding="utf-8")

budget_path = ROOT / "tests/test_architecture_growth_budget.py"
budget = budget_path.read_text(encoding="utf-8")
parent_size = PARENT.stat().st_size
child_size = CHILD.stat().st_size
round_up = lambda size: ((size + 1999) // 1000) * 1000
parent_limit = round_up(parent_size)
child_limit = round_up(child_size)
budget = budget.replace(
    '    "services/order_runtime.py": 108_000,\n',
    f'    "services/order_runtime.py": {parent_limit:_},\n'
    f'    "services/order_payment_runtime.py": {child_limit:_},\n',
    1,
)
budget_path.write_text(budget, encoding="utf-8")

print(f"parent bytes: {parent_size}; ceiling: {parent_limit}")
print(f"payment runtime bytes: {child_size}; ceiling: {child_limit}")
