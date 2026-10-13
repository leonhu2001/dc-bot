from pathlib import Path


runtime_path = Path("services/self_service_runtime.py")
source = runtime_path.read_text(encoding="utf-8")

old_imports = """from __future__ import annotations

from typing import Any, Mapping

import discord
"""
new_imports = """from __future__ import annotations

import json
from typing import Any, Mapping

import discord

from core.database import remember_claim_data, remember_order_data, save_bot_data
from core.permissions import is_customer_staff
from core.time_utils import get_taipei_now_iso
from services.orders import (
    ORDER_CATEGORY_LABELS,
    _to_int,
    build_self_service_order_embed,
    get_self_service_quantity_unit,
)
from services.smart_dispatch import create_smart_dispatch_plan, set_specified_dm_results
"""
if old_imports not in source:
    raise SystemExit("expected self_service_runtime import block not found")
source = source.replace(old_imports, new_imports, 1)

old_config = """_CONFIGURED = False


def configure_self_service_runtime(namespace: Mapping[str, Any]) -> None:
    \"\"\"Bind remaining bot-owned legacy dependencies after bot.py is loaded.\"\"\"
    global _CONFIGURED

    for name, value in namespace.items():
        if name.startswith(\"__\"):
            continue
        if name == \"configure_self_service_runtime\":
            continue
        globals()[name] = value
"""
new_config = """# Dependencies with a stable owning module are imported directly above and must not
# be replaced by the legacy bot.py namespace injection. Keeping this allow-list
# explicit lets us shrink the remaining runtime surface incrementally without
# changing the public Discord self-service entry points.
_MODULE_OWNED_RUNTIME_NAMES = frozenset(
    {
        \"json\",
        \"ORDER_CATEGORY_LABELS\",
        \"_to_int\",
        \"build_self_service_order_embed\",
        \"get_self_service_quantity_unit\",
        \"remember_claim_data\",
        \"remember_order_data\",
        \"save_bot_data\",
        \"is_customer_staff\",
        \"get_taipei_now_iso\",
        \"create_smart_dispatch_plan\",
        \"set_specified_dm_results\",
    }
)

_CONFIGURED = False


def configure_self_service_runtime(namespace: Mapping[str, Any]) -> None:
    \"\"\"Bind only the remaining bot-owned legacy dependencies after bot.py is loaded.\"\"\"
    global _CONFIGURED

    for name, value in namespace.items():
        if name.startswith(\"__\"):
            continue
        if name == \"configure_self_service_runtime\":
            continue
        if name in _MODULE_OWNED_RUNTIME_NAMES:
            continue
        globals()[name] = value
"""
if old_config not in source:
    raise SystemExit("expected self_service_runtime configure block not found")
source = source.replace(old_config, new_config, 1)
runtime_path.write_text(source, encoding="utf-8")


test_path = Path("tests/test_self_service_runtime_dependency_boundary.py")
test_path.write_text(
    '''from __future__ import annotations

import json

from core import database, permissions, time_utils
from services import orders, self_service_runtime, smart_dispatch


def test_self_service_runtime_uses_canonical_module_owned_dependencies():
    assert self_service_runtime.json is json
    assert self_service_runtime.ORDER_CATEGORY_LABELS is orders.ORDER_CATEGORY_LABELS
    assert self_service_runtime._to_int is orders._to_int
    assert self_service_runtime.build_self_service_order_embed is orders.build_self_service_order_embed
    assert self_service_runtime.get_self_service_quantity_unit is orders.get_self_service_quantity_unit
    assert self_service_runtime.remember_claim_data is database.remember_claim_data
    assert self_service_runtime.remember_order_data is database.remember_order_data
    assert self_service_runtime.save_bot_data is database.save_bot_data
    assert self_service_runtime.is_customer_staff is permissions.is_customer_staff
    assert self_service_runtime.get_taipei_now_iso is time_utils.get_taipei_now_iso
    assert self_service_runtime.create_smart_dispatch_plan is smart_dispatch.create_smart_dispatch_plan
    assert self_service_runtime.set_specified_dm_results is smart_dispatch.set_specified_dm_results


def test_legacy_configurator_cannot_shadow_module_owned_dependencies():
    canonical_json = self_service_runtime.json
    marker = object()
    self_service_runtime.configure_self_service_runtime(
        {
            "json": object(),
            "_self_service_dependency_boundary_marker": marker,
        }
    )

    assert self_service_runtime.json is canonical_json
    assert self_service_runtime._self_service_dependency_boundary_marker is marker


def test_module_owned_dependency_names_are_explicitly_guarded():
    expected = {
        "json",
        "ORDER_CATEGORY_LABELS",
        "_to_int",
        "build_self_service_order_embed",
        "get_self_service_quantity_unit",
        "remember_claim_data",
        "remember_order_data",
        "save_bot_data",
        "is_customer_staff",
        "get_taipei_now_iso",
        "create_smart_dispatch_plan",
        "set_specified_dm_results",
    }
    assert expected <= self_service_runtime._MODULE_OWNED_RUNTIME_NAMES
''',
    encoding="utf-8",
)
