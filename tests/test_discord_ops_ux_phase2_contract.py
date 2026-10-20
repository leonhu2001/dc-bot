from pathlib import Path


def test_phase2_does_not_move_acceptance_decision_into_presentation():
    presentation = Path("services/acceptance/error_presentation.py").read_text(encoding="utf-8")
    assert "claim_acceptance_order" not in presentation
    assert "transition_order_state" not in presentation


def test_cs_review_alert_is_guarded_by_existing_footer_dedupe():
    source = Path("services/web_sync/cs_review.py").read_text(encoding="utf-8")
    dedupe = source.index("if await _web_order_created_has_footer")
    alert = source.index("build_cs_review_alert_text(")
    assert dedupe < alert
