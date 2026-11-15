"""Owner-approved live Discord messages must survive routine deployments.

A green deployment only proves processes restart; this regression check protects
against a separate class of failure: startup handlers re-publishing a stale
built-in text/embed over an owner-edited message.
"""

from __future__ import annotations

import ast
from pathlib import Path

from services import quick_order_v2 as quick
from services.quick_order_v2_price_lists import (
    DELTA_PRICE_LIST_CATEGORIES,
    has_price_list,
)
from services.quick_order_v2_production import _public_view_for_channel
from views.panels import MainPanelView


ROOT = Path(__file__).resolve().parents[1]


def _async_function(path: str, name: str, *, inside: str | None = None) -> str:
    source = (ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    members = tree.body
    if inside:
        klass = next(
            node for node in members
            if isinstance(node, ast.ClassDef) and node.name == inside
        )
        members = klass.body
    func = next(
        node for node in members
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name
    )
    return ast.get_source_segment(source, func) or ""


def test_service_lobby_restart_is_read_only_and_persistent_buttons_still_registered():
    refresh = _async_function("bot.py", "refresh_main_service_panel")
    bot_source = (ROOT / "bot.py").read_text(encoding="utf-8")

    assert "fetch_message(" in refresh
    assert "message.edit(" not in refresh
    assert ".send(" not in refresh
    assert "live panel differs from source template" in refresh
    assert "preserving the existing Discord copy" in refresh
    assert "bot.add_view(MainPanelView())" in bot_source
    assert "await refresh_main_service_panel()" in bot_source

    # This is the existing service lobby, not the public Quick Order panel.
    view = MainPanelView()
    assert {child.custom_id for child in view.children} == {
        "mawan_main_panel_support_call_v1",
        "mawan_main_panel_recruit_button",
        "mawan_main_panel_complaint_button",
        "mawan_main_panel_feedback_button",
    }


def test_member_portal_does_not_clobber_approved_embed_or_components_on_restart():
    sync = _async_function(
        "cogs/setup_commands.py",
        "_sync_member_portal_panel",
        inside="SetupCommands",
    )
    source = (ROOT / "cogs/setup_commands.py").read_text(encoding="utf-8")
    assert "target_message.edit(" not in sync
    assert "await target_message.edit(" not in sync
    assert "target_message = await channel.send(" in sync
    assert 'action = "preserved"' in sync
    assert "bot.add_view(MemberPortalView())" in source


def test_historical_welcome_copy_is_not_migrated_during_ordinary_bot_restarts():
    welcome = _async_function("bot.py", "refresh_welcome_history")
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    assert "message.edit(" not in welcome
    assert ".history(" not in welcome
    assert "automatic rewrite disabled" in welcome
    # Future new-member posts retain their normal code-owned greeting.
    assert "build_welcome_embed(" in source


def test_last_deployed_price_button_and_fun_order_approvals_still_hold():
    # Do not reinstate the four game price buttons while changing other views.
    for game in ("valorant", "lol", "apex", "steam"):
        channel_id = int(quick.QUICK_ORDER_V2_CHANNELS[game])
        assert has_price_list(channel_id) is False
        entry_view = _public_view_for_channel(channel_id)
        assert len(entry_view.children) == 1
        assert all(
            "price_list" not in str(getattr(child, "custom_id", ""))
            for child in entry_view.children
        )

    assert [code for code, _label, _emoji in DELTA_PRICE_LIST_CATEGORIES] == [
        "desktop",
        "mobile",
        "fun",
    ]
    delta = _public_view_for_channel(quick.QUICK_ORDER_V2_CHANNELS["delta"])
    assert any("price_list" in str(child.custom_id) for child in delta.children)

    from services import order_rules
    from services.orders import SELF_SERVICE_ORDER_CATALOG

    for group in SELF_SERVICE_ORDER_CATALOG["delta_desktop_fun"]:
        for detail in group["details"]:
            key = str(detail["rule_key"])
            rule = order_rules.ORDER_RULES[key]
            assert rule.allow_specify is True, key
            assert rule.specify_fee_default == 0, key
            assert all(fee == 0 for fee in rule.specify_fee_by_role.values()), key

    # No accidental reduction back to male-only protectors.
    for rule_key in ("fun_our_love_start_50", "fun_our_love_start_0"):
        assert set(order_rules.ORDER_RULES[rule_key].allowed_roles) == {
            "male_protector",
            "female_protector",
            "top_protector",
        }
