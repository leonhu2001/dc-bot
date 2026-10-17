from __future__ import annotations

from typing import Any, Mapping

import discord

from services.payment_methods import PAYMENT_METHOD_OPTIONS, WALLET_PAYMENT_METHOD
from services.wallet_service import get_wallet_payment_transaction
from services.orders import (
    ORDER_CATEGORY_LABELS,
    ORDER_ITEM_GROUPS_BY_CATEGORY,
    SELF_SERVICE_ACTIVE_CATEGORIES,
    _to_int,
    get_order_item_detail_for_selection,
    get_order_item_details_for_group,
    get_order_item_group_label,
    get_self_service_quantity_meta,
)
from services.self_service_selection_state import (
    apply_self_service_category_selection,
    apply_self_service_detail_selection,
    apply_self_service_item_group_selection,
)

from services.order_credential_runtime import (
    configure_order_credentials,
    _order_requires_credentials,
    _credential_user_for_id,
    _credential_display_name,
    _resolve_credential_owner,
    revoke_order_credential_messages,
    ensure_order_credential_request,
    OrderCredentialModal,
    OrderCredentialEntryView,
)
from services.order_point_redemption import (
    _get_pending_order_point_benefit_info,
    precheck_order_point_benefit_for_payment,
    redeem_order_point_benefit_on_payment,
)
from services.order_payment_runtime import (
    configure_order_payment_runtime,
    finalize_accepted_pending_payment,
)
from services.order_storage_runtime import (
    configure_order_storage_runtime,
    lock_dispatch_claim_panel,
    store_dispatch_claim_panel,
    resume_stored_order,
)
from services.order_dispatch_runtime import (
    DispatchCancelClaimButton,
    sync_single_discord_claim_event_to_web,
    maybe_handle_prepay_acceptance_claim,
    maybe_handle_prepay_acceptance_unclaim,
    DispatchClaimView,
    delete_dispatch_claim_panel_for_order,
    sync_web_order_status_from_bot,
)


_CONFIGURED = False

_MODULE_OWNED_RUNTIME_NAMES = frozenset(
    {
        "Any",
        "Mapping",
        "discord",
    }
)

_ORDER_RUNTIME_BINDING_NAMES = frozenset(
    {
        "DB_FILE",
        "DISPATCH_CHANNEL_ID",
        "ORDER_CONTROL_SELECTIONS",
        "SELF_SERVICE_ORDER_SELECTIONS",
        "SelfServiceOrderView",
        "_defer_and_refresh_self_service_panel",
        "_get_rule_from_self_service_data",
        "build_payment_method_embed",
        "build_self_service_panel_embed",
        "can_operate_self_service_order",
        "format_t_amount",
        "get_order_customer_id_from_channel",
        "get_wallet_balance",
        "is_customer_staff",
        "remember_order_data",
        "rename_ticket_channel",
        "send_order_log",
    }
)



def configure_order_runtime_explicit(
    *,
    db_file,
    dispatch_channel_id,
    order_control_selections,
    order_selections,
    self_service_order_view_type,
    defer_and_refresh_self_service_panel,
    self_service_rule_getter,
    payment_method_embed_builder,
    self_service_panel_embed_builder,
    can_operate_self_service_order_func,
    amount_formatter,
    order_customer_id_getter,
    wallet_balance_getter,
    customer_staff_checker,
    remember_order,
    ticket_channel_renamer,
    order_log_sender,
) -> None:
    # Explicit args keep the transitional module-global binding allowlisted.
    globals().update(
        {
            "DB_FILE": db_file,
            "DISPATCH_CHANNEL_ID": dispatch_channel_id,
            "ORDER_CONTROL_SELECTIONS": order_control_selections,
            "SELF_SERVICE_ORDER_SELECTIONS": order_selections,
            "SelfServiceOrderView": self_service_order_view_type,
            "_defer_and_refresh_self_service_panel": defer_and_refresh_self_service_panel,
            "_get_rule_from_self_service_data": self_service_rule_getter,
            "build_payment_method_embed": payment_method_embed_builder,
            "build_self_service_panel_embed": self_service_panel_embed_builder,
            "can_operate_self_service_order": can_operate_self_service_order_func,
            "format_t_amount": amount_formatter,
            "get_order_customer_id_from_channel": order_customer_id_getter,
            "get_wallet_balance": wallet_balance_getter,
            "is_customer_staff": customer_staff_checker,
            "remember_order_data": remember_order,
            "rename_ticket_channel": ticket_channel_renamer,
            "send_order_log": order_log_sender,
        }
    )


