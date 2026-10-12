from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# These are ceilings, not targets. Existing large modules should shrink over time;
# the guard prevents unrelated features from silently making them larger again.
MAX_BYTES = {
    "bot.py": 273_000,
    "services/order_runtime.py": 87_000,
    "services/order_payment_runtime.py": 27_000,
    "services/order_credential_runtime.py": 23_500,
    "services/order_point_redemption.py": 7_000,
    "services/self_service_runtime.py": 86_000,
    "services/self_service_reorder.py": 33_000,
    "services/self_service_financials.py": 42_000,
    "web/app/main.py": 18_500,
    "web/app/routers/admin.py": 14_000,
    "web/app/routers/admin_dashboard.py": 29_000,
    "web/app/routers/admin_order_workspace.py": 68_000,
    "views/review.py": 95_500,
}


def test_legacy_runtime_files_do_not_grow() -> None:
    oversized: list[str] = []
    for relative_path, limit in MAX_BYTES.items():
        size = (ROOT / relative_path).stat().st_size
        if size > limit:
            oversized.append(f"{relative_path}: {size} > {limit}")

    assert not oversized, (
        "Large legacy modules grew instead of being extracted:\n"
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
