from pathlib import Path


BOT_SOURCE = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")


def test_migrated_runtimes_use_explicit_startup_wiring():
    assert "configure_acceptance_runtime(globals())" not in BOT_SOURCE
    assert "configure_order_lifecycle_runtime(globals())" not in BOT_SOURCE
    assert "configure_self_service_runtime(globals())" not in BOT_SOURCE

    assert "configure_acceptance_runtime_explicit(" in BOT_SOURCE
    assert "configure_order_lifecycle_runtime_explicit(" in BOT_SOURCE
    assert "configure_self_service_runtime_explicit(" in BOT_SOURCE


def test_unmigrated_runtime_bridges_remain_scoped_for_this_pr():
    assert "configure_web_sync_runtime(globals())" in BOT_SOURCE
    assert "configure_order_runtime(globals())" in BOT_SOURCE


def test_explicit_runtime_wiring_names_key_bot_owned_dependencies():
    expected_fragments = (
        "dispatch_channel_id=DISPATCH_CHANNEL_ID",
        "order_claims=ORDER_CLAIMS",
        "payment_method_view_type=PaymentMethodView",
        "order_selections=SELF_SERVICE_ORDER_SELECTIONS",
        "bot_instance=bot",
        "guild_id=GUILD_ID",
        "refresh_existing_web_sync_dispatch=_refresh_existing_web_sync_dispatch",
        "receipt_channel_id=RECEIPT_CHANNEL_ID",
        "sync_web_order_closed=sync_web_order_closed_from_bot",
        "sync_web_order_cancelled=sync_web_order_cancelled_from_bot",
        "customer_category_id=CUSTOMER_CATEGORY_ID",
        "customer_role_id=CUSTOMER_ROLE_ID",
        "point_redeem_items=POINT_REDEEM_ITEMS",
        "point_redeem_items_by_key=POINT_REDEEM_ITEMS_BY_KEY",
        "order_control_view_type=OrderControlView",
    )

    for fragment in expected_fragments:
        assert fragment in BOT_SOURCE
