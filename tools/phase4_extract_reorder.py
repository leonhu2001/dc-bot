from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "services/self_service_runtime.py"
CHILD = ROOT / "services/self_service_reorder.py"

NAMES = [
    "_reorder_order_value",
    "_reorder_json_dict",
    "build_reorder_self_service_draft",
    "_reorder_message_has_component",
    "_find_reorder_panel_message",
    "ensure_reorder_ticket_panels",
    "create_reorder_ticket_from_closed_order",
]

source = PARENT.read_text(encoding="utf-8")
tree = ast.parse(source)
lines = source.splitlines(keepends=True)
nodes = {
    node.name: node
    for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in NAMES
}
missing = set(NAMES) - nodes.keys()
if missing:
    raise RuntimeError(f"missing reorder definitions: {sorted(missing)}")

pieces = []
for name in NAMES:
    node = nodes[name]
    pieces.append("".join(lines[node.lineno - 1 : node.end_lineno]).rstrip() + "\n")

header = '''from __future__ import annotations

import json
from typing import Any, Callable

import discord


_CONFIGURED = False


def configure_self_service_reorder(
    *,
    order_category_labels,
    order_item_groups_by_category,
    get_order_rule_by_item_label: Callable,
    role_key_for_member: Callable,
    to_int: Callable,
    order_item_details_for_group: Callable,
    order_item_group_label: Callable,
    self_service_quantity_meta: Callable,
    taipei_now_iso: Callable,
    staff_price_required: Callable,
    customer_role_id: int,
    customer_category_id: int,
    order_control_view,
    self_service_order_view,
    panel_embed_builder: Callable,
    self_service_order_selections: dict,
    remember_data: Callable,
    save_data: Callable,
    ticket_channel_name_builder: Callable,
    delete_order_row: Callable,
    order_log_sender: Callable,
) -> None:
    """Bind the explicit APIs needed by the reorder ticket workflow."""
    global _CONFIGURED
    global ORDER_CATEGORY_LABELS, ORDER_ITEM_GROUPS_BY_CATEGORY
    global _get_order_rule_by_item_label, _role_key_for_member, _to_int
    global get_order_item_details_for_group, get_order_item_group_label
    global get_self_service_quantity_meta, get_taipei_now_iso
    global is_self_service_staff_price_required
    global CUSTOMER_ROLE_ID, CUSTOMER_CATEGORY_ID
    global OrderControlView, SelfServiceOrderView, build_self_service_panel_embed
    global SELF_SERVICE_ORDER_SELECTIONS, remember_order_data, save_bot_data
    global build_ticket_channel_name, delete_order_row_from_db, send_order_log

    ORDER_CATEGORY_LABELS = order_category_labels
    ORDER_ITEM_GROUPS_BY_CATEGORY = order_item_groups_by_category
    _get_order_rule_by_item_label = get_order_rule_by_item_label
    _role_key_for_member = role_key_for_member
    _to_int = to_int
    get_order_item_details_for_group = order_item_details_for_group
    get_order_item_group_label = order_item_group_label
    get_self_service_quantity_meta = self_service_quantity_meta
    get_taipei_now_iso = taipei_now_iso
    is_self_service_staff_price_required = staff_price_required
    CUSTOMER_ROLE_ID = int(customer_role_id)
    CUSTOMER_CATEGORY_ID = int(customer_category_id)
    OrderControlView = order_control_view
    SelfServiceOrderView = self_service_order_view
    build_self_service_panel_embed = panel_embed_builder
    SELF_SERVICE_ORDER_SELECTIONS = self_service_order_selections
    remember_order_data = remember_data
    save_bot_data = save_data
    build_ticket_channel_name = ticket_channel_name_builder
    delete_order_row_from_db = delete_order_row
    send_order_log = order_log_sender
    _CONFIGURED = True


'''
CHILD.write_text(header + "\n\n".join(pieces), encoding="utf-8")

# Remove the physical implementations from the parent, bottom-up so line numbers stay valid.
for node in sorted(nodes.values(), key=lambda item: item.lineno, reverse=True):
    del lines[node.lineno - 1 : node.end_lineno]
parent = "".join(lines)

child_import = '''from services.self_service_reorder import (
    configure_self_service_reorder,
    _reorder_order_value,
    _reorder_json_dict,
    build_reorder_self_service_draft,
    _reorder_message_has_component,
    _find_reorder_panel_message,
    ensure_reorder_ticket_panels,
    create_reorder_ticket_from_closed_order,
)

'''
anchor = "\n\n_CONFIGURED = False\n"
if anchor not in parent:
    raise RuntimeError("self-service configured marker not found")
parent = parent.replace(anchor, "\n\n" + child_import + "_CONFIGURED = False\n", 1)

configure_anchor = '''    if financial_keys.issubset(namespace):
        configure_self_service_financials(
'''
if configure_anchor not in parent:
    raise RuntimeError("financial configure anchor not found")