def configure_order_runtime(namespace: Mapping[str, Any]) -> None:
    """Bind remaining bot-owned legacy dependencies after bot.py is loaded."""
    global _CONFIGURED

    for name in _ORDER_RUNTIME_BINDING_NAMES:
        if name in namespace:
            globals()[name] = namespace[name]

    credential_keys = {
        "CREDENTIAL_OWNER_USER_ID",
        "GUILD_ID",
        "SELF_SERVICE_ORDER_SELECTIONS",
        "_to_int",
        "bot",
        "fetch_member_safely",
        "get_taipei_now_iso",
        "remember_order_data",
        "save_bot_data",
    }
    if credential_keys.issubset(namespace):
        configure_order_credentials(
            credential_owner_user_id=namespace["CREDENTIAL_OWNER_USER_ID"],
            guild_id=namespace["GUILD_ID"],
            self_service_order_selections=namespace["SELF_SERVICE_ORDER_SELECTIONS"],
            to_int=namespace["_to_int"],
            bot_instance=namespace["bot"],
            fetch_member=namespace["fetch_member_safely"],
            taipei_now_iso=namespace["get_taipei_now_iso"],
            remember_data=namespace["remember_order_data"],
            save_data=namespace["save_bot_data"],
        )

    payment_keys = {
        "DISPATCH_CHANNEL_ID",
        "ORDER_CATEGORY_LABELS",
        "ORDER_CLAIMS",
        "SELF_SERVICE_ORDER_SELECTIONS",
        "StaffOrderOperationView",
        "_build_receiver_text_from_claim_data",
        "_to_int",
        "add_customer_reward_from_order",
        "adjust_customer_wallet_balance",
        "build_payment_method_embed",
        "build_self_service_order_embed",
        "ensure_payment_submit_receipt",
        "fetch_member_safely",
        "format_t_amount",
        "get_taipei_now_iso",
        "remember_claim_data",
        "remember_order_data",
        "rename_ticket_channel",
        "save_bot_data",
        "send_order_log",
        "send_wallet_log",
    }
    if payment_keys.issubset(namespace):
        configure_order_payment_runtime(
            dispatch_channel_id=namespace["DISPATCH_CHANNEL_ID"],
            dispatch_claim_view=DispatchClaimView,
            order_category_labels=namespace["ORDER_CATEGORY_LABELS"],
            order_claims=namespace["ORDER_CLAIMS"],
            payment_method_view=PaymentMethodView,
            self_service_order_selections=namespace["SELF_SERVICE_ORDER_SELECTIONS"],
            staff_order_operation_view=namespace["StaffOrderOperationView"],
            receiver_text_builder=namespace["_build_receiver_text_from_claim_data"],
            to_int=namespace["_to_int"],
            customer_reward_adder=namespace["add_customer_reward_from_order"],
            wallet_adjuster=namespace["adjust_customer_wallet_balance"],
            payment_method_embed_builder=namespace["build_payment_method_embed"],
            self_service_order_embed_builder=namespace["build_self_service_order_embed"],
            payment_receipt_ensurer=namespace["ensure_payment_submit_receipt"],
            fetch_member=namespace["fetch_member_safely"],
            amount_formatter=namespace["format_t_amount"],
            taipei_now_iso=namespace["get_taipei_now_iso"],
            remember_claim=namespace["remember_claim_data"],
            remember_order=namespace["remember_order_data"],
            ticket_channel_renamer=namespace["rename_ticket_channel"],
            save_data=namespace["save_bot_data"],
            order_log_sender=namespace["send_order_log"],
            wallet_log_sender=namespace["send_wallet_log"],
        )

    storage_keys = {
        "DISPATCH_CHANNEL_ID",
        "ORDER_CATEGORY_LABELS",
        "ORDER_CLAIMS",
        "SELF_SERVICE_ORDER_SELECTIONS",
        "_apply_acceptance_state_to_claim_data",
        "_get_rule_from_self_service_data",
        "_to_int",
        "build_self_service_order_embed",
        "delete_claim_row_from_db",
        "get_taipei_now_iso",
        "prepare_initial_smart_dispatch",
        "remember_claim_data",
        "remember_order_data",
        "save_bot_data",
        "send_initial_smart_dispatch_alert",
        "send_specified_staff_dispatch_dms",
        "set_specified_dm_results",
    }
    if storage_keys.issubset(namespace):
        configure_order_storage_runtime(
            dispatch_channel_id=namespace["DISPATCH_CHANNEL_ID"],
            dispatch_claim_view=DispatchClaimView,
            order_category_labels=namespace["ORDER_CATEGORY_LABELS"],
            order_claims=namespace["ORDER_CLAIMS"],
            self_service_order_selections=namespace["SELF_SERVICE_ORDER_SELECTIONS"],
            to_int=namespace["_to_int"],
            self_service_order_embed_builder=namespace["build_self_service_order_embed"],
            taipei_now_iso=namespace["get_taipei_now_iso"],
            remember_claim=namespace["remember_claim_data"],
            remember_order=namespace["remember_order_data"],
            save_data=namespace["save_bot_data"],
            acceptance_state_applier=namespace["_apply_acceptance_state_to_claim_data"],
            self_service_rule_getter=namespace["_get_rule_from_self_service_data"],
            claim_row_deleter=namespace["delete_claim_row_from_db"],
            initial_dispatch_preparer=namespace["prepare_initial_smart_dispatch"],
            initial_dispatch_alert_sender=namespace["send_initial_smart_dispatch_alert"],
            specified_staff_dm_sender=namespace["send_specified_staff_dispatch_dms"],
            specified_dm_result_setter=namespace["set_specified_dm_results"],
            web_order_status_syncer=sync_web_order_status_from_bot,
        )

    _CONFIGURED = True


class OrderControlSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="填寫自助下單",
                value="dispatch",
                description="開啟自助下單面板給開單用戶填寫"
            ),
            discord.SelectOption(
                label="取消訂單",
                value="cancel",
                description="取消並關閉這張下單票口"
            ),
        ]

        super().__init__(
            placeholder="客服操作選項",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="order_control_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以操作訂單。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("這個功能只能在下單票口內使用。", ephemeral=True)
            return

        ORDER_CONTROL_SELECTIONS[(interaction.channel.id, interaction.user.id)] = self.values[0]

        await interaction.response.defer()


class SelfServiceOrderCategorySelect(discord.ui.Select):
    def __init__(self, customer_id: int, channel_id: int, selected_category: str | None = None):
        self.customer_id = customer_id
        self.channel_id = channel_id

        options = [
            discord.SelectOption(
                label=ORDER_CATEGORY_LABELS.get(category_key, category_key),
                value=category_key,
                default=selected_category == category_key
            )
            for category_key in SELF_SERVICE_ACTIVE_CATEGORIES
        ]

        super().__init__(
            placeholder="請選擇訂單類別",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="self_service_order_category_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇訂單。", ephemeral=True)
            return

        selected_category = self.values[0]

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data["customer_id"] = self.customer_id
        apply_self_service_category_selection(data, selected_category)
        remember_order_data(self.channel_id, data)
        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "選擇訂單類別",
            ORDER_CATEGORY_LABELS.get(selected_category, selected_category),
        )

        await interaction.response.edit_message(
            embed=build_self_service_panel_embed(self.customer_id, data, interaction.guild),
            view=SelfServiceOrderView(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                selected_category=selected_category
            )
        )


