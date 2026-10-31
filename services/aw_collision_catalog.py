from __future__ import annotations

from typing import Any

import discord

from services.order_rules import AW_COLLISION_PRICING_BY_RULE


AW_GROUP_LABEL = "AW代撞"
AW_RULE_KEYS = tuple(AW_COLLISION_PRICING_BY_RULE)
CREDENTIAL_NOTE_PLACEHOLDER = (
    "例如 Steam、Garena、Google 登入、其他登入注意事項；請補充安全箱格數"
)
AW_COLLISION_PLANS: dict[str, dict[str, Any]] = {key: dict(plan) for key, plan in AW_COLLISION_PRICING_BY_RULE.items()}

_INSTALLED = False
_ORIGINAL_QUANTITY_SELECT = None
_ORIGINAL_WAITING_ORDER_CREATOR = None
_ORIGINAL_PANEL_BUILDER = None


def is_aw_collision_rule(rule_key: str | None) -> bool:
    return str(rule_key or "").strip() in AW_COLLISION_PLANS


def aw_collision_plan(rule_key: str | None) -> dict[str, Any] | None:
    return AW_COLLISION_PLANS.get(str(rule_key or "").strip())


def validate_aw_quantity_for_rule(rule_key: str | None, quantity: int) -> dict[str, Any]:
    plan = aw_collision_plan(rule_key)
    if plan is None:
        raise ValueError("目前選擇的 AW 代撞方案已失效，請重新選擇。")

    try:
        value = int(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("發數請輸入整數。") from exc

    minimum = int(plan["min"])
    maximum = int(plan["max"])
    if value < minimum or value > maximum:
        range_text = (
            f"{minimum}～{maximum} 發"
            if maximum < 999999
            else f"{minimum} 發以上"
        )
        raise ValueError(
            f"你目前選的是「{plan['label']}」，但填了 {value} 發。"
            f"此方案只能填 {range_text}；請改發數，或回第三欄更換方案。"
        )
    return plan


def aw_collision_original_amount(rule_key: str | None, quantity: int) -> int:
    plan = validate_aw_quantity_for_rule(rule_key, quantity)
    value = int(quantity)
    # 系統金額以整數 T 記錄。4.5T/發若總額出現 0.5T，向上進位 1T，
    # 避免因整數帳務格式而少收半 T。
    return (value * int(plan["rate_x2"]) + 1) // 2


def _extend_product_dependent_state() -> None:
    from services import self_service_selection_state as selection

    extra_keys = (
        "aw_collision_quantity_confirmed",
        "aw_collision_plan_key",
        "aw_collision_unit_rate",
        "aw_collision_quantity_set_by",
    )
    current = tuple(getattr(selection, "_PRODUCT_DEPENDENT_KEYS", ()))
    selection._PRODUCT_DEPENDENT_KEYS = current + tuple(
        key for key in extra_keys if key not in current
    )


class AwCollisionQuantityModal(discord.ui.Modal, title="填寫 AW 代撞發數"):
    quantity = discord.ui.TextInput(
        label="發數",
        placeholder="例如：80、250、600",
        required=True,
        max_length=6,
    )

    def __init__(
        self,
        customer_id: int,
        channel_id: int,
        panel_message_id: int | None = None,
    ):
        super().__init__()
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)
        self.panel_message_id = panel_message_id

    async def on_submit(self, interaction: discord.Interaction):
        from services import order_runtime

        state = order_runtime._require_runtime_state()
        if not state.can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message(
                "只有開這張票口的用戶或客服可以填寫發數。",
                ephemeral=True,
            )
            return

        data = state.order_selections.setdefault(self.channel_id, {})
        rule_key = str(data.get("order_rule_key") or "")
        if not is_aw_collision_rule(rule_key):
            await interaction.response.send_message(
                "目前已不是 AW 代撞方案，請重新選擇品項。",
                ephemeral=True,
            )
            return

        raw = str(self.quantity.value or "").strip().replace(",", "")
        try:
            value = int(raw)
        except ValueError:
            await interaction.response.send_message("發數請輸入整數，例如 250。", ephemeral=True)
            return

        try:
            plan = validate_aw_quantity_for_rule(rule_key, value)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        data["quantity"] = value
        data["aw_collision_quantity_confirmed"] = True
        data["aw_collision_plan_key"] = rule_key
        data["aw_collision_unit_rate"] = str(plan["rate_text"])
        data["aw_collision_quantity_set_by"] = int(interaction.user.id)
        data.pop("payment_method", None)
        state.remember_order(self.channel_id, data)

        original_amount = aw_collision_original_amount(rule_key, value)
        rounding_note = ""
        if int(plan["rate_x2"]) % 2 and value % 2:
            rounding_note = "\n※ 原始計算有 0.5T，系統以整數 T 結算，已向上進位 1T。"

        await interaction.response.defer(ephemeral=True)
        if isinstance(interaction.channel, discord.TextChannel) and self.panel_message_id:
            try:
                panel_message = await interaction.channel.fetch_message(self.panel_message_id)
                await panel_message.edit(
                    embed=state.self_service_panel_embed_builder(
                        self.customer_id,
                        data,
                        interaction.guild,
                    ),
                    view=state.self_service_order_view_type(
                        customer_id=self.customer_id,
                        channel_id=self.channel_id,
                        selected_category=data.get("category"),
                    ),
                    allowed_mentions=discord.AllowedMentions(
                        users=False,
                        roles=False,
                        everyone=False,
                    ),
                )
            except discord.HTTPException:
                pass

        await interaction.followup.send(
            f"已填寫 **{value} 發**。\n"
            f"套用方案：**{plan['label']}**\n"
            f"商品原價：**{original_amount:,}T**"
            f"{rounding_note}",
            ephemeral=True,
        )


