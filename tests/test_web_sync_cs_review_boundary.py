import inspect
from pathlib import Path

from services.web_sync import cs_review
from services.web_sync import runtime as web_sync_runtime


EXPECTED_CS_REVIEW_DEPENDENCIES = {
    "order_selections",
    "ensure_dispatch",
    "seed_state",
}


def test_web_sync_cs_review_uses_explicit_dependencies():
    signature = inspect.signature(cs_review.configure_web_sync_cs_review)
    assert set(signature.parameters) == EXPECTED_CS_REVIEW_DEPENDENCIES
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )


def test_cs_review_gate_is_physically_extracted():
    runtime_source = Path("services/web_sync/runtime.py").read_text(
        encoding="utf-8"
    )
    cs_source = Path("services/web_sync/cs_review.py").read_text(
        encoding="utf-8"
    )

    for definition in (
        "def _web_cs_order_id_from_channel",
        "def _web_cs_set_status",
        "async def _web_cs_ensure_review_panel",
        "class WebsiteOrderCsConfirmView",
        "class WebsitePendingCancelConfirmView",
    ):
        assert definition not in runtime_source
        assert definition in cs_source

    assert "import bot" not in cs_source
    assert "from bot import" not in cs_source
    assert "globals()" not in cs_source
    assert web_sync_runtime.WebsiteOrderCsConfirmView is cs_review.WebsiteOrderCsConfirmView
    assert (
        web_sync_runtime.WebsitePendingCancelConfirmView
        is cs_review.WebsitePendingCancelConfirmView
    )
    assert (
        web_sync_runtime._web_cs_ensure_review_panel
        is cs_review._web_cs_ensure_review_panel
    )
