from pathlib import Path

runtime_path = Path("services/self_service_runtime.py")
text = runtime_path.read_text(encoding="utf-8")

# Import the cohesive retract lifecycle and its persistent post-submit view.
import_anchor = "from services.smart_dispatch import create_smart_dispatch_plan, set_specified_dm_results\n"
import_line = (
    "from services.self_service_retract import (\n"
    "    SelfServiceDispatchedView,\n"
    "    retract_self_service_dispatch,\n"
    ")\n"
)
old_import_line = "from services.self_service_retract import retract_self_service_dispatch\n"
if old_import_line in text:
    text = text.replace(old_import_line, import_line, 1)
elif import_line not in text:
    if import_anchor not in text:
        raise SystemExit("smart dispatch import anchor missing")
    text = text.replace(import_anchor, import_anchor + import_line, 1)

# The view now owns its permission checks, so the legacy runtime only needs the
# permission helper it already used elsewhere.
text = text.replace(
    "from core.permissions import is_customer_staff, is_manager_or_admin\n",
    "from core.permissions import is_customer_staff\n",
    1,
)
text = text.replace('        "is_manager_or_admin",\n', "", 1)

owned_anchor = '        "set_specified_dm_results",\n'
for owned_name in ("retract_self_service_dispatch", "SelfServiceDispatchedView"):
    entry = f'        "{owned_name}",\n'
    if entry not in text:
        if owned_anchor not in text:
            raise SystemExit("module owned anchor missing")
        text = text.replace(owned_anchor, owned_anchor + entry, 1)

# Replace the large lifecycle implementation with a narrow adapter that passes
# the remaining runtime-owned stores/adapters explicitly.
start_marker = "async def retract_waiting_acceptance_order_from_self_service(\n"
end_marker = "PRICE_FORMULA_VERSION = 2\n"
start = text.find(start_marker)
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit(f"retract function markers missing start={start} end={end}")

wrapper = '''async def retract_waiting_acceptance_order_from_self_service(
    interaction: discord.Interaction,
    *,
    channel_id: int,
) -> str:
    """Adapter from the legacy self-service runtime into the retract lifecycle."""
    return await retract_self_service_dispatch(
        interaction,
        channel_id=channel_id,
        order_selections=SELF_SERVICE_ORDER_SELECTIONS,
        order_claims=ORDER_CLAIMS,
        dispatch_channel_id=DISPATCH_CHANNEL_ID,
        remember_order=remember_order_data,
        save_data=save_bot_data,
        delete_claim_row=delete_claim_row_from_db,
        order_log_sender=send_order_log,
        now_iso=get_taipei_now_iso,
    )


'''
text = text[:start] + wrapper + text[end:]

# Move the post-submit retract button view beside the retract lifecycle. This is
# a concrete feature boundary, not a broad refactor of the self-service runtime.
view_start_marker = "class SelfServiceDispatchedView(discord.ui.View):\n"
view_end_marker = "class SelfServiceOrderView(discord.ui.View):\n"
view_start = text.find(view_start_marker)
view_end = text.find(view_end_marker, view_start)
if view_start < 0 or view_end < 0:
    raise SystemExit(f"dispatched view markers missing start={view_start} end={view_end}")
text = text[:view_start] + text[view_end:]
runtime_path.write_text(text, encoding="utf-8")

retract_path = Path("services/self_service_retract.py")
retract = retract_path.read_text(encoding="utf-8")
permission_import = "from core.permissions import is_customer_staff, is_manager_or_admin\n"
if permission_import not in retract:
    retract = retract.replace(
        "import discord\n\nfrom services.orders import _to_int\n",
        "import discord\n\n"
        "from core.permissions import is_customer_staff, is_manager_or_admin\n"
        "from services.orders import _to_int\n",
        1,
    )

view_code = r'''


class SelfServiceDispatchedView(discord.ui.View):
    """送出後只保留撤回操作；固定 custom_id 讓重啟後仍可操作。"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="撤回派單",
        style=discord.ButtonStyle.danger,
        custom_id="self_service_retract_dispatch_button",
    )
    async def retract_dispatch(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if (
            not isinstance(interaction.user, discord.Member)
            or not (
                is_customer_staff(interaction.user)
                or is_manager_or_admin(interaction.user)
            )
        ):
            await interaction.response.send_message(
                "只有客服、店長或管理員可以撤回派單。",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message(
                "無法確認目前票口頻道。",
                ephemeral=True,
            )
            return

        # Lazy import avoids a module cycle while keeping the legacy runtime's
        # state stores as the single source of truth until that boundary is retired.
        from services import self_service_runtime as runtime

        channel_id = int(interaction.channel.id)
        data = runtime.SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        customer_id = _to_int(data.get("customer_id"), None)

        if customer_id is None:
            await interaction.response.send_message(
                "找不到這張票口的顧客資料。",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            response_text = await retract_self_service_dispatch(
                interaction,
                channel_id=channel_id,
                order_selections=runtime.SELF_SERVICE_ORDER_SELECTIONS,
                order_claims=runtime.ORDER_CLAIMS,
                dispatch_channel_id=runtime.DISPATCH_CHANNEL_ID,
                remember_order=runtime.remember_order_data,
                save_data=runtime.save_bot_data,
                delete_claim_row=runtime.delete_claim_row_from_db,
                order_log_sender=runtime.send_order_log,
                now_iso=runtime.get_taipei_now_iso,
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception as exc:
            print(
                f"[dispatch-retract] failed channel_id={channel_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            await interaction.followup.send(
                "撤回派單失敗，原訂單已鎖住付款；請再按一次撤回，"
                "若仍失敗請通知客服主管查看後台紀錄。",
                ephemeral=True,
            )
            return

        panel_refreshed = False
        if interaction.message is not None:
            try:
                updated_data = runtime.SELF_SERVICE_ORDER_SELECTIONS.get(
                    channel_id,
                    {},
                )
                await interaction.message.edit(
                    embed=runtime.build_self_service_panel_embed(
                        customer_id,
                        updated_data,
                        interaction.guild,
                    ),
                    view=runtime.SelfServiceOrderView(
                        customer_id=customer_id,
                        channel_id=channel_id,
                        selected_category=updated_data.get("category"),
                    ),
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
                panel_refreshed = True
            except discord.HTTPException:
                panel_refreshed = False

        if not panel_refreshed:
            response_text += (
                "\n⚠️ 自助下單 Panel 未能自動刷新，"
                "請重新開啟票口 Panel 後再修改。"
            )

        await interaction.followup.send(response_text, ephemeral=True)
'''

if "class SelfServiceDispatchedView(discord.ui.View):" not in retract:
    retract += view_code
retract_path.write_text(retract, encoding="utf-8")