class SelfServiceOrderItemSelect(discord.ui.Select):
    def __init__(
        self,
        customer_id: int,
        channel_id: int,
        selected_category: str | None = None,
        selected_item: str | None = None,
    ):
        self.customer_id = customer_id
        self.channel_id = channel_id
        self.selected_category = selected_category

        data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        selected_group = data.get("item_group") or (
            get_order_item_group_label(selected_item) if selected_item else None
        )

        if selected_category is None:
            options = [
                discord.SelectOption(
                    label="請先選擇訂單類別",
                    value="need_category",
                    description="選完上方類別後，這裡會自動更新",
                )
            ]
            disabled = True
            placeholder = "請先選擇訂單類別"
        else:
            group_options = ORDER_ITEM_GROUPS_BY_CATEGORY.get(selected_category, [])

            if group_options:
                options = [
                    discord.SelectOption(
                        label=str(group_label)[:100],
                        value=str(group_label)[:100],
                        description=ORDER_CATEGORY_LABELS.get(selected_category, selected_category)[:100],
                        default=str(group_label) == str(selected_group),
                    )
                    for group_label in group_options[:25]
                ]
                disabled = False
                placeholder = "請選擇訂單項目"
            else:
                # Discord Select 即使 disabled 也必須至少有 1 個 option；
                # 不能傳 options=[]，否則 API 會回 50035 Invalid Form Body。
                options = [
                    discord.SelectOption(
                        label="此類別目前沒有可用品項",
                        value="no_items",
                        description="請改選其他訂單類別",
                    )
                ]
                disabled = True
                placeholder = "此類別目前沒有可用品項"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="self_service_order_item_select",
            row=1,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇訂單項目。", ephemeral=True)
            return

        selected_group = self.values[0]
        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data["customer_id"] = self.customer_id
        apply_self_service_item_group_selection(data, selected_group)
        remember_order_data(self.channel_id, data)

        await _defer_and_refresh_self_service_panel(
            interaction,
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            data=data,
        )

        try:
            await log_self_service_proxy_action(
                interaction,
                self.customer_id,
                "自助下單項目",
                selected_group,
            )
        except Exception as exc:
            print(f"[self-service] log 自助下單項目失敗 channel_id={self.channel_id}: {exc}")


class SelfServiceOrderDetailSelect(discord.ui.Select):
    def __init__(
        self,
        customer_id: int,
        channel_id: int,
    ):
        self.customer_id = customer_id
        self.channel_id = channel_id

        data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        category = data.get("category")
        selected_group = data.get("item_group")
        selected_value = str(data.get("item_detail_value") or "")

        if category is None or selected_group is None:
            options = [
                discord.SelectOption(
                    label="請先選擇訂單項目",
                    value="need_item",
                    description="選完第二欄後，這裡會顯示規格",
                )
            ]
            disabled = True
            placeholder = "請先選擇訂單項目"
        else:
            details = get_order_item_details_for_group(category, selected_group)
            if not details:
                options = [
                    discord.SelectOption(
                        label="沒有可用規格",
                        value="need_item",
                        description="請重新選擇訂單項目",
                    )
                ]
                disabled = True
                placeholder = "沒有可用規格"
            else:
                options = [
                    discord.SelectOption(
                        label=str(detail.get("label") or detail.get("item"))[:100],
                        value=str(detail.get("value") or "")[:100],
                        description=(
                            f"{detail.get('quantity_unit', '單')}｜"
                            f"{detail.get('min_quantity', 1)}～{detail.get('max_quantity', 1)}"
                        )[:100],
                        default=str(detail.get("value") or "") == selected_value,
                    )
                    for detail in details[:25]
                ]
                disabled = len(details) == 1 and bool(selected_value)
                placeholder = "請選擇具體規格"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="self_service_order_detail_select",
            row=2,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇訂單規格。", ephemeral=True)
            return

        selected_value = self.values[0]
        if selected_value == "need_item":
            await interaction.response.defer()
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        category = data.get("category")
        selected_group = data.get("item_group")
        detail = get_order_item_detail_for_selection(category, selected_group, selected_value)

        if detail is None:
            await interaction.response.send_message("訂單規格選擇異常，請重新選擇。", ephemeral=True)
            return

        apply_self_service_detail_selection(data, detail)
        remember_order_data(self.channel_id, data)

        await _defer_and_refresh_self_service_panel(
            interaction,
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            data=data,
        )

        try:
            await log_self_service_proxy_action(
                interaction,
                self.customer_id,
                "自助下單規格",
                str(detail.get("label") or detail.get("item")),
            )
        except Exception as exc:
            print(f"[self-service] log 自助下單規格失敗 channel_id={self.channel_id}: {exc}")


