from pathlib import Path


def test_worker_tip_persistence_has_single_canonical_owner():
    review = Path("views/review.py").read_text(encoding="utf-8")
    service = Path("services/worker_tips.py").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS worker_tips" not in review
    assert "CREATE TABLE IF NOT EXISTS worker_tips" in service
    assert "def create_worker_tip" not in review
    assert "def create_worker_tip" in service
    assert "def mark_worker_tip_paid" not in review
    assert "def mark_worker_tip_paid" in service


def test_worker_tip_discord_ui_is_not_implemented_in_review_module():
    review = Path("views/review.py").read_text(encoding="utf-8")
    tip_views = Path("views/worker_tips.py").read_text(encoding="utf-8")

    assert "class WorkerTipPaymentMethodSelect" not in review
    assert "class WorkerTipPaymentConfirmView" not in review
    assert "class WorkerTipPaymentMethodSelect" in tip_views
    assert "class WorkerTipPaymentConfirmView" in tip_views
    assert "def configure_worker_tip_views" in tip_views
    assert "from views.review import" not in tip_views


def test_review_composes_worker_tips_through_explicit_callbacks():
    review = Path("views/review.py").read_text(encoding="utf-8")
    assert "configure_worker_tip_views(" in review
    assert "review_target_getter=get_review_targets" in review
    assert "refresh_post_close_handler=refresh_post_close_panel" in review
