from __future__ import annotations

import discord

from core.database import (
    delete_claim_row_from_db,
    remember_order_data,
    save_bot_data,
)
from core.permissions import can_operate_self_service_order, is_customer_staff
from core.time_utils import get_taipei_now_iso
from services.order_runtime import (
    SelfServiceOrderCategorySelect,
    SelfServiceOrderDetailSelect,
    SelfServiceOrderItemSelect,
    SelfServiceOrderQuantitySelect,
    _self_service_quantity_meta,
    get_self_service_quantity_unit,
    log_self_service_proxy_action,
    normalize_self_service_staff_count,
)
from services.orders import (
    ORDER_CATEGORY_LABELS,
    ORDER_ITEM_TO_CATEGORY,
    _to_int,
    get_order_item_detail_for_selection,
)
from services.self_service_dispatch_cleanup import cleanup_failed_self_service_dispatch
from services.self_service_financials import (
    _format_percent_value,
    _format_plain_amount,
    _parse_cash_amount_text,
    _parse_discount_percent_text,
    add_self_service_quote_preview,
    get_self_service_staff_price,
    is_aw_collision_rule,
    is_order_point_benefit_allowed_for_rule,
    is_self_service_staff_price_required,
)
from services.self_service_retract import SelfServiceDispatchedView
from services.self_service_selection_runtime import (
    SelfServicePointBenefitView,
    SelfServiceSpecifiedStaffDropdownView,
    get_specified_staff_entries_for_rule,
)


_CONFIGURED = False
SELF_SERVICE_ORDER_SELECTIONS: dict = {}
ORDER_CLAIMS: dict = {}
DISPATCH_CHANNEL_ID = 0


def _unconfigured(*_args, **_kwargs):
    raise RuntimeError("self-service UI runtime is not configured")


_get_rule_from_self_service_data = _unconfigured
_is_specify_preference = _unconfigured
create_waiting_acceptance_order_from_self_service = _unconfigured


def configure_self_service_ui_runtime(
    *,
    order_selections: dict,
    order_claims: dict,
    dispatch_channel_id: int,
    get_rule_from_data,
    is_specify_preference,
    create_waiting_order,
) -> None:
    """Bind the small set of orchestrator-owned callbacks/state used by the UI."""
    global _CONFIGURED
    global SELF_SERVICE_ORDER_SELECTIONS, ORDER_CLAIMS, DISPATCH_CHANNEL_ID
    global _get_rule_from_self_service_data, _is_specify_preference
    global create_waiting_acceptance_order_from_self_service

    SELF_SERVICE_ORDER_SELECTIONS = order_selections
    ORDER_CLAIMS = order_claims
    DISPATCH_CHANNEL_ID = int(dispatch_channel_id)
    _get_rule_from_self_service_data = get_rule_from_data
    _is_specify_preference = is_specify_preference
    create_waiting_acceptance_order_from_self_service = create_waiting_order
    _CONFIGURED = True


class SelfServicePlayerCountModal(discord.ui.Modal, title="填寫陪玩人數"):
    player_count = discord.ui.TextInput(
        label="陪玩人數",
        placeholder="例如：1、2、3、4",
        required=True,
        max_length=3,
    )

    def __init__(self, customer_id: int, channel_id: int):
        super().__init__()
        self.customer_id = customer_id
        self.channel_id = channel_id

    async def on_submit(self, interaction: discord.Interaction):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以操作訂單。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})

        try:
            rule = _get_rule_from_self_service_data(data)
            value = int(str(self.player_count.value).strip())
        except ValueError:
            await interaction.response.send_message("陪玩人數請輸入數字。", ephemeral=True)
            return

        if value < int(rule.min_player_count or 1):
            await interaction.response.send_message(f"陪玩人數至少需要 {rule.min_player_count} 位。", ephemeral=True)
            return

        if rule.max_player_count is not None and value > int(rule.max_player_count):
            await interaction.response.send_message(f"{rule.label} 最多只能點 {rule.max_player_count} 位。", ephemeral=True)
            return

        data["player_count"] = value
        data.pop("payment_method", None)
        remember_order_data(self.channel_id, data)

        await interaction.response.send_message(
            f"已填寫陪玩人數：**{value} 位**。\n請再按一次「送出等待接單」。",
            ephemeral=True,
        )