def _get_order_rule_by_item_label(item: str | None):
    item_text = str(item or "").strip()
    if not item_text:
        return None

    try:
        from services.order_rules import ORDER_RULES
        from services.orders import ORDER_RULE_KEY_BY_LABEL
    except Exception:
        return None

    rule_key = ORDER_RULE_KEY_BY_LABEL.get(item_text)
    if rule_key and rule_key in ORDER_RULES:
        return ORDER_RULES[rule_key]

    for rule in ORDER_RULES.values():
        if str(getattr(rule, "label", "")) == item_text:
            return rule
    return None


def normalize_self_service_staff_count(data: dict) -> None:
    if not isinstance(data, dict):
        return

    try:
        rule = _get_rule_from_self_service_data(data)
    except Exception:
        return

    if not bool(getattr(rule, "player_count_enabled", False)):
        return

    raw_value = data.get("player_count")
    if raw_value is None or str(raw_value).strip() == "":
        return

    value = _to_int(raw_value)
    if value is None:
        data.pop("player_count", None)
        return

    minimum = max(1, int(getattr(rule, "min_player_count", 1) or 1))
    maximum_raw = getattr(rule, "max_player_count", None)
    maximum = int(maximum_raw) if maximum_raw is not None else None
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    data["player_count"] = value


def _self_service_quantity_meta(data: dict | None, item: str | None = None) -> dict:
    data = data or {}
    meta = get_self_service_quantity_meta(
        data.get("category"),
        data.get("item_group"),
        data.get("item_detail_value"),
    )
    if meta:
        return meta

    # 舊訂單 / 舊 panel fallback。
    rule = _get_order_rule_by_item_label(item or data.get("item"))
    if rule is None:
        return {"unit": "單", "min": 1, "max": 1}

    item_text = str(item or data.get("item") or "")
    if item_text == "炫彩勇敢者｜代做":
        return {"unit": "小時", "min": 1, "max": 3}
    if item_text in {"炫彩勇敢者｜陪做", "勇敢者｜陪做"}:
        return {"unit": "小時", "min": 1, "max": 1}

    pricing_type = str(getattr(rule, "pricing_type", "") or "").lower()
    unit = "小時" if str(getattr(rule, "unit_label", "")) == "H" else str(getattr(rule, "unit_label", "單") or "單")
    minimum = max(1, int(getattr(rule, "min_quantity", 1) or 1))
    maximum = int(getattr(rule, "max_quantity", None) or (24 if pricing_type in {"hourly", "game"} else 1))
    return {"unit": unit, "min": minimum, "max": max(minimum, maximum)}


def get_self_service_quantity_limit(item: str | None, data: dict | None = None) -> int:
    return int(_self_service_quantity_meta(data, item)["max"])


def get_self_service_quantity_unit(item: str | None, data: dict | None = None) -> str:
    return str(_self_service_quantity_meta(data, item)["unit"])


def get_self_service_quantity_options(item: str | None, data: dict | None = None) -> list[int]:
    meta = _self_service_quantity_meta(data, item)
    return list(range(int(meta["min"]), int(meta["max"]) + 1))


