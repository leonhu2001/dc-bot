from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "services" / "self_service_runtime.py"
SERVICE = ROOT / "services" / "self_service_selection_runtime.py"
BUDGET = ROOT / "tests" / "test_architecture_growth_budget.py"
SMOKE = ROOT / "tools" / "runtime_import_smoke.py"
TEST = ROOT / "tests" / "test_self_service_selection_runtime_extraction.py"

START = "SPECIFIED_STAFF_SELECT_PAGE_SIZE = 25"
END = "def is_self_service_staff_price_required("
IMPORT_ANCHOR = "from services.self_service_reorder import ("
CONFIG_FINISH = "    _CONFIGURED = True\n"

SERVICE_IMPORT = '''from services.self_service_selection_runtime import (\n    configure_self_service_selection_runtime,\n    FREE_PLAY_FIRST_HOUR_RULE_KEYS,\n    ORDER_POINT_BENEFIT_SPECS,\n    get_specified_staff_entries_for_rule,\n    SelfServicePointBenefitView,\n    SelfServiceSpecifiedStaffDropdownView,\n)\n\n\n'''

SERVICE_HEADER = '''from __future__ import annotations\n\nfrom collections.abc import Callable\nfrom typing import Any\n\nimport discord\n\n\n_CONFIGURED = False\nSELF_SERVICE_ORDER_SELECTIONS: dict = {}\nPOINT_REDEEM_ITEMS: list[dict] = []\n\n\ndef _unconfigured(*args, **kwargs):\n    raise RuntimeError("self-service selection runtime is not configured")\n\n\n_role_key_for_member: Callable[..., Any] = _unconfigured\nremember_order_data: Callable[..., Any] = _unconfigured\nbuild_self_service_panel_embed: Callable[..., Any] = _unconfigured\nSelfServiceOrderView: Any = None\n_to_int: Callable[..., Any] = _unconfigured\nget_order_point_item: Callable[..., Any] = _unconfigured\nget_customer_point_balance_for_order: Callable[..., Any] = _unconfigured\nis_order_point_benefit_allowed_for_rule: Callable[..., Any] = _unconfigured\n_adapt_order_point_benefit_for_rule: Callable[..., Any] = _unconfigured\nget_selected_order_point_benefit: Callable[..., Any] = _unconfigured\n\n\ndef configure_self_service_selection_runtime(\n    *,\n    order_selections: dict,\n    point_redeem_items: list[dict],\n    role_key_for_member: Callable[..., Any],\n    remember_data: Callable[..., Any],\n    panel_embed_builder: Callable[..., Any],\n    order_view_type: Any,\n    to_int: Callable[..., Any],\n    order_point_item_getter: Callable[..., Any],\n    customer_point_balance_getter: Callable[..., Any],\n    point_benefit_allowed_for_rule: Callable[..., Any],\n    point_benefit_adapter: Callable[..., Any],\n    selected_point_benefit_getter: Callable[..., Any],\n) -> None:\n    global _CONFIGURED\n    global SELF_SERVICE_ORDER_SELECTIONS, POINT_REDEEM_ITEMS\n    global _role_key_for_member, remember_order_data\n    global build_self_service_panel_embed, SelfServiceOrderView, _to_int\n    global get_order_point_item, get_customer_point_balance_for_order\n    global is_order_point_benefit_allowed_for_rule\n    global _adapt_order_point_benefit_for_rule, get_selected_order_point_benefit\n\n    if order_view_type is None:\n        raise RuntimeError("self-service selection runtime requires order_view_type")\n\n    SELF_SERVICE_ORDER_SELECTIONS = order_selections\n    POINT_REDEEM_ITEMS = point_redeem_items\n    _role_key_for_member = role_key_for_member\n    remember_order_data = remember_data\n    build_self_service_panel_embed = panel_embed_builder\n    SelfServiceOrderView = order_view_type\n    _to_int = to_int\n    get_order_point_item = order_point_item_getter\n    get_customer_point_balance_for_order = customer_point_balance_getter\n    is_order_point_benefit_allowed_for_rule = point_benefit_allowed_for_rule\n    _adapt_order_point_benefit_for_rule = point_benefit_adapter\n    get_selected_order_point_benefit = selected_point_benefit_getter\n    _CONFIGURED = True\n\n\n'''