PRICE_FORMULA_VERSION = 2


def build_self_service_panel_embed(
    customer_id: int,
    data: dict,
    guild: discord.Guild | None = None,
) -> discord.Embed:
    category = data.get("category")
    category_label = ORDER_CATEGORY_LABELS.get(category, "尚未選擇")
    item_group = str(data.get("item_group") or "尚未選擇")

    detail = get_order_item_detail_for_selection(
        category,
        data.get("item_group"),
        data.get("item_detail_value"),
    )
    detail_label = str((detail or {}).get("label") or "尚未選擇")

    quantity = _to_int(data.get("quantity"), 1) or 1
    quantity_unit = get_self_service_quantity_unit(data.get("item"), data) if data.get("item") else "單"

    embed = discord.Embed(
        title="自助下單",
        description=(
            f"下單用戶：<@{customer_id}>\n\n"
            "請依序選擇：類別 → 訂單項目 → 具體規格 → 單數。\n"
            "可指定的品項才會開放指定成員；2 小時以上免指定費。\n"
            "送出後先進入等待接單，人數滿後才開放付款。"
        ),
        color=discord.Color.purple(),
    )

    embed.add_field(name="第一欄｜類別", value=str(category_label), inline=True)
    embed.add_field(name="第二欄｜項目", value=item_group, inline=True)
    embed.add_field(name="第三欄｜規格", value=detail_label, inline=True)

    if data.get("item"):
        embed.add_field(
            name="第四欄｜單數",
            value=f"{quantity} {quantity_unit}",
            inline=True,
        )

    try:
        rule = _get_rule_from_self_service_data(data) if data.get("item") else None
    except Exception:
        rule = None

    if rule is not None:
        if getattr(rule, "allow_specify", False):
            specified_ids = [str(item) for item in data.get("specified_staff_ids") or []]
            specify_text = "未指定" if not specified_ids else f"已指定 {len(specified_ids)} 位"
        else:
            specify_text = "此品項不可指定"
        embed.add_field(name="指定", value=specify_text, inline=True)

    return add_self_service_quote_preview(embed, data, guild)

# 指定陪玩 / 點數福利選擇 UI 已移至 services/self_service_selection_runtime.py
# 客服手動價格規則由 services/self_service_financials.py 單一維護。


