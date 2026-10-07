from pathlib import Path

from services.web_sync import runtime as web_sync_runtime


ROOT = Path(__file__).resolve().parents[1]


def test_bot_web_database_path_points_to_repository_root():
    assert Path(web_sync_runtime._web_dashboard_db_path_for_bot()).resolve() == (
        ROOT / "web_dashboard.db"
    ).resolve()


def test_final_web_orders_do_not_recreate_bot_claims():
    source = (ROOT / "bot.py").read_text(encoding="utf-8")

    assert "startup removed final Web-order claims" in source
    assert "WHERE status IN ('closed', 'cancelled')" in source
    assert "final-order claim cleaned" in source
    assert "delete_claim_row_from_db(message_id=final_message_id)" in source
    assert "await _refresh_existing_web_sync_dispatch(event)" in source