class SelfServiceOrderQuantitySelect(discord.ui.Select):
    def __init__(
        self,
        customer_id: int,
        channel_id: int,
        selected_item: str | None = None,
        selected_quantity: int | None = None,
    ):
        self.customer_id = customer_id
        self.channel_id = channel_id
        self.selected_item = selected_item
        data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        quantity = selected_quantity or 1

        if selected_item is None:
            options = [
                discord.SelectOption(
                    label="請先選擇具體規格",
                    value="need_item",
                    description="選完第三欄後，這裡會顯示單數",
                )
            ]
            disabled = True
            placeholder = "請先選擇具體規格"
        else:
            quantity_options = get_self_service_quantity_options(selected_item, data)
            quantity_unit = get_self_service_quantity_unit(selected_item, data)

            if quantity not in quantity_options:
                quantity = quantity_options[0]

            if len(quantity_options) == 1:
                options = [
                    discord.SelectOption(
                        label=f"{quantity_options[0]} {quantity_unit}",
                        value=str(quantity_options[0]),
                        description=f"此項目固定 {quantity_options[0]} {quantity_unit}",
                        default=True,
                    )
                ]
                disabled = True
                placeholder = f"固定 {quantity_options[0]} {quantity_unit}"
            else:
                options = [
                    discord.SelectOption(
                        label=f"{num} {quantity_unit}",
                        value=str(num),
                        description=f"{num} {quantity_unit}",
                        default=quantity == num,
                    )
                    for num in quantity_options[:25]
                ]
                disabled = False
                placeholder = f"請選擇 {min(quantity_options)}～{max(quantity_options)} {quantity_unit}"

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="self_service_order_quantity_select",
            row=3,
            disabled=disabled,
        )

    async def callback(self, interaction: discord.Interaction):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇訂單單數。", ephemeral=True)
            return

        if self.values[0] == "need_item":
            await interaction.response.defer()
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        selected_item = data.get("item")

        try:
            quantity = int(self.values[0])
        except ValueError:
            await interaction.response.send_message("單數選擇異常，請重新選擇。", ephemeral=True)
            return

        meta = _self_service_quantity_meta(data, selected_item)
        minimum = int(meta["min"])
        maximum = int(meta["max"])
        quantity_unit = str(meta["unit"])

        if quantity < minimum or quantity > maximum:
            await interaction.response.send_message(
                f"單數請選擇 {minimum}～{maximum} {quantity_unit}。",
                ephemeral=True,
            )
            return

        data["customer_id"] = self.customer_id
        data["quantity"] = quantity
        data.pop("payment_method", None)
        remember_order_data(self.channel_id, data)

        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "選擇訂單單數",
            f"{quantity} {quantity_unit}",
        )

        await interaction.response.edit_message(
            embed=build_self_service_panel_embed(self.customer_id, data, interaction.guild),
            view=SelfServiceOrderView(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                selected_category=data.get("category"),
            ),
        )

async def log_self_service_proxy_action(
    interaction: discord.Interaction,
    customer_id: int,
    action: str,
    detail: str | None = None,
) -> None:
    """客服 / 店長 / 管理員代操作自助下單時，寫入機器人日誌。"""
    if interaction.user.id == customer_id:
        return

    channel_text = interaction.channel.mention if isinstance(interaction.channel, discord.TextChannel) else "未紀錄"
    fields = [
        ("操作人員", interaction.user.mention, True),
        ("原下單顧客", f"<@{customer_id}>", True),
        ("票口", channel_text, False),
        ("操作", action, True),
    ]

    if detail:
        fields.append(("內容", detail, False))

    try:
        await send_order_log(
            interaction.guild,
            title="自助下單代操作",
            fields=fields,
            color=discord.Color.teal(),
        )
    except Exception as e:
        print(f"寫入自助下單代操作日誌失敗：{e}")













































