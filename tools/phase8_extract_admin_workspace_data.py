from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "web" / "app" / "routers" / "admin_order_workspace.py"
SERVICE = ROOT / "web" / "app" / "services" / "admin_order_workspace_data.py"

TARGETS = [
    "_mw4a2r6_table_exists",
    "_mw4a2r6_safe_int",
    "_mw4a2r6_json",
    "_mw4a2r6_time",
    "_mw4a2r6_status_label",
    "_mw4a2r6_meta_map",
    "_mw4a2r6_ensure_meta_table",
    "_mw4a2r6_user_name",
    "_mw4a2r6_staff_map",
    "_mw4a2r6_cs_members",
    "_mw4a2r6_load_order_bundle",
]

source = ROUTER.read_text(encoding="utf-8")
tree = ast.parse(source)
lines = source.splitlines(keepends=True)
nodes = {
    node.name: node
    for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    and node.name in TARGETS
}
missing = set(TARGETS) - nodes.keys()
if missing:
    raise RuntimeError(f"missing admin workspace data definitions: {sorted(missing)}")

blocks = []
for name in TARGETS:
    node = nodes[name]
    blocks.append("".join(lines[node.lineno - 1 : node.end_lineno]).rstrip() + "\n")

SERVICE.write_text(
    '''from __future__ import annotations

from sqlalchemy import text

from web.app.services.staff_service import list_customer_service_members


'''
    + "\n\n".join(blocks),
    encoding="utf-8",
)

for node in sorted(nodes.values(), key=lambda item: item.lineno, reverse=True):
    del lines[node.lineno - 1 : node.end_lineno]
router = "".join(lines)

anchor = '''from web.app.services.order_financial_edit import (
    preserve_order_financial_gaps,
)
'''
imports = '''from web.app.services.admin_order_workspace_data import (
    _mw4a2r6_cs_members,
    _mw4a2r6_ensure_meta_table,
    _mw4a2r6_load_order_bundle,
    _mw4a2r6_safe_int,
    _mw4a2r6_table_exists,
    _mw4a2r6_user_name,
)
'''
if anchor not in router:
    raise RuntimeError("router service import anchor missing")
router = router.replace(anchor, anchor + imports, 1)
ROUTER.write_text(router, encoding="utf-8")

# Boundary tests prevent data/view-model construction from drifting back into the router.
test_path = ROOT / "tests" / "test_admin_order_workspace_data_boundary.py"
test_path.write_text(
    '''from pathlib import Path


def test_admin_order_workspace_data_bundle_is_owned_by_service():
    router = Path("web/app/routers/admin_order_workspace.py").read_text(encoding="utf-8")
    service = Path("web/app/services/admin_order_workspace_data.py").read_text(encoding="utf-8")

    assert "def _mw4a2r6_load_order_bundle" not in router
    assert "def _mw4a2r6_load_order_bundle" in service
    assert "def _mw4a2r6_staff_map" not in router
    assert "def _mw4a2r6_staff_map" in service
    assert "def _mw4a2r6_meta_map" not in router
    assert "def _mw4a2r6_meta_map" in service


def test_admin_order_workspace_router_keeps_http_actions_not_data_builder():
    router = Path("web/app/routers/admin_order_workspace.py").read_text(encoding="utf-8")
    service = Path("web/app/services/admin_order_workspace_data.py").read_text(encoding="utf-8")

    assert '@router.get("/admin/order-workspace/{order_id}")' in router
    assert "async def admin_order_workspace_edit_r8" in router
    assert "APIRouter" not in service
    assert "RedirectResponse" not in service
''',
    encoding="utf-8",
)

budget_path = ROOT / "tests" / "test_architecture_growth_budget.py"
budget = budget_path.read_text(encoding="utf-8")
router_size = ROUTER.stat().st_size
service_size = SERVICE.stat().st_size
round_up = lambda size: ((size + 1999) // 1000) * 1000
router_limit = round_up(router_size)
service_limit = round_up(service_size)
budget = budget.replace(
    '    "web/app/routers/admin_order_workspace.py": 68_000,\n',
    f'    "web/app/routers/admin_order_workspace.py": {router_limit:_},\n'
    f'    "web/app/services/admin_order_workspace_data.py": {service_limit:_},\n',
    1,
)
budget_path.write_text(budget, encoding="utf-8")

print(f"admin_order_workspace.py bytes={router_size} ceiling={router_limit}")
print(f"admin_order_workspace_data.py bytes={service_size} ceiling={service_limit}")
