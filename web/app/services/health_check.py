from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from shared.db import SessionLocal


REQUIRED_PUBLIC_ASSETS = (
    "js/mw_order_ui.js",
    "css/order_ui.css",
)


def check_runtime_dependencies(static_dir: Path) -> dict[str, bool]:
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1")).scalar_one()
    finally:
        db.close()

    missing_assets = [
        relative_path
        for relative_path in REQUIRED_PUBLIC_ASSETS
        if not (static_dir / relative_path).is_file()
    ]
    if missing_assets:
        raise RuntimeError(
            "required public assets missing: " + ", ".join(missing_assets)
        )

    return {
        "database": True,
        "public_assets": True,
    }
