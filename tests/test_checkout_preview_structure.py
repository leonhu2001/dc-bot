import ast
from pathlib import Path


PRODUCTION_ROOTS = (
    Path("cogs"),
    Path("core"),
    Path("services"),
    Path("shared"),
    Path("views"),
    Path("web/app"),
)


def _production_python_files():
    yield Path("bot.py")

    for root in PRODUCTION_ROOTS:
        yield from sorted(root.rglob("*.py"))


def test_production_modules_do_not_override_top_level_definitions():
    duplicates = []

    for path in _production_python_files():
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source)

        seen = set()

        for node in tree.body:
            if not isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            ):
                continue

            if node.name in seen:
                duplicates.append(f"{path}:{node.lineno}:{node.name}")
            else:
                seen.add(node.name)

    assert duplicates == []