def _install_quantity_select_patch() -> None:
    global _ORIGINAL_QUANTITY_SELECT

    from services import order_runtime

    if _ORIGINAL_QUANTITY_SELECT is None:
        _ORIGINAL_QUANTITY_SELECT = order_runtime.SelfServiceOrderQuantitySelect
    original = _ORIGINAL_QUANTITY_SELECT

    class AwAwareQuantitySelect(original):
        def __init__(
            self,
            customer_id: int,
            channel_id: int,
            selected_item: str | None = None,
            selected_quantity: int | None = None,
        ):
            self.customer_id = int(customer_id)
            self.channel_id = int(channel_id)
            self.selected_item = selected_item
            data = order_runtime._require_runtime_state().order_selections.get(channel_id, {})
            rule_key = str(data.get("order_rule_key") or "")
            self._aw_collision_mode = is_aw_collision_rule(rule_key)

            if not self._aw_collision_mode:
                super().__init__(
                    customer_id,
                    channel_id,
                    selected_item,
                    selected_quantity,
                )
                return

            quantity = data.get("quantity")
            confirmed = bool(data.get("aw_collision_quantity_confirmed"))
            description = (
                f"目前 {int(quantity)} 發｜點擊可重新填寫"
                if confirmed and quantity is not None
                else "點擊後輸入要代撞的發數"
            )
            discord.ui.Select.__init__(
                self,
                placeholder="填寫發數",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(
                        label="發數",
                        value="aw_collision_quantity_modal",
                        description=description[:100],
                    )
                ],
                custom_id="self_service_order_quantity_select",
                row=3,
                disabled=False,
            )

        async def callback(self, interaction: discord.Interaction):
            if not self._aw_collision_mode:
                await super().callback(interaction)
                return

            state = order_runtime._require_runtime_state()
            if not state.can_operate_self_service_order(interaction.user, self.customer_id):
                await interaction.response.send_message(
                    "只有開這張票口的用戶或客服可以填寫發數。",
                    ephemeral=True,
                )
                return

            panel_message_id = interaction.message.id if interaction.message is not None else None
            await interaction.response.send_modal(
                AwCollisionQuantityModal(
                    customer_id=self.customer_id,
                    channel_id=self.channel_id,
                    panel_message_id=panel_message_id,
                )
            )

    order_runtime.SelfServiceOrderQuantitySelect = AwAwareQuantitySelect


