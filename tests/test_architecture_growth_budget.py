from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Canonical import paths are now thin facades.  Existing implementations are
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
