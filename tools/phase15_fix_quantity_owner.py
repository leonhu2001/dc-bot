from pathlib import Path

runtime = Path("services/self_service_runtime.py")
source = runtime.read_text(encoding="utf-8")

needle_import = "    build_self_service_order_embed,\n    get_self_service_quantity_unit,\n)\n"
replacement_import = "    build_self_service_order_embed,\n)\n"
if needle_import not in source:
    raise SystemExit("quantity helper import block not found")
source = source.replace(needle_import, replacement_import, 1)

needle_guard = '        "build_self_service_order_embed",\n        "get_self_service_quantity_unit",\n        "remember_claim_data",\n'
replacement_guard = '        "build_self_service_order_embed",\n        "remember_claim_data",\n'
if needle_guard not in source:
    raise SystemExit("quantity helper guard entry not found")
source = source.replace(needle_guard, replacement_guard, 1)
runtime.write_text(source, encoding="utf-8")

test = Path("tests/test_self_service_runtime_dependency_boundary.py")
test_source = test.read_text(encoding="utf-8")
test_source = test_source.replace(
    "    assert self_service_runtime.get_self_service_quantity_unit is orders.get_self_service_quantity_unit\n",
    "",
    1,
)
test_source = test_source.replace(
    '        "build_self_service_order_embed",\n        "get_self_service_quantity_unit",\n        "remember_claim_data",\n',
    '        "build_self_service_order_embed",\n        "remember_claim_data",\n',
    1,
)
test.write_text(test_source, encoding="utf-8")