def _install_dispatch_guard() -> None:
    global _ORIGINAL_WAITING_ORDER_CREATOR

    from services import self_service_dispatch_runtime as dispatch

    if _ORIGINAL_WAITING_ORDER_CREATOR is None:
        _ORIGINAL_WAITING_ORDER_CREATOR = dispatch.create_waiting_acceptance_order
    original = _ORIGINAL_WAITING_ORDER_CREATOR

    async def aw_aware_creator(
        interaction: discord.Interaction,
        *,
        customer_id: int,
        channel_id: int,
        deps,
    ):
        data = deps.order_selections.setdefault(channel_id, {})
        rule_key = str(data.get("order_rule_key") or "")
        if is_aw_collision_rule(rule_key):
            if not data.get("aw_collision_quantity_confirmed"):
                raise ValueError("請先在第四欄點「發數」，填寫實際要代撞的發數。")
            if str(data.get("aw_collision_plan_key") or "") != rule_key:
                raise ValueError(
                    "AW代撞方案與已填發數的方案不一致。請在第四欄重新填寫發數後再送出。"
                )
            try:
                validate_aw_quantity_for_rule(rule_key, int(data.get("quantity")))
            except (TypeError, ValueError) as exc:
                if isinstance(exc, ValueError) and str(exc):
                    raise ValueError(str(exc)) from exc
                raise ValueError("AW代撞發數異常，請重新填寫。") from exc

        return await original(
            interaction,
            customer_id=customer_id,
            channel_id=channel_id,
            deps=deps,
        )

    dispatch.create_waiting_acceptance_order = aw_aware_creator


def _install_panel_patch() -> None:
    global _ORIGINAL_PANEL_BUILDER

    from services import self_service_ui_runtime as ui

    if _ORIGINAL_PANEL_BUILDER is None:
        _ORIGINAL_PANEL_BUILDER = ui.build_self_service_panel_embed
    original = _ORIGINAL_PANEL_BUILDER

    def aw_panel(customer_id: int, data: dict, guild: discord.Guild | None = None):
        embed = original(customer_id, data, guild)
        rule_key = str(data.get("order_rule_key") or "")
        if not is_aw_collision_rule(rule_key):
            return embed

        confirmed = bool(data.get("aw_collision_quantity_confirmed"))
        plan = aw_collision_plan(rule_key) or {}
        for index, field in enumerate(list(embed.fields)):
            if str(field.name) == "第四欄｜單數":
                value = (
                    f"{int(data.get('quantity') or 0)} 發"
                    if confirmed
                    else "尚未填寫｜請點第四欄「發數」"
                )
                embed.set_field_at(index, name=field.name, value=value, inline=field.inline)
            elif str(field.name) == "訂單試算" and not confirmed:
                embed.set_field_at(
                    index,
                    name=field.name,
                    value=(
                        f"**方案：** {plan.get('label', 'AW代撞')}\n"
                        "**發數：** 尚未填寫\n"
                        "請先點第四欄「發數」輸入數量，系統才會計算價格。"
                    ),
                    inline=False,
                )
        return embed

    ui.build_self_service_panel_embed = aw_panel


def _patch_credential_placeholder() -> None:
    try:
        from services.order_credential_runtime import set_order_credential_note_placeholder
    except Exception:
        return

    set_order_credential_note_placeholder(CREDENTIAL_NOTE_PLACEHOLDER)


def install_aw_collision_catalog() -> None:
    """Install AW tier pricing, modal quantity input, and credential-copy update."""
    global _INSTALLED
    if _INSTALLED:
        return

    _extend_product_dependent_state()
    _install_quantity_select_patch()
    _install_dispatch_guard()
    _install_panel_patch()
    _patch_credential_placeholder()
    _INSTALLED = True


__all__ = [
    "AW_COLLISION_PLANS",
    "AW_GROUP_LABEL",
    "AW_RULE_KEYS",
    "AwCollisionQuantityModal",
    "CREDENTIAL_NOTE_PLACEHOLDER",
    "aw_collision_original_amount",
    "aw_collision_plan",
    "install_aw_collision_catalog",
    "is_aw_collision_rule",
    "validate_aw_quantity_for_rule",
]
