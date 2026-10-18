from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# These are ceilings, not targets. Existing large modules should shrink over time;
# the guard prevents unrelated features from silently making them larger again.
MAX_BYTES = {
    "bot.py": 235_000,
    "services/vip_voice_runtime.py": 12_000,
    "services/order_lifecycle_runtime.py": 36_000,
    "services/order_runtime.py": 45_000,
    "services/order_dispatch_runtime.py": 30_000,
    "services/order_storage_runtime.py": 32_000,
    "services/order_payment_runtime.py": 27_000,
    "services/order_credential_runtime.py": 23_500,
    "services/order_point_redemption.py": 7_000,
    "services/self_service_runtime.py": 70_000,
    "services/web_sync/runtime.py": 3_000,
    "services/web_sync/order_created.py": 30_000,
    "services/web_sync/cs_review.py": 25_000,
    "services/web_sync/self_service_bridge.py": 12_000,
    "services/self_service_reorder.py": 33_000,
    "services/self_service_selection_runtime.py": 30_000,
    "services/self_service_financials.py": 42_000,
    "web/app/main.py": 18_500,
    "web/app/routers/admin.py": 14_000,
    "web/app/routers/admin_dashboard.py": 29_000,
    "web/app/routers/admin_order_workspace.py": 47_000,
    "web/app/services/admin_order_workspace_data.py": 21_000,
    "views/review.py": 50_000,
    "services/review_storage.py": 25_000,
    "services/worker_tips.py": 11_000,
    "views/worker_tips.py": 25_000,
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


def test_runtime_configurators_do_not_receive_entrypoint_globals() -> None:
    pattern = re.compile(
        r"configure_[A-Za-z0-9_]*runtime\s*\(\s*globals\s*\(\s*\)\s*\)"
    )
    offenders: list[str] = []
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        if relative.parts and relative.parts[0] == "tests":
            continue
        source = path.read_text(encoding="utf-8")
        if pattern.search(source):
            offenders.append(str(relative))

    assert not offenders, (
        "runtime configuration must use explicit dependencies, not globals(): "
        + ", ".join(offenders)
    )