class SelfServiceStaffPriceModal(discord.ui.Modal, title="客服填寫訂單價格"):
    amount = discord.ui.TextInput(
        label="訂單價格",
        placeholder="請輸入實收前原價，例如 3000",
        required=True,
        max_length=10,
    )

    reason = discord.ui.TextInput(
        label="價格備註",
        placeholder="例如 自訂單報價、部門任務報價",
        required=False,
        max_length=100,
    )

    def __init__(self, customer_id: int, channel_id: int, panel_message_id: int | None = None):
        super().__init__()
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)
        self.panel_message_id = panel_message_id

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以填寫訂單價格。", ephemeral=True)
            return

        raw_amount = str(self.amount.value or "").strip().replace(",", "")

        try:
            amount = int(float(raw_amount))
        except ValueError:
            await interaction.response.send_message("價格請輸入數字，例如 3000。", ephemeral=True)
            return

        if amount < 0:
            await interaction.response.send_message("價格不能小於 0。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        data["manual_staff_amount"] = int(amount)
        data["manual_staff_price_reason"] = str(self.reason.value or "").strip()
        data["manual_staff_price_set_by"] = interaction.user.id
        data["manual_staff_price_set_at"] = get_taipei_now_iso()
        data.pop("payment_method", None)

        remember_order_data(self.channel_id, data)

        await interaction.response.defer(ephemeral=True)

        edited_panel = False

        if isinstance(interaction.channel, discord.TextChannel) and self.panel_message_id:
            try:
                panel_message = await interaction.channel.fetch_message(self.panel_message_id)
                await panel_message.edit(
                    embed=build_self_service_panel_embed(self.customer_id, data, interaction.guild),
                    view=SelfServiceOrderView(
                        customer_id=self.customer_id,
                        channel_id=self.channel_id,
                        selected_category=data.get("category"),
                    ),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
                edited_panel = True
            except discord.HTTPException:
                edited_panel = False

        await interaction.followup.send(
            f"已設定訂單價格：{_format_plain_amount(amount)}"
            + (f"\n備註：{data['manual_staff_price_reason']}" if data.get("manual_staff_price_reason") else "")
            + ("" if edited_panel else "\n\n提醒：面板沒有自動刷新，請重新選一次數量即可刷新試算。"),
            ephemeral=True,
        )

        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "客服填寫訂單價格",
            f"{_format_plain_amount(amount)}｜{data.get('manual_staff_price_reason') or '無備註'}",
        )

class SelfServiceStaffDiscountCouponModal(discord.ui.Modal, title="客服設定折扣"):
    discount_percent = discord.ui.TextInput(
        label="折後比例 %",
        placeholder="例如 90 = 9 折；不折扣留空或填 100",
        required=False,
        max_length=10,
    )

    discount_reason = discord.ui.TextInput(
        label="折扣原因",
        placeholder="例如 VIP折扣、店內活動、老客優惠、補償折扣",
        required=False,
        max_length=100,
    )

    cash_coupon_amount = discord.ui.TextInput(
        label="固定折扣金額",
        placeholder="例如 100；沒有固定折扣可留空或填 0",
        required=False,
        max_length=10,
    )

    cash_coupon_reason = discord.ui.TextInput(
        label="固定折扣原因 / 名稱",
        placeholder="例如 VIP優惠、活動優惠、生日優惠",
        required=False,
        max_length=100,
    )

    def __init__(self, customer_id: int, channel_id: int, panel_message_id: int | None = None):
        super().__init__()
        self.customer_id = customer_id
        self.channel_id = channel_id
        self.panel_message_id = panel_message_id

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以設定折扣。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})

        if not data.get("item"):
            await interaction.response.send_message("請先選擇訂單項目，再設定折扣。", ephemeral=True)
            return

        discount_percent_text = str(
            self.discount_percent.value
            or ""
        ).strip()

        try:
            discount_percent = _parse_discount_percent_text(
                discount_percent_text
            )
            coupon_amount = _parse_cash_amount_text(
                str(
                    self.cash_coupon_amount.value
                    or ""
                )
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if discount_percent_text:
            data["manual_discount_mode"] = "pay_rate"
            data["manual_discount_percent"] = discount_percent
            data["manual_discount_percent_override"] = True
            data["manual_discount_reason"] = str(
                self.discount_reason.value
                or ""
            ).strip()
        else:
            data.pop("manual_discount_mode", None)
            data.pop("manual_discount_percent", None)
            data.pop("manual_discount_reason", None)
            data["manual_discount_percent_override"] = False

        data["cash_coupon_amount"] = coupon_amount
        data["fixed_discount_amount"] = coupon_amount
        data["cash_coupon_reason"] = str(self.cash_coupon_reason.value or "").strip()
        data["manual_price_adjustment_set_by"] = interaction.user.id
        data["manual_price_adjustment_set_at"] = get_taipei_now_iso()

        remember_order_data(self.channel_id, data)

        await interaction.response.defer(ephemeral=True)

        edited_panel = False

        if isinstance(interaction.channel, discord.TextChannel) and self.panel_message_id:
            try:
                panel_message = await interaction.channel.fetch_message(self.panel_message_id)
                await panel_message.edit(
                    embed=build_self_service_panel_embed(self.customer_id, data, interaction.guild),
                    view=SelfServiceOrderView(
                        customer_id=self.customer_id,
                        channel_id=self.channel_id,
                        selected_category=data.get("category"),
                    ),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
                edited_panel = True
            except discord.HTTPException:
                edited_panel = False

        adjustment_note = []
        if discount_percent_text:
            adjustment_note.append(
                "客服百分比：折後 "
                f"{_format_percent_value(discount_percent)}%"
            )
        else:
            adjustment_note.append(
                "客服百分比已清除，改由顧客 VIP 等級自動套用。"
            )

        if coupon_amount > 0:
            adjustment_note.append(
                f"固定折扣：-{_format_plain_amount(coupon_amount)}"
                "（店內吸收，不影響打手分潤）"
            )

        await interaction.followup.send(
            "已設定折扣。"
            + ("\n" + "\n".join(adjustment_note) if adjustment_note else "")
            + ("" if edited_panel else "\n\n提醒：面板沒有自動刷新，請重新選一次數量即可刷新試算。"),
            ephemeral=True,
        )

        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "設定折扣",
            "｜".join(adjustment_note) if adjustment_note else "折後100%，無固定折扣",
        )

class SelfServiceSubmitNoteModal(discord.ui.Modal, title="送單前訂單備註"):
    note = discord.ui.TextInput(
        label="訂單備註",
        placeholder="可填可不填，例如：老闆特殊需求、時間、注意事項",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=800,
    )

    def __init__(self, customer_id: int, channel_id: int, panel_message_id: int | None = None):
        super().__init__()
        self.customer_id = int(customer_id)
        self.channel_id = int(channel_id)
        self.panel_message_id = panel_message_id

    async def on_submit(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("請聯繫客服送單。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
        note_text = str(self.note.value or "").strip()

        if note_text:
            data["staff_order_note"] = note_text
            data["staff_note"] = note_text
        else:
            data.pop("staff_order_note", None)
            data.pop("staff_note", None)

        data["staff_order_note_set_by"] = interaction.user.id
        data["staff_order_note_set_at"] = get_taipei_now_iso()
        remember_order_data(self.channel_id, data)

        await interaction.response.defer(ephemeral=True)

        try:
            response_text = await create_waiting_acceptance_order_from_self_service(
                interaction,
                customer_id=self.customer_id,
                channel_id=self.channel_id,
            )
        except ValueError as exc:
            failed_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
            provisional_started = _to_int(
                failed_data.get("provisional_dispatch_message_id"),
                None,
            ) is not None
            if not provisional_started:
                await interaction.followup.send(str(exc), ephemeral=True)
                return

            cleanup_warnings = await cleanup_failed_self_service_dispatch(
                interaction,
                channel_id=self.channel_id,
                data=failed_data,
                order_claims=ORDER_CLAIMS,
                default_dispatch_channel_id=DISPATCH_CHANNEL_ID,
                remember_order=remember_order_data,
                save_data=save_bot_data,
                delete_claim_row=delete_claim_row_from_db,
            )
            warning_text = ""
            if cleanup_warnings:
                warning_text = "\n⚠️ " + "；".join(cleanup_warnings)
            await interaction.followup.send(
                f"{exc}\n\n本次 provisional 派單已回滾，原本填好的草稿仍保留，可以修正後重新送出。"
                + warning_text,
                ephemeral=True,
            )
            return
        except Exception as exc:
            failed_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})
            provisional_started = _to_int(
                failed_data.get("provisional_dispatch_message_id"),
                None,
            ) is not None
            canonical_ready = (
                _to_int(failed_data.get("dispatch_message_id"), None) is not None
                and _to_int(failed_data.get("web_order_id"), None) is not None
                and str(failed_data.get("status") or "").strip().lower()
                == "waiting_acceptance"
            )
            print(
                f"[acceptance] 備註後建立 waiting_acceptance 自助單失敗 "
                f"channel_id={self.channel_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )

            if provisional_started:
                cleanup_warnings = await cleanup_failed_self_service_dispatch(
                    interaction,
                    channel_id=self.channel_id,
                    data=failed_data,
                    order_claims=ORDER_CLAIMS,
                    default_dispatch_channel_id=DISPATCH_CHANNEL_ID,
                    remember_order=remember_order_data,
                    save_data=save_bot_data,
                    delete_claim_row=delete_claim_row_from_db,
                )
                warning_text = ""
                if cleanup_warnings:
                    warning_text = "\n⚠️ " + "；".join(cleanup_warnings)
                await interaction.followup.send(
                    "送出等待接單失敗；本次 provisional 派單已回滾，原本填好的草稿仍保留，可以修正後重新送出。"
                    + warning_text,
                    ephemeral=True,
                )
                return

            if canonical_ready:
                await interaction.followup.send(
                    "訂單的 WebOrder／接單狀態已建立完成，但送單後續處理發生異常。"
                    "為避免重複派單，請先不要重新送出，通知客服主管確認此張單。",
                    ephemeral=True,
                )
                return

            await interaction.followup.send(
                "送出等待接單失敗；尚未建立可接單的派單，原本填好的草稿仍保留，請修正後再試或通知客服主管。",
                ephemeral=True,
            )
            return

        if isinstance(interaction.channel, discord.TextChannel) and self.panel_message_id:
            try:
                panel_message = await interaction.channel.fetch_message(self.panel_message_id)
                await panel_message.edit(
                    embed=build_self_service_panel_embed(self.customer_id, data, interaction.guild),
                    view=SelfServiceDispatchedView(),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            except discord.HTTPException:
                pass

        await log_self_service_proxy_action(
            interaction,
            self.customer_id,
            "送出等待接單",
            note_text or "無備註",
        )

        await interaction.followup.send(response_text, ephemeral=True)


class SelfServiceOrderView(discord.ui.View):
    def __init__(self, customer_id: int, channel_id: int, selected_category: str | None = None):
        super().__init__(timeout=86400)

        self.customer_id = customer_id
        self.channel_id = channel_id

        data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        category = selected_category or data.get("category")
        selected_item = data.get("item")
        selected_quantity = _to_int(data.get("quantity"), 1) or 1

        self.add_item(SelfServiceOrderCategorySelect(customer_id, channel_id, category))
        self.add_item(SelfServiceOrderItemSelect(customer_id, channel_id, category, selected_item))
        self.add_item(SelfServiceOrderDetailSelect(customer_id, channel_id))
        self.add_item(SelfServiceOrderQuantitySelect(customer_id, channel_id, selected_item, selected_quantity))

        try:
            current_rule = _get_rule_from_self_service_data(data) if selected_item else None
        except Exception:
            current_rule = None
        is_aw_collision = bool(current_rule and is_aw_collision_rule(current_rule))

        for child in self.children:
            custom_id = getattr(child, "custom_id", None)
            if custom_id == "self_service_order_specified_staff_button":
                child.disabled = not bool(current_rule and getattr(current_rule, "allow_specify", False))
            elif custom_id == "self_service_order_staff_price_button":
                child.disabled = not bool(
                    current_rule
                    and (is_self_service_staff_price_required(current_rule) or is_aw_collision)
                )
            elif custom_id == "self_service_order_point_benefit_button":
                child.disabled = bool(is_aw_collision or data.get("website_finance_settled"))
            elif custom_id == "self_service_order_staff_discount_coupon_button" and is_aw_collision:
                child.disabled = True
            elif custom_id == "self_service_order_go_payment_button":
                child.label = "客服確認送出" if data.get("reorder_source_order_id") else "送出等待接單"


    @discord.ui.button(
        label="選擇指定成員",
        style=discord.ButtonStyle.secondary,
        custom_id="self_service_order_specified_staff_button",
        row=4,
    )
    async def specified_staff(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇指定成員。", ephemeral=True)
            return

        if interaction.guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})

        if not data.get("item"):
            await interaction.response.send_message("請先選擇訂單項目，再選擇指定成員。", ephemeral=True)
            return

        try:
            rule = _get_rule_from_self_service_data(data)
            from services.order_rules import get_required_staff_count
            player_count = _to_int(data.get("player_count"), 1) or 1
            required_staff_count = get_required_staff_count(rule, player_count)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        except Exception as exc:
            await interaction.response.send_message(f"讀取指定規則失敗：{exc}", ephemeral=True)
            return

        can_specify_item = bool(getattr(rule, "allow_specify", False))

        if not can_specify_item:
            data.pop("specified_staff_ids", None)
            remember_order_data(self.channel_id, data)
            await interaction.response.send_message("這個項目不開放指定人員。", ephemeral=True)
            return

        if not _is_specify_preference(data.get("companion_preference")):
            data["companion_preference"] = "指定陪玩/打手"
            remember_order_data(self.channel_id, data)

        await interaction.response.defer(ephemeral=True)

        max_specified_count = int(rule.max_specified_count or required_staff_count or 1)
        max_specified_count = min(max_specified_count, int(required_staff_count or 1))
        entries = get_specified_staff_entries_for_rule(interaction.guild, rule)

        if not entries:
            await interaction.followup.send("目前找不到符合這張單可指定職位的人員，請確認打手身分組。", ephemeral=True)
            return

        panel_message_id = interaction.message.id if interaction.message is not None else None

        view = SelfServiceSpecifiedStaffDropdownView(
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            panel_message_id=panel_message_id,
            rule_key=rule.key,
            max_specified_count=max_specified_count,
            entries=entries,
            selected_ids=[str(item) for item in data.get("specified_staff_ids") or []],
        )

        await interaction.followup.send(
            content=view.build_message_content(),
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )


    @discord.ui.button(
        label="點數 / 會員福利",
        style=discord.ButtonStyle.secondary,
        custom_id="self_service_order_point_benefit_button",
        row=4,
    )
    async def point_benefit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not can_operate_self_service_order(interaction.user, self.customer_id):
            await interaction.response.send_message("只有開這張票口的用戶或客服可以選擇點數福利。", ephemeral=True)
            return

        if interaction.guild is None:
            await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})

        if not data.get("item"):
            await interaction.response.send_message("請先選擇訂單項目，再選擇點數福利。", ephemeral=True)
            return

        try:
            rule = _get_rule_from_self_service_data(data)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        allowed, reason = is_order_point_benefit_allowed_for_rule(rule, "discount_20", data)
        if not allowed:
            await interaction.response.send_message(reason or "這個分類不可使用點數福利。", ephemeral=True)
            return

        panel_message_id = interaction.message.id if interaction.message is not None else None

        view = SelfServicePointBenefitView(
            customer_id=self.customer_id,
            channel_id=self.channel_id,
            panel_message_id=panel_message_id,
            rule=rule,
        )

        await interaction.response.send_message(
            content=view.build_message_content(data),
            view=view,
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )


    @discord.ui.button(
        label="客服填價格",
        style=discord.ButtonStyle.secondary,
        custom_id="self_service_order_staff_price_button",
        row=4,
    )
    async def staff_price(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以填寫訂單價格。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(self.channel_id, {})

        if not data.get("item"):
            await interaction.response.send_message("請先選擇訂單項目，再填寫價格。", ephemeral=True)
            return

        try:
            rule = _get_rule_from_self_service_data(data)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if not is_self_service_staff_price_required(rule) and not is_aw_collision_rule(rule):
            await interaction.response.send_message("這個項目會自動試算價格，不需要客服手動填價格。", ephemeral=True)
            return

        panel_message_id = interaction.message.id if interaction.message is not None else None
        await interaction.response.send_modal(
            SelfServiceStaffPriceModal(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                panel_message_id=panel_message_id,
            )
        )


    @discord.ui.button(
        label="客服設定折扣",
        style=discord.ButtonStyle.secondary,
        custom_id="self_service_order_staff_discount_coupon_button",
        row=4,
    )
    async def staff_discount_coupon(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("只有客服可以設定折扣。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})

        if not data.get("item"):
            await interaction.response.send_message("請先選擇訂單項目，再設定折扣。", ephemeral=True)
            return

        try:
            rule = _get_rule_from_self_service_data(data)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        if is_aw_collision_rule(rule):
            await interaction.response.send_message(
                "AW代撞不套用客服折扣、會員或點數福利。",
                ephemeral=True,
            )
            return

        panel_message_id = interaction.message.id if interaction.message is not None else None
        await interaction.response.send_modal(
            SelfServiceStaffDiscountCouponModal(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                panel_message_id=panel_message_id,
            )
        )


    @discord.ui.button(
        label="送出等待接單",
        style=discord.ButtonStyle.success,
        custom_id="self_service_order_go_payment_button",
        row=4
    )
    async def go_payment(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_customer_staff(interaction.user):
            await interaction.response.send_message("請聯繫客服送單。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.get(self.channel_id, {})
        category = data.get("category")
        item = data.get("item")
        quantity = _to_int(data.get("quantity"), 1) or 1
        companion_preference = data.get("companion_preference")

        if category is None or item is None:
            await interaction.response.send_message("請先選擇訂單類別與訂單項目，再取得訂單金額。", ephemeral=True)
            return

        try:
            selected_rule = _get_rule_from_self_service_data(data)
            item_category = str(getattr(selected_rule, "category", "") or "")
        except ValueError:
            item_category = ORDER_ITEM_TO_CATEGORY.get(item)

        if item_category != category:
            await interaction.response.send_message(
                "你選擇的訂單類別與訂單項目不一致，請重新選擇。",
                ephemeral=True,
            )
            return

        quantity_meta = _self_service_quantity_meta(data, item)
        min_quantity = int(quantity_meta["min"])
        max_quantity = int(quantity_meta["max"])
        quantity_unit = str(quantity_meta["unit"])

        if min_quantity == max_quantity:
            quantity = min_quantity
            data["quantity"] = quantity
            remember_order_data(self.channel_id, data)
        elif quantity < min_quantity or quantity > max_quantity:
            await interaction.response.send_message(
                f"單數請選擇 {min_quantity}～{max_quantity} {quantity_unit}。",
                ephemeral=True,
            )
            return

        if companion_preference is None:
            companion_preference = "不指定陪玩/打手"
            data["companion_preference"] = companion_preference
            remember_order_data(self.channel_id, data)

        try:
            rule = _get_rule_from_self_service_data(data)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        normalize_self_service_staff_count(data)

        if getattr(rule, "player_count_enabled", False) and not _to_int(data.get("player_count")):
            await interaction.response.send_modal(SelfServicePlayerCountModal(self.customer_id, self.channel_id))
            return

        if getattr(rule, "allow_specify", False) and _is_specify_preference(companion_preference) and not data.get("specified_staff_ids"):
            await interaction.response.send_message(
                "老闆已選擇指定，但尚未完成指定成員選擇。請老闆先點「選擇指定成員」並按「完成」後，再送出等待接單。",
                ephemeral=True,
            )
            return

        if is_self_service_staff_price_required(rule) and get_self_service_staff_price(data) is None:
            await interaction.response.send_message("這張單需要客服先按「客服填價格」填寫價格，才能送出等待接單。", ephemeral=True)
            return

        panel_message_id = interaction.message.id if interaction.message is not None else None
        await interaction.response.send_modal(
            SelfServiceSubmitNoteModal(
                customer_id=self.customer_id,
                channel_id=self.channel_id,
                panel_message_id=panel_message_id,
            )
        )
