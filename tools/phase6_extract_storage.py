from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "services/order_runtime.py"
CHILD = ROOT / "services/order_storage_runtime.py"
TARGETS = [
    "lock_dispatch_claim_panel",
    "store_dispatch_claim_panel",
    "resume_stored_order",
]

source = PARENT.read_text(encoding="utf-8")
tree = ast.parse(source)
lines = source.splitlines(keepends=True)
nodes = {
    item.name: item
    for item in tree.body
    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in TARGETS
}
missing = set(TARGETS) - nodes.keys()
if missing:
    raise RuntimeError(f"missing stored-order definitions: {sorted(missing)}")

implementations = []
for name in TARGETS:
    node = nodes[name]
    implementations.append("".join(lines[node.lineno - 1 : node.end_lineno]).rstrip() + "\n")

header = '''from __future__ import annotations

from typing import Callable

import discord

from services.order_credential_runtime import (
    _order_requires_credentials,
    ensure_order_credential_request,
    revoke_order_credential_messages,
)
from services.smart_dispatch import create_smart_dispatch_plan
from services.ticket_identity import get_order_customer_id_from_channel


_CONFIGURED = False


def configure_order_storage_runtime(
    *,
    dispatch_channel_id: int,
    dispatch_claim_view,
    order_category_labels: dict,
    order_claims: dict,
    self_service_order_selections: dict,
    to_int: Callable,
    self_service_order_embed_builder: Callable,
    taipei_now_iso: Callable,
    remember_claim: Callable,
    remember_order: Callable,
    save_data: Callable,
    acceptance_state_applier: Callable,
    self_service_rule_getter: Callable,
    claim_row_deleter: Callable,
    initial_dispatch_preparer: Callable,
    initial_dispatch_alert_sender: Callable,
    specified_staff_dm_sender: Callable,
    specified_dm_result_setter: Callable,
    web_order_status_syncer: Callable,
) -> None:
    """Bind explicit runtime collaborators for store/lock/resume flows."""
    global _CONFIGURED
    global DISPATCH_CHANNEL_ID, DispatchClaimView, ORDER_CATEGORY_LABELS, ORDER_CLAIMS
    global SELF_SERVICE_ORDER_SELECTIONS, _to_int, build_self_service_order_embed
    global get_taipei_now_iso, remember_claim_data, remember_order_data, save_bot_data
    global _apply_acceptance_state_to_claim_data, _get_rule_from_self_service_data
    global delete_claim_row_from_db, prepare_initial_smart_dispatch
    global send_initial_smart_dispatch_alert, send_specified_staff_dispatch_dms
    global set_specified_dm_results, sync_web_order_status_from_bot

    DISPATCH_CHANNEL_ID = int(dispatch_channel_id)
    DispatchClaimView = dispatch_claim_view
    ORDER_CATEGORY_LABELS = order_category_labels
    ORDER_CLAIMS = order_claims
    SELF_SERVICE_ORDER_SELECTIONS = self_service_order_selections
    _to_int = to_int
    build_self_service_order_embed = self_service_order_embed_builder
    get_taipei_now_iso = taipei_now_iso
    remember_claim_data = remember_claim
    remember_order_data = remember_order
    save_bot_data = save_data
    _apply_acceptance_state_to_claim_data = acceptance_state_applier
    _get_rule_from_self_service_data = self_service_rule_getter
    delete_claim_row_from_db = claim_row_deleter
    prepare_initial_smart_dispatch = initial_dispatch_preparer
    send_initial_smart_dispatch_alert = initial_dispatch_alert_sender
    send_specified_staff_dispatch_dms = specified_staff_dm_sender
    set_specified_dm_results = specified_dm_result_setter
    sync_web_order_status_from_bot = web_order_status_syncer
    _CONFIGURED = True


'''
CHILD.write_text(header + "\n\n".join(implementations), encoding="utf-8")

for node in sorted(nodes.values(), key=lambda item: item.lineno, reverse=True):
    del lines[node.lineno - 1 : node.end_lineno]
parent = "".join(lines)

child_import = '''from services.order_storage_runtime import (
    configure_order_storage_runtime,
    lock_dispatch_claim_panel,
    store_dispatch_claim_panel,
    resume_stored_order,
)
'''
anchor = '''from services.order_payment_runtime import (
    configure_order_payment_runtime,
    finalize_accepted_pending_payment,
)
'''
if anchor not in parent:
    raise RuntimeError("order payment import anchor not found")
parent = parent.replace(anchor, anchor + child_import, 1)

end_anchor = "\n    _CONFIGURED = True\n"
position = parent.find(end_anchor)
if position < 0:
    raise RuntimeError("configure completion marker not found")