class StoreOrderModal(discord.ui.Modal, title="存單"):
    reason = discord.ui.TextInput(
        label="存單原因",
        placeholder="例如：顧客暫時無法遊玩、改約時間、等待活動開啟",
        required=True,
        max_length=200
    )

    expected_time = discord.ui.TextInput(
        label="預計恢復時間",
        placeholder="例如：今晚 20:00、明天、未定",
        required=False,
        max_length=100
    )

    note = discord.ui.TextInput(
        label="備註",
        placeholder="可填寫付款狀態、注意事項或客服備註",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=800
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
            return

        if not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以存單。", ephemeral=True)
            return

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("這個功能只能在下單票口內使用。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            await store_dispatch_claim_panel(
                guild=guild,
                order_channel=interaction.channel,
                staff_member=interaction.user,
                reason=self.reason.value.strip(),
                expected_time=self.expected_time.value.strip() or None,
                note=self.note.value.strip() or None,
            )
            store_data = SELF_SERVICE_ORDER_SELECTIONS.get(interaction.channel.id, {})
            store_item = str(store_data.get("item") or store_data.get("category_label") or "訂單")
            store_customer_id = get_order_customer_id_from_channel(interaction.channel)
            store_customer_member = guild.get_member(store_customer_id) if store_customer_id is not None else None
            await rename_ticket_channel(interaction.channel, f"存單-{store_item}", member=store_customer_member)
            await send_order_log(
                guild,
                title="訂單已存單",
                fields=[
                    ("票口", interaction.channel.mention, True),
                    ("操作人員", interaction.user.mention, True),
                    ("存單原因", self.reason.value.strip(), False),
                    ("預計恢復", self.expected_time.value.strip() or "未填寫", True),
                    ("備註", self.note.value.strip() or "未填寫", False),
                ],
                color=discord.Color.gold(),
            )
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        await interaction.channel.send(
            f"此訂單已由 {interaction.user.mention} 存單。\n\n"
            f"存單原因：{self.reason.value.strip()}\n"
            f"預計恢復：{self.expected_time.value.strip() or '未填寫'}\n"
            f"備註：{self.note.value.strip() or '無'}",
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False
            )
        )

        await interaction.followup.send("已存單，派單頻道接單面板已鎖定。", ephemeral=True)



