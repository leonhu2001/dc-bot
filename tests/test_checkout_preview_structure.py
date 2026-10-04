import ast
from pathlib import Path


def test_staff_order_filter_has_single_top_level_definition():
    source = Path("web/app/services/checkout_preview.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    definitions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "build_staff_order_filter"
    ]

    assert len(definitions) == 1
