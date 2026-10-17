from pathlib import Path

from web.app.services.worker_bonus_payout import _effective_stream_bonus


ROOT = Path(__file__).resolve().parents[1]


def test_effective_stream_bonus_follows_report_until_admin_override():
    assert _effective_stream_bonus(legacy=False, report_streamed=True, override=None) is True
    assert _effective_stream_bonus(legacy=False, report_streamed=False, override=None) is False
    assert _effective_stream_bonus(legacy=False, report_streamed=True, override=False) is False
    assert _effective_stream_bonus(legacy=False, report_streamed=False, override=True) is True


def test_legacy_orders_never_gain_stream_bonus_from_override():
    assert _effective_stream_bonus(legacy=True, report_streamed=True, override=True) is False


def test_stream_bonus_override_is_additive_and_workspace_controlled():
    model = (ROOT / "shared/models.py").read_text(encoding="utf-8")
    schema = (ROOT / "shared/db.py").read_text(encoding="utf-8")
    service = (ROOT / "web/app/services/admin_service.py").read_text(encoding="utf-8")
    router = (ROOT / "web/app/routers/admin_order_workspace.py").read_text(encoding="utf-8")
    template = (ROOT / "web/app/templates/admin_order_detail.html").read_text(encoding="utf-8")

    assert "stream_bonus_override: Mapped[bool | None]" in model
    assert "ADD COLUMN stream_bonus_override INTEGER" in schema
    assert "toggle_stream_bonus_for_assignment" in service
    assert "直播加成只能在報單審核通過後修正" in service
    assert "/stream-bonus" in router
    assert "管理端修正直播（新制 +2%）" in template


def test_payout_engine_reads_override_without_mutating_report_rows():
    source = (ROOT / "web/app/services/worker_bonus_payout.py").read_text(encoding="utf-8")
    assert "_assignment_stream_override_map" in source
    assert "OrderAssignment.stream_bonus_override.is_not(None)" in source
    assert "UPDATE order_report_workers" not in source
