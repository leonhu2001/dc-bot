from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "views" / "review.py"
SERVICE = ROOT / "services" / "review_storage.py"
BUDGET = ROOT / "tests" / "test_architecture_growth_budget.py"
SMOKE = ROOT / "tools" / "runtime_import_smoke.py"
TEST = ROOT / "tests" / "test_review_storage_extraction.py"

MOVE_NAMES = {
    "_root_dir",
    "_web_db_path",
    "_now_iso",
    "_connect",
    "ensure_review_tables",
    "_find_order",
    "get_review_targets",
    "_existing_reviews",
    "_has_skipped_all",
    "build_review_status",
    "record_review_skip",
    "record_member_review",
    "get_staff_favorites",
    "_get_post_close_tip_rows",
    "get_post_close_status",
    "add_staff_favorite",
}

PUBLIC_IMPORTS = (
    "ensure_review_tables",
    "get_review_targets",
    "build_review_status",
    "record_review_skip",
    "record_member_review",
    "get_staff_favorites",
    "get_post_close_status",
    "add_staff_favorite",
)

IMPORT_ANCHOR = "from views.worker_tips import ("

SERVICE_HEADER = '''from __future__ import annotations\n\nimport sqlite3\nfrom datetime import datetime\nfrom pathlib import Path\n\nfrom services.worker_tips import (\n    configure_worker_tip_store,\n    ensure_worker_tip_tables,\n)\n\n\n'''


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def rounded_budget(size: int, *, extra: int = 2000, floor: int = 5000) -> int:
    target = size + extra
    return max(floor, ((target + 4999) // 5000) * 5000)


def main() -> None:
    source = VIEW.read_text(encoding="utf-8")
    require("from services.review_storage import (" not in source, "review storage already extracted")
    require(IMPORT_ANCHOR in source, "worker tips import anchor missing")

    tree = ast.parse(source)
    candidates = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in MOVE_NAMES
    ]
    found = {node.name for node in candidates}
    missing = MOVE_NAMES - found
    require(not missing, "missing persistence functions: " + ", ".join(sorted(missing)))

    lines = source.splitlines(keepends=True)
    blocks: list[tuple[int, str]] = []
    spans: list[tuple[int, int]] = []
    for node in sorted(candidates, key=lambda item: item.lineno):
        start = node.lineno - 1
        end = int(node.end_lineno or node.lineno)
        while end < len(lines) and lines[end].strip() == "":
            end += 1
        blocks.append((start, "".join(lines[start:end]).rstrip() + "\n\n"))
        spans.append((start, end))

    keep = [True] * len(lines)
    for start, end in spans:
        for index in range(start, end):
            keep[index] = False
    view_source = "".join(line for index, line in enumerate(lines) if keep[index])

    import_text = "from services.review_storage import (\n" + "".join(
        f"    {name},\n" for name in PUBLIC_IMPORTS
    ) + ")\n"
    view_source = view_source.replace(IMPORT_ANCHOR, import_text + IMPORT_ANCHOR, 1)
    VIEW.write_text(view_source, encoding="utf-8")

    SERVICE.write_text(
        SERVICE_HEADER + "".join(block for _, block in blocks),
        encoding="utf-8",
    )

    # Persistence must be absent from the Discord view layer after extraction.
    final_view = VIEW.read_text(encoding="utf-8")
    require("conn.execute(" not in final_view, "SQLite execute call remains in views/review.py")
    require("CREATE TABLE IF NOT EXISTS order_reviews" not in final_view, "review DDL remains in view")
    require("CREATE TABLE IF NOT EXISTS staff_favorites" not in final_view, "favorite DDL remains in view")

    budget_source = BUDGET.read_text(encoding="utf-8")
    view_budget = rounded_budget(VIEW.stat().st_size)
    storage_budget = rounded_budget(SERVICE.stat().st_size)
    budget_source = budget_source.replace(
        '"views/review.py": 66_000,',
        f'"views/review.py": {view_budget:_},\n    "services/review_storage.py": {storage_budget:_},',
        1,
    )
    BUDGET.write_text(budget_source, encoding="utf-8")

    smoke_source = SMOKE.read_text(encoding="utf-8")
    smoke_source = smoke_source.replace(
        '    "services.worker_tips",',
        '    "services.worker_tips",\n    "services.review_storage",',
        1,
    )
    SMOKE.write_text(smoke_source, encoding="utf-8")

    TEST.write_text(
        '''from __future__ import annotations\n\nimport importlib\nfrom pathlib import Path\n\n\nROOT = Path(__file__).resolve().parents[1]\nVIEW = ROOT / "views" / "review.py"\nSTORE = ROOT / "services" / "review_storage.py"\n\n\ndef test_review_sql_is_canonical_in_storage_service():\n    view = VIEW.read_text(encoding="utf-8")\n    store = STORE.read_text(encoding="utf-8")\n\n    assert "from services.review_storage import (" in view\n    assert "conn.execute(" not in view\n    assert "CREATE TABLE IF NOT EXISTS order_reviews" not in view\n    assert "CREATE TABLE IF NOT EXISTS staff_favorites" not in view\n\n    for fragment in (\n        "CREATE TABLE IF NOT EXISTS order_reviews",\n        "CREATE TABLE IF NOT EXISTS order_review_skips",\n        "CREATE TABLE IF NOT EXISTS staff_favorites",\n        "INSERT INTO order_reviews",\n        "INSERT OR IGNORE INTO staff_favorites",\n    ):\n        assert fragment in store\n\n\ndef test_review_storage_exports_existing_view_contracts():\n    module = importlib.import_module("services.review_storage")\n    for name in (\n        "ensure_review_tables",\n        "get_review_targets",\n        "build_review_status",\n        "record_review_skip",\n        "record_member_review",\n        "get_staff_favorites",\n        "get_post_close_status",\n        "add_staff_favorite",\n    ):\n        assert callable(getattr(module, name))\n\n\ndef test_review_view_keeps_discord_orchestration_not_storage():\n    source = VIEW.read_text(encoding="utf-8")\n    for fragment in (\n        "class ReviewDraftConfirmView",\n        "class MemberReviewModal",\n        "async def refresh_post_close_panel",\n        "def build_post_close_status_embed",\n    ):\n        assert fragment in source\n\n\ndef test_review_storage_has_no_view_or_bot_dependency():\n    source = STORE.read_text(encoding="utf-8")\n    assert "import bot" not in source\n    assert "from bot import" not in source\n    assert "from views" not in source\n''',
        encoding="utf-8",
    )

    print("review persistence extracted")
    print("views/review.py bytes:", VIEW.stat().st_size)
    print("services/review_storage.py bytes:", SERVICE.stat().st_size)
    print("budgets:", view_budget, storage_budget)


if __name__ == "__main__":
    main()