async def finalize_payment_and_dispatch(
    *,
    interaction: discord.Interaction,
    customer_id: int,
    channel_id: int,
    reward_result: str | None = None,
) -> None:
    async def send_ephemeral(message: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    guild = interaction.guild

    if guild is None:
        await send_ephemeral("這個功能只能在伺服器內使用。")
        return

    if not isinstance(interaction.channel, discord.TextChannel):
        await send_ephemeral("無法確認目前票口頻道。")
        return

    data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
    status = str(data.get("status") or "").lower().strip()

    if status == "accepted_pending_pay":
        await finalize_accepted_pending_payment(
            interaction=interaction,
            customer_id=customer_id,
            channel_id=channel_id,
        )
        return

    if status == "waiting_acceptance":
        await send_ephemeral("這張單還在等待接單，人數滿後才會開放付款。")
        return

    if status == "active":
        await send_ephemeral("這張單已付款成立，不需要再次送出付款。")
        return

    if status in {"closed", "cancelled", "canceled", "stored"}:
        await send_ephemeral(f"這張單目前狀態為 {status}，不能送出付款。")
        return

    dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID

    if dispatch_message_id is not None:
        dispatch_channel = guild.get_channel(dispatch_channel_id)
        if isinstance(dispatch_channel, discord.TextChannel):
            await send_ephemeral(
                "這張單已有派單訊息，舊付款後派單流程已停用。\n"
                f"派單訊息：https://discord.com/channels/{guild.id}/{dispatch_channel.id}/{dispatch_message_id}"
            )
        else:
            await send_ephemeral("這張單已有派單訊息，舊付款後派單流程已停用。")
        return

    await send_ephemeral(
        "舊付款後派單流程已停用。\n"
        "請使用現在的流程：自助下單送出等待接單 → 接單人數滿 → 顧客付款 → 訂單成立。"
    )






class PaymentMethodSelect(discord.ui.Select):
    def __init__(
        self,
        customer_id: int,
        channel_id: int,
        selected_method: str | None = None,
    ):
        self.customer_id = customer_id
        self.channel_id = channel_id

        normalized_selected_method = str(selected_method or "").strip()

        options = [
            discord.SelectOption(
                label=method,
                value=method,
                default=(method == normalized_selected_method),
            )
            for method in PAYMENT_METHOD_OPTIONS
        ]

        placeholder = (
            f"✓ 已選擇：{normalized_selected_method}"
            if normalized_selected_method in PAYMENT_METHOD_OPTIONS
            else "請選擇付款方式"
        )

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
            custom_id="payment_method_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇付款方式。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data["customer_id"] = self.customer_id
        selected_method = self.values[0]
        data["payment_method"] = selected_method

        self.placeholder = f"✓ 已選擇：{selected_method}"
        for option in self.options:
            option.default = option.value == selected_method

        remember_order_data(self.channel_id, data)
        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "選擇付款方式",
            selected_method,
        )

        category = data.get("category")
        item = data.get("item")
        quantity = _to_int(data.get("quantity"), 1) or 1
        companion_preference = data.get("companion_preference")
        amount = _to_int(data.get("amount"), 0) or _to_int(data.get("total_amount"), 0) or 0

        if category is not None and item is not None:
            payment_embed = build_payment_method_embed(
                customer_id=self.customer_id,
                category_label=ORDER_CATEGORY_LABELS.get(category, str(category)),
                item=str(item),
                quantity=quantity,
                payment_method=selected_method,
                companion_preference=companion_preference,
                amount=amount or None,
                receiver_text=str(data.get("accepted_staff_display_text") or "").strip() or None,
            )

            if selected_method == WALLET_PAYMENT_METHOD:
                # A wallet debit may already have committed even if a later Discord/Web
                # finalization step failed. Recover the authoritative ledger row by ticket
                # channel so the UI and the next retry both know this order is already paid.
                wallet_tx = get_wallet_payment_transaction(
                    self.customer_id,
                    self.channel_id,
                    db_file=DB_FILE,
                )
                if wallet_tx is not None:
                    data["wallet_transaction_id"] = wallet_tx["id"]
                    data["wallet_paid_amount"] = abs(int(wallet_tx.get("amount") or 0))
                    data["wallet_balance_before"] = int(wallet_tx.get("balance_before") or 0)
                    data["wallet_balance_after"] = int(wallet_tx.get("balance_after") or 0)
                    remember_order_data(self.channel_id, data)
                    wallet_text = (
                        f"✅ 錢包已扣款：{format_t_amount(abs(int(wallet_tx.get('amount') or 0)))}\n"
                        f"扣款後餘額：{format_t_amount(int(wallet_tx.get('balance_after') or 0))}\n"
                        "重新送出只會繼續完成訂單，不會再次扣款。"
                    )
                else:
                    wallet_balance = get_wallet_balance(self.customer_id)
                    if amount > 0:
                        after_balance = wallet_balance - amount
                        wallet_text = (
                            f"目前錢包餘額：{format_t_amount(wallet_balance)}\n"
                            f"本單金額：{format_t_amount(amount)}\n"
                        )
                        if after_balance >= 0:
                            wallet_text += f"扣款後餘額：{format_t_amount(after_balance)}"
                        else:
                            wallet_text += f"尚不足：{format_t_amount(abs(after_balance))}"
                    else:
                        wallet_text = (
                            f"目前錢包餘額：{format_t_amount(wallet_balance)}\n"
                            "本單金額：待客服填寫"
                        )

                payment_embed.add_field(
                    name="我的錢包",
                    value=wallet_text,
                    inline=False,
                )

            await interaction.response.edit_message(embed=payment_embed, view=self.view)
        else:
            await interaction.response.defer()


class PaymentMethodView(discord.ui.View):
    def __init__(
        self,
        customer_id: int,
        channel_id: int,
        submitted: bool = False,
        selected_method: str | None = None,
    ):
        super().__init__(timeout=86400)
        self.customer_id = customer_id
        self.channel_id = channel_id
        self.submitted = submitted
        self.add_item(
            PaymentMethodSelect(
                customer_id,
                channel_id,
                selected_method=selected_method,
            )
        )

        if submitted:
            for child in self.children:
                child.disabled = True
                if isinstance(child, discord.ui.Button) and child.custom_id == "payment_method_submit_button":
                    child.label = "已送出"
                    child.style = discord.ButtonStyle.secondary

    @discord.ui.button(
        label="送出",
        style=discord.ButtonStyle.success,
        custom_id="payment_method_submit_button",
        row=1
    )
    async def submit_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以送出付款方式。", ephemeral=True)
            return

        await finalize_payment_and_dispatch(
            interaction=interaction,
            customer_id=self.customer_id,
            channel_id=self.channel_id,
        )