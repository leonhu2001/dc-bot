from pathlib import Path

from services.review_persistent_runtime import restore_persistent_review_views


class _FakeBot:
    def __init__(self):
        self.views = []

    def add_view(self, view, *, message_id=None):
        self.views.append((view, message_id))


class _FakeView:
    def __init__(self, *, customer_id, order_content=None):
        self.customer_id = customer_id
        self.order_content = order_content


def test_restore_persistent_review_views_only_restores_saved_closed_panels():
    bot = _FakeBot()
    orders = {
        10: {
            "status": "closed",
            "customer_id": 100,
            "post_close_panel_message_id": 1000,
        },
        11: {
            "status": "active",
            "customer_id": 101,
            "post_close_panel_message_id": 1001,
        },
        12: {
            "closed": True,
            "customer_id": 102,
        },
    }

    restored = restore_persistent_review_views(
        bot,
        orders,
        _FakeView,
        lambda channel_id: (f"order-{channel_id}", "wallet"),
    )

    assert restored == 1
    assert len(bot.views) == 1
    view, message_id = bot.views[0]
    assert message_id == 1000
    assert view.customer_id == 100
    assert view.order_content == "order-10"


def test_review_button_view_is_persistent():
    source = (Path(__file__).resolve().parents[1] / "views" / "review.py").read_text(
        encoding="utf-8"
    )
    class_source = source.split("class ReviewButtonView", 1)[1]
    assert "super().__init__(timeout=None)" in class_source
    for custom_id in (
        "review_leave_button",
        "review_worker_tip_button",
        "review_skip_button",
        "review_favorite_members_button",
        "review_reorder_button",
        "review_close_ticket_button",
    ):
        assert f'custom_id="{custom_id}"' in class_source
