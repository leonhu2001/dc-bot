from __future__ import annotations

import ast
from pathlib import Path

from services import quick_order_v2 as quick
from services import quick_order_v2_price_lists as price_lists
from services import quick_order_v2_production as production
from services.order_rules import (
    ORDER_RULES,
    PROTECTOR_ROLES,
    ROLE_IDS,
    get_base_rule,
    get_required_staff_count,
)
from views.panels import MainPanelView


ROOT = Path(__file__).resolve().parents[1]


def _function_ast(module: str, name: str):
    src = (ROOT / module).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=module)
    return next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    )


def test_startup_service_lobby_is_read_only_and_persistent_buttons_are_registered():
    panel = _function_ast("bot.py", "refresh_main_service_panel")
    calls = [
        ast.unparse(node.func)
        for node in ast.walk(panel)
        if isinstance(node, ast.Call)
    ]
    assert "channel.fetch_message" in calls
    assert "message.edit" not in calls
    assert "message.delete" not in calls
    assert "channel.send" not in calls
    assert "build_main_panel_embed" not in calls

    src = (ROOT / "bot.py").read_text(encoding="utf-8")
    assert "bot.add_view(MainPanelView())" in src
    assert "await refresh_main_service_panel()" in src


def test_main_lobby_public_button_ids_are_stable_without_reposting():
    view = MainPanelView()
    ids = [str(getattr(item, "custom_id", "") or "") for item in view.children]
    assert ids == [
        "mawan_main_panel_support_call_v1",
        "mawan_main_panel_recruit_button",
        "mawan_main_panel_complaint_button",
        "mawan_main_panel_feedback_button",
    ]


def test_welcome_history_is_not_auto_rewritten_on_deployment():
    on_ready = _function_ast("bot.py", "on_ready")
    calls = [
        ast.unparse(node.func)
        for node in ast.walk(on_ready)
        if isinstance(node, ast.Call)
    ]
    assert "refresh_welcome_history" not in calls
    assert "_refresh_welcome_history_background" not in calls
    assert "bot.loop.create_task(_refresh_welcome_history_background())" not in (
        ROOT / "bot.py"
    ).read_text(encoding="utf-8").split(
        "@bot.event\nasync def on_ready():", 1
    )[1].split("# ========= Slash 指令 =========", 1)[0]
    assert "build_welcome_embed(" in (
        ROOT / "bot.py"
    ).read_text(encoding="utf-8")


def test_latest_owner_approved_public_game_panel_removals_still_hold():
    assert price_lists.DELTA_PRICE_LIST_CATEGORIES == (
        ("desktop", "端遊", "🖥️"),
        ("mobile", "手遊", "📱"),
        ("fun", "趣味單", "🎉"),
    )
    assert price_lists.has_price_list(quick.QUICK_ORDER_V2_CHANNELS["delta"])
    for game in ("valorant", "lol", "apex", "steam"):
        channel = quick.QUICK_ORDER_V2_CHANNELS[game]
        assert not price_lists.has_price_list(channel)
        ids = [
            getattr(item, "custom_id", None)
            for item in production._public_view_for_channel(channel).children
        ]
        assert len(ids) == 1
        assert "price_list" not in str(ids[0])
    # Delta farm orders exist; only their price-list category was removed.
    assert any(category == "farm" for _, _, category, _ in quick._DELTA_BUTTONS)


def test_latest_owner_approved_fun_free_specify_and_our_love_roles_still_hold():
    from services.orders import SELF_SERVICE_ORDER_CATALOG

    keys = {
        detail["rule_key"]
        for group in SELF_SERVICE_ORDER_CATALOG["delta_desktop_fun"]
        for detail in group["details"]
    }
    assert keys
    for key in keys:
        rule = ORDER_RULES[key]
        assert rule.allow_specify
        assert rule.specify_fee_default == 0
        assert rule.max_specified_count == get_required_staff_count(rule)

    for key in ("fun_our_love_start_50", "fun_our_love_start_0"):
        rule = get_base_rule(key)
        assert rule.allowed_roles == PROTECTOR_ROLES
        assert get_required_staff_count(rule) == 2
