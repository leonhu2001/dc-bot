from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Canonical import paths are now thin facades. Existing implementations are
# isolated under *_legacy and may only shrink while responsibilities are moved
# into focused services/views.
MAX_BYTES = {
    "bot.py": 276_000,
    "services/order_runtime.py": 2_000,
    "services/order_runtime_legacy.py": 129_000,
    "services/self_service_runtime.py": 2_000,
    "services/self_service_runtime_legacy.py": 146_000,
    "web/app/routers/admin.py": 2_000,
    "web/app/routers/admin_legacy.py": 102_000,
    "views/review.py": 95_500,
}

LEGACY_IMPORT_TOKENS = (
    "services.order_runtime_legacy",
    "services.self_service_runtime_legacy",
    "web.app.routers.admin_legacy",
)


def test_legacy_runtime_files_do_not_grow() -> None:
    oversized: list[str] = []
    for relative_path, limit in MAX_BYTES.items():
        size = (ROOT / relative_path).stat().st_size
        if size > limit:
            oversized.append(f"{relative_path}: {size} > {limit}")

    assert not oversized, (
        "Canonical facades or isolated legacy modules exceeded their budget:\n"
        + "\n".join(oversized)
    )


def test_new_services_do_not_import_bot_entrypoint() -> None:
    offenders: list[str] = []
    for path in (ROOT / "services").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "import bot" in source or "from bot import" in source:
            offenders.append(str(path.relative_to(ROOT)))

    assert not offenders, (
        "services must depend on explicit APIs, not bot.py globals: "
        + ", ".join(offenders)
    )


def test_canonical_runtime_files_are_facades_not_new_implementation_hosts() -> None:
    facade_paths = (
        "services/order_runtime.py",
        "services/self_service_runtime.py",
        "web/app/routers/admin.py",
    )
    for relative_path in facade_paths:
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "sys.modules[__name__] = _legacy" in source, relative_path
        assert source.count("\n") < 40, relative_path


def test_application_code_does_not_bypass_canonical_legacy_facades() -> None:
    offenders: list[str] = []
    roots = (
        ROOT / "bot.py",
        ROOT / "cogs",
        ROOT / "core",
        ROOT / "services",
        ROOT / "shared",
        ROOT / "views",
        ROOT / "web" / "app",
    )
    facade_paths = {
        ROOT / "services" / "order_runtime.py",
        ROOT / "services" / "self_service_runtime.py",
        ROOT / "web" / "app" / "routers" / "admin.py",
    }

    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        else:
            files.extend(root.rglob("*.py"))

    for path in files:
        if path in facade_paths or path.name.endswith("_legacy.py"):
            continue
        source = path.read_text(encoding="utf-8")
        if any(token in source for token in LEGACY_IMPORT_TOKENS):
            offenders.append(str(path.relative_to(ROOT)))

    assert not offenders, (
        "application code must import canonical facade paths, not *_legacy: "
        + ", ".join(offenders)
    )
