from __future__ import annotations

import subprocess
import sys
import textwrap


def test_vip_timer_quick_order_builds_private_ticket_for_current_and_legacy_game_labels():
    # Run in a new interpreter: global installer patches are intentionally
    # idempotent and must be exercised in a clean app-like environment.
    script = textwrap.dedent(
        '''
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from services import (
            order_runtime,
            quick_order_v2 as quick,
            quick_order_v2_fixes as fixes,
            quick_order_v2_production as prod,
            self_service_ui_runtime as ui,
            self_service_selection_state as state,
            vip_timer_self_service as timer,
            vip_timer_catalog_guard as guard,
            vip_timer_select_flow as flow,
            vip_timer_selector_order_v2 as v2,
            vip_timer_selector_order_v3 as v3,
            vip_timer_selector_order_v4 as v4,
            vip_timer_policy_v5 as v5,
        )
        from services.order_runtime import _OrderRuntimeState
        from services.vip_timer import VIP_TIMER_CATEGORY

        drafts = {}
        def no_op(*args, **kwargs):
            return None

        order_runtime._RUNTIME_STATE = _OrderRuntimeState(
            db_file=None,
            dispatch_channel_id=0,
            order_control_selections={},
            order_selections=drafts,
            self_service_order_view_type=ui.SelfServiceOrderView,
            defer_and_refresh_self_service_panel=no_op,
            self_service_rule_getter=no_op,
            payment_method_embed_builder=no_op,
            self_service_panel_embed_builder=ui.build_self_service_panel_embed,
            can_operate_self_service_order=no_op,
            amount_formatter=no_op,
            order_customer_id_getter=no_op,
            wallet_balance_getter=no_op,
            customer_staff_checker=no_op,
            remember_order=no_op,
            ticket_channel_renamer=no_op,
            order_log_sender=no_op,
        )
        ui.SELF_SERVICE_ORDER_SELECTIONS = drafts

        timer.install_vip_timer_self_service()
        guard.install_vip_timer_catalog_guard()
        flow.install_vip_timer_select_flow()
        v2.install_vip_timer_selector_order_v2()
        v3.install_vip_timer_selector_order_v3()
        v4.install_vip_timer_selector_order_v4()
        v5.install_vip_timer_policy_v5()
        fixes.install_quick_order_v2_fixes(SimpleNamespace())
        prod.install_quick_order_v2_production(SimpleNamespace())

        quick.assert_vip_timer_self_service_eligible = no_op
        quick.remember_order_data = no_op
        quick.format_customer_notes_for_ticket = lambda x: ""
        quick._build_order_control_view = lambda: None

        class FakeMember:
            id = 777
            mention = "<@777>"
            def __str__(self):
                return "customer"

        class FakeCategory:
            pass

        class FakeChannel:
            id = 888
            mention = "<#888>"
            def __init__(self):
                self.sent = []
                self.delete = AsyncMock()
            async def send(self, *args, **kwargs):
                self.sent.append((args, kwargs))
                return SimpleNamespace(id=999)

        class FakeGuild:
            default_role = SimpleNamespace()
            me = None
            def __init__(self):
                self.channels = []
            def get_channel(self, channel_id):
                return FakeCategory()
            def get_role(self, role_id):
                return None
            async def create_text_channel(self, **kwargs):
                channel = FakeChannel()
                self.channels.append(channel)
                return channel

        quick.discord.Member = FakeMember
        quick.discord.CategoryChannel = FakeCategory

        async def run(label):
            guild = FakeGuild()
            interaction = SimpleNamespace(
                guild=guild,
                user=FakeMember(),
                response=SimpleNamespace(defer=AsyncMock(),send_message=AsyncMock()),
                edit_original_response=AsyncMock(),
            )
            ticket = await quick._create_ticket(
                interaction,
                category=VIP_TIMER_CATEGORY,
                item_group=label,
                source_channel_id=quick.QUICK_ORDER_V2_CHANNELS["vip_timer"],
            )
            if ticket is None:
                print("FAILED LABEL", repr(label), "RESPONSE", interaction.edit_original_response.await_args_list)
            assert ticket is not None, f"ticket not created for {label}"
            assert len(ticket.sent) == 2
            assert not ticket.delete.await_count

        async def main():
            from services import orders
            timer.refresh_vip_timer_self_service_catalog()
            groups = [g["label"] for g in orders.SELF_SERVICE_ORDER_CATALOG[VIP_TIMER_CATEGORY]]
            assert groups
            await run(groups[0])
            # Historic panel value should be accepted without a generic ValueError.
            await run("三角洲行動｜端遊")

        asyncio.run(main())
        '''
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=80,
    )
    assert result.returncode == 0, (
        f"VIP timer ticket smoke failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