CONFIG_CALL = '''\n    selection_keys = {\n        "SELF_SERVICE_ORDER_SELECTIONS",\n        "POINT_REDEEM_ITEMS",\n        "_to_int",\n        "remember_order_data",\n    }\n    if selection_keys.issubset(namespace):\n        configure_self_service_selection_runtime(\n            order_selections=namespace["SELF_SERVICE_ORDER_SELECTIONS"],\n            point_redeem_items=namespace["POINT_REDEEM_ITEMS"],\n            role_key_for_member=_role_key_for_member,\n            remember_data=namespace["remember_order_data"],\n            panel_embed_builder=build_self_service_panel_embed,\n            order_view_type=SelfServiceOrderView,\n            to_int=namespace["_to_int"],\n            order_point_item_getter=get_order_point_item,\n            customer_point_balance_getter=get_customer_point_balance_for_order,\n            point_benefit_allowed_for_rule=is_order_point_benefit_allowed_for_rule,\n            point_benefit_adapter=_adapt_order_point_benefit_for_rule,\n            selected_point_benefit_getter=get_selected_order_point_benefit,\n        )\n'''


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def rounded_budget(size: int, *, floor: int = 5_000) -> int:
    target = size + 2_000
    rounded = ((target + 4_999) // 5_000) * 5_000
    return max(floor, rounded)


def main() -> None:
    source = PARENT.read_text(encoding="utf-8")
    require(START in source, "selection start anchor missing")
    require(END in source, "selection end anchor missing")
    require("from services.self_service_selection_runtime import (" not in source, "selection runtime already extracted")
    require(IMPORT_ANCHOR in source, "reorder import anchor missing")
    require(CONFIG_FINISH in source, "configure finish anchor missing")

    start = source.index(START)
    end = source.index(END, start)
    block = source[start:end].rstrip() + "\n"

    required_symbols = (
        "def get_specified_staff_entries_for_rule(",
        "class SelfServiceSpecifiedStaffDropdown(",
        "class SelfServicePointBenefitSelect(",
        "class SelfServicePointBenefitView(",
        "class SelfServiceSpecifiedStaffDropdownView(",
        "ORDER_POINT_BENEFIT_SPECS = {",
    )
    for symbol in required_symbols:
        require(symbol in block, f"selection block missing {symbol}")

    SERVICE.write_text(SERVICE_HEADER + block, encoding="utf-8")

    source = source[:start] + "# 指定陪玩 / 點數福利選擇 UI 已移至 services/self_service_selection_runtime.py\n\n" + source[end:]
    source = source.replace(IMPORT_ANCHOR, SERVICE_IMPORT + IMPORT_ANCHOR, 1)
    source = source.replace(CONFIG_FINISH, CONFIG_CALL + "\n" + CONFIG_FINISH, 1)
    PARENT.write_text(source, encoding="utf-8")

    parent_budget = rounded_budget(PARENT.stat().st_size)
    service_budget = rounded_budget(SERVICE.stat().st_size)
    budget_source = BUDGET.read_text(encoding="utf-8")
    budget_source = budget_source.replace('"services/self_service_runtime.py": 86_000,', f'"services/self_service_runtime.py": {parent_budget:_},', 1)
    budget_source = budget_source.replace(
        '"services/self_service_reorder.py": 33_000,',
        f'"services/self_service_reorder.py": 33_000,\n    "services/self_service_selection_runtime.py": {service_budget:_},',
        1,
    )
    BUDGET.write_text(budget_source, encoding="utf-8")

    smoke_source = SMOKE.read_text(encoding="utf-8")
    smoke_source = smoke_source.replace(
        '    "services.self_service_runtime",',
        '    "services.self_service_runtime",\n    "services.self_service_selection_runtime",',
        1,
    )
    SMOKE.write_text(smoke_source, encoding="utf-8")

    TEST.write_text(
        '''from __future__ import annotations\n\nimport importlib\nfrom pathlib import Path\n\n\nROOT = Path(__file__).resolve().parents[1]\nPARENT = ROOT / "services" / "self_service_runtime.py"\nSERVICE = ROOT / "services" / "self_service_selection_runtime.py"\n\n\ndef test_selection_ui_is_canonical_in_dedicated_service():\n    parent = PARENT.read_text(encoding="utf-8")\n    service = SERVICE.read_text(encoding="utf-8")\n\n    assert "from services.self_service_selection_runtime import (" in parent\n    assert "configure_self_service_selection_runtime(" in parent\n\n    for symbol in (\n        "def get_specified_staff_entries_for_rule(",\n        "class SelfServiceSpecifiedStaffDropdown(",\n        "class SelfServicePointBenefitSelect(",\n        "class SelfServicePointBenefitView(",\n        "class SelfServiceSpecifiedStaffDropdownView(",\n        "ORDER_POINT_BENEFIT_SPECS = {",\n    ):\n        assert symbol not in parent\n        assert symbol in service\n\n\ndef test_selection_runtime_import_smoke():\n    module = importlib.import_module("services.self_service_selection_runtime")\n    assert callable(module.configure_self_service_selection_runtime)\n    assert issubclass(module.SelfServicePointBenefitView, module.discord.ui.View)\n    assert issubclass(module.SelfServiceSpecifiedStaffDropdownView, module.discord.ui.View)\n\n\ndef test_selection_runtime_has_no_parent_or_bot_import_cycle():\n    source = SERVICE.read_text(encoding="utf-8")\n    assert "import bot" not in source\n    assert "from bot import" not in source\n    assert "import services.self_service_runtime" not in source\n    assert "from services.self_service_runtime import" not in source\n\n\ndef test_parent_configures_selection_with_explicit_dependencies():\n    source = PARENT.read_text(encoding="utf-8")\n    for fragment in (\n        "order_selections=namespace[\\\"SELF_SERVICE_ORDER_SELECTIONS\\\"]",\n        "point_redeem_items=namespace[\\\"POINT_REDEEM_ITEMS\\\"]",\n        "role_key_for_member=_role_key_for_member",\n        "order_view_type=SelfServiceOrderView",\n        "point_benefit_adapter=_adapt_order_point_benefit_for_rule",\n    ):\n        assert fragment in source\n''',
        encoding="utf-8",
    )

    print("self-service selection runtime extracted")
    print("self_service_runtime.py bytes:", PARENT.stat().st_size)
    print("self_service_selection_runtime.py bytes:", SERVICE.stat().st_size)
    print("budgets:", parent_budget, service_budget)


if __name__ == "__main__":
    main()
