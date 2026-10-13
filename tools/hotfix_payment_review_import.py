from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "services" / "payment_review_runtime.py"
TEST = ROOT / "tests" / "test_payment_review_runtime_import_boundary.py"

source = RUNTIME.read_text(encoding="utf-8")
old = '''from views.review import (
    _worker_tip_row,
    mark_worker_tip_cancelled,
    mark_worker_tip_paid,
    refresh_post_close_panel,
)
'''
new = '''from services.worker_tips import (
    mark_worker_tip_cancelled,
    mark_worker_tip_paid,
)
from views.review import refresh_post_close_panel
'''
if old not in source:
    raise RuntimeError("stale payment-review worker-tip import block not found")
source = source.replace(old, new, 1)
RUNTIME.write_text(source, encoding="utf-8")

TEST.write_text(
    '''from __future__ import annotations

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
''',
    encoding="utf-8",
)
print("payment review worker-tip import boundary repaired")