storage_binding = '''
    storage_keys = {
        "DISPATCH_CHANNEL_ID",
        "ORDER_CATEGORY_LABELS",
        "ORDER_CLAIMS",
        "SELF_SERVICE_ORDER_SELECTIONS",
        "_apply_acceptance_state_to_claim_data",
        "_get_rule_from_self_service_data",
        "_to_int",
        "build_self_service_order_embed",
        "delete_claim_row_from_db",
        "get_taipei_now_iso",
        "prepare_initial_smart_dispatch",
        "remember_claim_data",
        "remember_order_data",
        "save_bot_data",
        "send_initial_smart_dispatch_alert",
        "send_specified_staff_dispatch_dms",
        "set_specified_dm_results",
    }
    if storage_keys.issubset(namespace):
        configure_order_storage_runtime(
            dispatch_channel_id=namespace["DISPATCH_CHANNEL_ID"],
            dispatch_claim_view=DispatchClaimView,
            order_category_labels=namespace["ORDER_CATEGORY_LABELS"],
            order_claims=namespace["ORDER_CLAIMS"],
            self_service_order_selections=namespace["SELF_SERVICE_ORDER_SELECTIONS"],
            to_int=namespace["_to_int"],
            self_service_order_embed_builder=namespace["build_self_service_order_embed"],
            taipei_now_iso=namespace["get_taipei_now_iso"],
            remember_claim=namespace["remember_claim_data"],
            remember_order=namespace["remember_order_data"],
            save_data=namespace["save_bot_data"],
            acceptance_state_applier=namespace["_apply_acceptance_state_to_claim_data"],
            self_service_rule_getter=namespace["_get_rule_from_self_service_data"],
            claim_row_deleter=namespace["delete_claim_row_from_db"],
            initial_dispatch_preparer=namespace["prepare_initial_smart_dispatch"],
            initial_dispatch_alert_sender=namespace["send_initial_smart_dispatch_alert"],
            specified_staff_dm_sender=namespace["send_specified_staff_dispatch_dms"],
            specified_dm_result_setter=namespace["set_specified_dm_results"],
            web_order_status_syncer=sync_web_order_status_from_bot,
        )
'''
parent = parent[:position] + storage_binding + parent[position:]
PARENT.write_text(parent, encoding="utf-8")

# Lock the physical boundary in tests.
test_path = ROOT / "tests/test_runtime_extraction_boundaries.py"
test = test_path.read_text(encoding="utf-8")
test = test.replace(
    "    order_runtime,\n",
    "    order_runtime,\n    order_storage_runtime,\n",
    1,
)
test = test.replace(
    "    assert callable(order_runtime.configure_order_runtime)\n",
    "    assert callable(order_runtime.configure_order_runtime)\n    assert callable(order_storage_runtime.configure_order_storage_runtime)\n",
    1,
)
needle = '''    assert "class DispatchClaimView" in order_source
    assert "class OrderCredentialModal" not in order_source
'''
replacement = '''    storage_source = Path("services/order_storage_runtime.py").read_text(
        encoding="utf-8"
    )

    assert "class DispatchClaimView" in order_source
    assert "async def lock_dispatch_claim_panel" not in order_source
    assert "async def store_dispatch_claim_panel" not in order_source
    assert "async def resume_stored_order" not in order_source
    assert "async def lock_dispatch_claim_panel" in storage_source
    assert "async def store_dispatch_claim_panel" in storage_source
    assert "async def resume_stored_order" in storage_source
    assert "def configure_order_storage_runtime" in storage_source
    assert "import bot" not in storage_source
    assert "from bot import" not in storage_source
    assert "class OrderCredentialModal" not in order_source
'''
if needle not in test:
    raise RuntimeError("storage boundary test anchor not found")
test_path.write_text(test.replace(needle, replacement, 1), encoding="utf-8")

claim_test_path = ROOT / "tests/test_bot_claim_finalization.py"
claim_test = claim_test_path.read_text(encoding="utf-8")
claim_test = claim_test.replace(
    'source = (root / "services" / "order_runtime.py").read_text(\n',
    'source = (root / "services" / "order_storage_runtime.py").read_text(\n',
    1,
)
claim_test = claim_test.replace(
    '''    end = source.index(
        "def sync_web_order_status_from_bot",
        start,
    )
    block = source[start:end]
''',
    '''    end = source.index("async def store_dispatch_claim_panel", start)
    block = source[start:end]
''',
    1,
)
claim_test_path.write_text(claim_test, encoding="utf-8")

budget_path = ROOT / "tests/test_architecture_growth_budget.py"
budget = budget_path.read_text(encoding="utf-8")
parent_size = PARENT.stat().st_size
child_size = CHILD.stat().st_size
round_up = lambda size: ((size + 1999) // 1000) * 1000
parent_limit = round_up(parent_size)
child_limit = round_up(child_size)
budget = budget.replace(
    '    "services/order_runtime.py": 87_000,\n',
    f'    "services/order_runtime.py": {parent_limit:_},\n'
    f'    "services/order_storage_runtime.py": {child_limit:_},\n',
    1,
)
budget_path.write_text(budget, encoding="utf-8")

print(f"parent bytes: {parent_size}; ceiling: {parent_limit}")
print(f"storage runtime bytes: {child_size}; ceiling: {child_limit}")
