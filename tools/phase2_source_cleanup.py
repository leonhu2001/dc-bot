from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (
    ROOT / "bot.py",
    ROOT / "cogs",
    ROOT / "core",
    ROOT / "services",
    ROOT / "shared",
    ROOT / "views",
    ROOT / "web" / "app",
)
UTC_IMPORT = "from core.time_utils import utc_now_naive\n"


def python_files():
    for root in SOURCE_ROOTS:
        if root.is_file():
            yield root
            continue
        yield from root.rglob("*.py")


def insert_utc_import(source: str) -> str:
    if UTC_IMPORT.strip() in source:
        return source

    lines = source.splitlines(keepends=True)
    insert_at = 0

    if lines and lines[0].startswith("#!"):
        insert_at = 1

    while insert_at < len(lines) and (
        lines[insert_at].startswith("#")
        or not lines[insert_at].strip()
    ):
        insert_at += 1

    if (
        insert_at < len(lines)
        and lines[insert_at].startswith("from __future__ import")
    ):
        insert_at += 1
        while insert_at < len(lines) and not lines[insert_at].strip():
            insert_at += 1

    lines.insert(insert_at, UTC_IMPORT)
    return "".join(lines)


def modernize_utcnow() -> int:
    changed = 0
    for path in sorted(set(python_files())):
        if path == ROOT / "core" / "time_utils.py":
            continue

        source = path.read_text(encoding="utf-8-sig")
        if "datetime.utcnow" not in source:
            continue

        updated = source.replace("datetime.utcnow", "utc_now_naive")
        updated = insert_utc_import(updated)
        path.write_text(updated, encoding="utf-8")
        changed += 1
        print(f"UTCNOW_MODERNIZED {path.relative_to(ROOT)}")
    return changed


def retire_order_patch_asset() -> None:
    catalog = ROOT / "web" / "app" / "templates" / "order_catalog.html"
    source = catalog.read_text(encoding="utf-8")
    block = '''\n<script\n    src="/static/js/mw_order_form_fix.js?v=3b211r-clean-modal"\n    defer\n></script>'''
    if block in source:
        source = source.replace(block, "")
        catalog.write_text(source, encoding="utf-8")
        print("PATCH_REFERENCE_REMOVED order_catalog.html")

    legacy = ROOT / "web" / "app" / "static" / "js" / "mw_order_form_fix.js"
    if legacy.exists():
        legacy.unlink()
        print("PATCH_ASSET_REMOVED mw_order_form_fix.js")

    audit = ROOT / "tools" / "audit_templates.py"
    audit_source = audit.read_text(encoding="utf-8")
    old = '''# The only remaining *_fix asset is a temporary compatibility loader for the\n# canonical order UI module. Runtime behavior must not be added back to it, and\n# no additional patch-style assets may be introduced.\nALLOWED_LEGACY_PATCH_ASSETS = {\n    "js/mw_order_form_fix.js",\n}\n'''
    new = '''# Patch-style frontend assets are fully retired. Keep this set empty so a new\n# *_fix.js / *_fix.css fails the static audit instead of becoming permanent debt.\nALLOWED_LEGACY_PATCH_ASSETS: set[str] = set()\n'''
    if old not in audit_source:
        raise RuntimeError("audit_templates.py patch-debt block changed unexpectedly")
    audit.write_text(audit_source.replace(old, new), encoding="utf-8")
    print("PATCH_DEBT_BUDGET_ZERO")


def main() -> None:
    count = modernize_utcnow()
    retire_order_patch_asset()
    print(f"SOURCE_CLEANUP_DONE utcnow_files={count}")


if __name__ == "__main__":
    main()
