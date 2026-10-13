from __future__ import annotations

import importlib
from pathlib import Path


def test_payment_review_runtime_uses_canonical_worker_tip_service():
    source = Path("services/payment_review_runtime.py").read_text(encoding="utf-8")
    assert "from services.worker_tips import (" in source
    assert "mark_worker_tip_cancelled" in source
    assert "mark_worker_tip_paid" in source
    assert "_worker_tip_row" not in source
    assert "from views.review import refresh_post_close_panel" in source


def test_payment_review_runtime_import_smoke():
    module = importlib.import_module("services.payment_review_runtime")
    assert callable(module.ensure_payment_review_worker_started)
