from __future__ import annotations

import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "views" / "review.py"
STORE = ROOT / "services" / "review_storage.py"


def test_review_sql_is_canonical_in_storage_service():
    view = VIEW.read_text(encoding="utf-8")
    store = STORE.read_text(encoding="utf-8")

    assert "from services.review_storage import (" in view
    assert "conn.execute(" not in view
    assert "CREATE TABLE IF NOT EXISTS order_reviews" not in view
    assert "CREATE TABLE IF NOT EXISTS staff_favorites" not in view

    for fragment in (
        "CREATE TABLE IF NOT EXISTS order_reviews",
        "CREATE TABLE IF NOT EXISTS order_review_skips",
        "CREATE TABLE IF NOT EXISTS staff_favorites",
        "INSERT INTO order_reviews",
        "INSERT OR IGNORE INTO staff_favorites",
    ):
        assert fragment in store


def test_review_storage_exports_existing_view_contracts():
    module = importlib.import_module("services.review_storage")
    for name in (
        "ensure_review_tables",
        "get_review_targets",
        "build_review_status",
        "record_review_skip",
        "record_member_review",
        "get_staff_favorites",
        "get_post_close_status",
        "add_staff_favorite",
    ):
        assert callable(getattr(module, name))


def test_review_view_keeps_discord_orchestration_not_storage():
    source = VIEW.read_text(encoding="utf-8")
    for fragment in (
        "class ReviewDraftConfirmView",
        "class MemberReviewModal",
        "async def refresh_post_close_panel",
        "def build_post_close_status_embed",
    ):
        assert fragment in source


def test_review_storage_has_no_view_or_bot_dependency():
    source = STORE.read_text(encoding="utf-8")
    assert "import bot" not in source
    assert "from bot import" not in source
    assert "from views" not in source