end_anchor = "\n    _CONFIGURED = True\n"
position = parent.find(end_anchor)
if position < 0:
    raise RuntimeError("configure completion marker not found")

reorder_binding = '''
    reorder_keys = {
        "ORDER_CATEGORY_LABELS",
        "ORDER_ITEM_GROUPS_BY_CATEGORY",
        "CUSTOMER_ROLE_ID",
        "CUSTOMER_CATEGORY_ID",
        "SELF_SERVICE_ORDER_SELECTIONS",
        "OrderControlView",
        "_get_order_rule_by_item_label",
        "_to_int",
        "build_ticket_channel_name",
        "delete_order_row_from_db",
        "get_order_item_details_for_group",
        "get_order_item_group_label",
        "get_self_service_quantity_meta",
        "get_taipei_now_iso",
        "remember_order_data",
        "save_bot_data",
        "send_order_log",
    }
    if reorder_keys.issubset(namespace):
        configure_self_service_reorder(
            order_category_labels=namespace["ORDER_CATEGORY_LABELS"],
            order_item_groups_by_category=namespace["ORDER_ITEM_GROUPS_BY_CATEGORY"],
            get_order_rule_by_item_label=namespace["_get_order_rule_by_item_label"],
            role_key_for_member=_role_key_for_member,
            to_int=namespace["_to_int"],
            order_item_details_for_group=namespace["get_order_item_details_for_group"],
            order_item_group_label=namespace["get_order_item_group_label"],
            self_service_quantity_meta=namespace["get_self_service_quantity_meta"],
            taipei_now_iso=namespace["get_taipei_now_iso"],
            staff_price_required=is_self_service_staff_price_required,
            customer_role_id=namespace["CUSTOMER_ROLE_ID"],
            customer_category_id=namespace["CUSTOMER_CATEGORY_ID"],
            order_control_view=namespace["OrderControlView"],
            self_service_order_view=SelfServiceOrderView,
            panel_embed_builder=build_self_service_panel_embed,
            self_service_order_selections=namespace["SELF_SERVICE_ORDER_SELECTIONS"],
            remember_data=namespace["remember_order_data"],
            save_data=namespace["save_bot_data"],
            ticket_channel_name_builder=namespace["build_ticket_channel_name"],
            delete_order_row=namespace["delete_order_row_from_db"],
            order_log_sender=namespace["send_order_log"],
        )
'''
parent = parent[:position] + reorder_binding + parent[position:]
PARENT.write_text(parent, encoding="utf-8")

# Strengthen physical-boundary regression coverage.
test_path = ROOT / "tests/test_runtime_extraction_boundaries.py"
test = test_path.read_text(encoding="utf-8")
test = test.replace(
    "    self_service_financials,\n    self_service_runtime,\n",
    "    self_service_financials,\n    self_service_reorder,\n    self_service_runtime,\n",
    1,
)
test = test.replace(
    "    assert callable(self_service_financials.configure_self_service_financials)\n",
    "    assert callable(self_service_financials.configure_self_service_financials)\n    assert callable(self_service_reorder.configure_self_service_reorder)\n",
    1,
)
old = '''    assert "class SelfServiceOrderView" in self_service_source
    assert "async def build_reorder_self_service_draft" in self_service_source

    assert "def calculate_self_service_financials" in financials_source
'''
new = '''    reorder_source = Path("services/self_service_reorder.py").read_text(
        encoding="utf-8"
    )

    assert "class SelfServiceOrderView" in self_service_source
    assert "async def build_reorder_self_service_draft" not in self_service_source
    assert "async def create_reorder_ticket_from_closed_order" not in self_service_source
    assert "async def build_reorder_self_service_draft" in reorder_source
    assert "async def create_reorder_ticket_from_closed_order" in reorder_source
    assert "def configure_self_service_reorder" in reorder_source
    assert "import bot" not in reorder_source
    assert "from bot import" not in reorder_source

    assert "def calculate_self_service_financials" in financials_source
'''
if old not in test:
    raise RuntimeError("runtime extraction test anchor not found")
test_path.write_text(test.replace(old, new, 1), encoding="utf-8")

# Tighten growth budgets to the post-extraction baseline.
budget_path = ROOT / "tests/test_architecture_growth_budget.py"
budget = budget_path.read_text(encoding="utf-8")
parent_size = PARENT.stat().st_size
child_size = CHILD.stat().st_size
round_up = lambda size: ((size + 1999) // 1000) * 1000
parent_limit = round_up(parent_size)
child_limit = round_up(child_size)
budget = budget.replace(
    '    "services/self_service_runtime.py": 113_000,\n',
    f'    "services/self_service_runtime.py": {parent_limit:_},\n'
    f'    "services/self_service_reorder.py": {child_limit:_},\n',
    1,
)
budget_path.write_text(budget, encoding="utf-8")

print(f"parent bytes: {parent_size}; ceiling: {parent_limit}")
print(f"reorder bytes: {child_size}; ceiling: {child_limit}")
