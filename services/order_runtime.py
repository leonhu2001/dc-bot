from __future__ import annotations

from typing import Any, Mapping

import discord


_CONFIGURED = False


def configure_order_runtime(namespace: Mapping[str, Any]) -> None:
    """Bind remaining bot-owned legacy dependencies after bot.py is loaded."""
    global _CONFIGURED

    for name, value in namespace.items():
        if name.startswith("__"):
            continue
        if name == "configure_order_runtime":
            continue
        globals()[name] = value

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
        data["category"] = selected_category
        data.pop("item_group", None)
        data.pop("item_detail_value", None)
        data.pop("item", None)
        data.pop("order_rule_key", None)
        data.pop("quantity", None)
        data.pop("player_count", None)
        data.pop("specified_staff_ids", None)
        data.pop("companion_preference", None)
        data.pop("payment_method", None)
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
        data["item_group"] = selected_group
        data.pop("item_detail_value", None)
        data.pop("item", None)
        data.pop("order_rule_key", None)
        data.pop("player_count", None)
        data.pop("specified_staff_ids", None)
        data.pop("payment_method", None)
        data["companion_preference"] = "不指定陪玩/打手"

        details = get_order_item_details_for_group(data.get("category"), selected_group)

        # 只有一個規格時直接選好，但第三欄仍會顯示該規格。
        if len(details) == 1:
            detail = details[0]
            data["item_detail_value"] = str(detail.get("value") or "")
            data["item"] = detail["item"]
            data["order_rule_key"] = detail["rule_key"]
            if detail.get("player_count") is not None:
                data["player_count"] = int(detail["player_count"])
            data["quantity"] = int(detail.get("min_quantity") or 1)
        else:
            data["quantity"] = 1

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

        data["item_detail_value"] = str(detail.get("value") or "")
        data["item"] = detail["item"]
        data["order_rule_key"] = detail["rule_key"]

        if detail.get("player_count") is not None:
            data["player_count"] = int(detail["player_count"])
        else:
            data.pop("player_count", None)

        data["quantity"] = int(detail.get("min_quantity") or 1)
        data.pop("specified_staff_ids", None)
        data.pop("payment_method", None)
        data["companion_preference"] = "不指定陪玩/打手"
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


class DispatchCancelClaimButton(discord.ui.Button):
    def __init__(self, disabled: bool = False):
        super().__init__(
            label="取消接單",
            style=discord.ButtonStyle.danger,
            custom_id="dispatch_cancel_claim",
            disabled=disabled
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view

        if not isinstance(view, DispatchClaimView):
            await interaction.response.send_message("接單面板狀態異常，請重新派單。", ephemeral=True)
            return

        await view.cancel_claim(interaction)




def sync_single_discord_claim_event_to_web(interaction, claim_type: str, action: str) -> None:
    """把 Discord 接單按鈕單一操作同步到網站。

    action:
    - claim：只新增目前這個人
    - unclaim：只移除目前這個人
    """
    try:
        from shared.web_order_sync import apply_discord_claim_event_to_web

        if interaction.message is None:
            return

        role_type = "booster"

        apply_discord_claim_event_to_web(
            dispatch_message_id=interaction.message.id,
            worker_discord_id=interaction.user.id,
            worker_display_name=getattr(interaction.user, "display_name", None) or getattr(interaction.user, "name", None) or str(interaction.user.id),
            role_type=role_type,
            action=action,
        )
    except Exception as exc:
        print(
            f"[web-sync] Discord 接單事件同步網站失敗 "
            f"message_id={getattr(getattr(interaction, 'message', None), 'id', None)} "
            f"user_id={getattr(getattr(interaction, 'user', None), 'id', None)} "
            f"claim_type={claim_type} action={action}: {exc}"
        )


def _get_pending_order_point_benefit_info(data: dict) -> dict | None:
    # zYao 3C3B website finance point safety v1
    if data.get("website_finance_settled"):
        return None

    benefit_key = str(
        data.get("point_benefit_key")
        or data.get("selected_point_benefit_key")
        or ""
    ).strip()

    if not benefit_key:
        return None

    item = get_order_point_item(benefit_key)

    benefit_name = str(
        data.get("point_benefit_name")
        or (item or {}).get("name")
        or benefit_key
    )

    benefit_cost = _to_int(
        data.get("point_benefit_cost"),
        _to_int((item or {}).get("cost"), 0) if item else 0,
    ) or 0

    if benefit_cost <= 0:
        return None

    return {
        "key": benefit_key,
        "name": benefit_name,
        "cost": int(benefit_cost),
    }


def precheck_order_point_benefit_for_payment(data: dict, customer_id: int) -> None:
    info = _get_pending_order_point_benefit_info(data)

    if info is None:
        return

    if data.get("point_benefit_redeemed"):
        return

    reward_data = get_customer_reward_data(int(customer_id))
    before_points = int(get_current_reward_points(reward_data))

    if before_points < int(info["cost"]):
        raise ValueError(
            f"點數不足，無法使用「{info['name']}」。"
            f"需要 {info['cost']} 點，目前只有 {before_points} 點。"
        )


async def redeem_order_point_benefit_on_payment(
    *,
    interaction: discord.Interaction,
    data: dict,
    customer_id: int,
    channel_id: int,
) -> str | None:
    info = _get_pending_order_point_benefit_info(data)

    if info is None:
        return None

    if data.get("point_benefit_redeemed"):
        before_points = _to_int(data.get("point_benefit_before_points"), 0) or 0
        after_points = _to_int(data.get("point_benefit_after_points"), 0) or 0
        return f"點數福利已扣點：{info['cost']} 點｜{info['name']}（{before_points} → {after_points}）"

    reward_data = get_customer_reward_data(int(customer_id))
    before_points = int(get_current_reward_points(reward_data))

    if before_points < int(info["cost"]):
        raise ValueError(
            f"點數不足，無法使用「{info['name']}」。"
            f"需要 {info['cost']} 點，目前只有 {before_points} 點。"
        )

    logs = reward_data.setdefault("point_adjustment_logs", [])

    if not isinstance(logs, list):
        logs = []
        reward_data["point_adjustment_logs"] = logs

    reward_data["point_adjustment"] = int(reward_data.get("point_adjustment", 0) or 0) - int(info["cost"])
    after_points = int(get_current_reward_points(reward_data))
    reward_data["points"] = after_points

    logs.append(
        {
            "created_at": get_taipei_now_iso(),
            "delta": -int(info["cost"]),
            "before_points": before_points,
            "after_points": after_points,
            "reason": f"訂單點數福利：{info['name']}",
            "source": "order_point_benefit",
            "order_channel_id": int(channel_id),
            "order_no": data.get("order_no") or data.get("receipt_id"),
            "benefit_key": info["key"],
            "benefit_name": info["name"],
            "operator_id": int(getattr(interaction.user, "id", 0) or 0),
        }
    )

    CUSTOMER_REWARDS[int(customer_id)] = reward_data

    data["point_benefit_redeemed"] = True
    data["point_benefit_redeemed_at"] = get_taipei_now_iso()
    data["point_benefit_before_points"] = before_points
    data["point_benefit_after_points"] = after_points
    data["point_benefit_redeemed_by"] = int(getattr(interaction.user, "id", 0) or 0)

    remember_order_data(channel_id, data)
    save_bot_data()

    try:
        await send_order_log(
            interaction.guild,
            title="訂單點數福利已扣點",
            fields=[
                ("顧客", f"<@{customer_id}>", True),
                ("福利", f"{info['cost']} 點｜{info['name']}", True),
                ("點數", f"{before_points} → {after_points}", True),
                ("訂單", str(data.get("order_no") or data.get("receipt_id") or channel_id), False),
            ],
            color=discord.Color.gold(),
        )
    except Exception as exc:
        print(f"[points] 訂單點數福利扣點日誌失敗 channel_id={channel_id}: {exc}")

    return f"點數福利已扣 {info['cost']} 點：{info['name']}（{before_points} → {after_points}）"


def precheck_order_loyalty_coupon_for_payment(data: dict, customer_id: int) -> None:
    coupon_id = _to_int(data.get("selected_loyalty_coupon_id"), None)
    if coupon_id is None:
        return
    from services.loyalty_benefits import validate_coupon_for_order
    validate_coupon_for_order(
        coupon_id, customer_id=customer_id,
        rule_key=str(data.get("order_rule_key") or ""),
        player_count=_to_int(data.get("player_count"), 1) or 1,
        allow_reserved=True,
    )


def consume_order_loyalty_coupon_on_payment(data: dict, customer_id: int, channel_id: int) -> str | None:
    coupon_id = _to_int(data.get("selected_loyalty_coupon_id"), None)
    if coupon_id is None:
        return None
    from services.loyalty_benefits import consume_coupon
    used_order_key = (
        f"WEB-{int(data['web_order_id'])}"
        if _to_int(data.get("web_order_id"), None) is not None
        else f"DC-{int(channel_id)}"
    )
    coupon = consume_coupon(
        coupon_id, customer_id=customer_id, used_order_key=used_order_key,
    )
    data["loyalty_coupon_used"] = True
    data["loyalty_coupon_used_at"] = get_taipei_now_iso()
    data["loyalty_coupon_name"] = str(coupon.get("display_name") or data.get("loyalty_coupon_name") or "累積福利")
    remember_order_data(channel_id, data)
    save_bot_data()
    return f"累積福利已套用：{data['loyalty_coupon_name']}"


def _order_requires_credentials(data: dict | None) -> bool:
    if not isinstance(data, dict):
        return False

    rule_key = str(data.get("order_rule_key") or "").strip().lower()
    category = str(data.get("category") or "").strip().lower()
    return rule_key.startswith("farm_") or category == "farm"


async def _credential_user_for_id(
    guild: discord.Guild | None,
    user_id: int,
) -> discord.Member | discord.User | None:
    if guild is not None:
        member = guild.get_member(int(user_id))
        if member is not None:
            return member

        try:
            member = await fetch_member_safely(guild, int(user_id))
        except Exception:
            member = None

        if member is not None:
            return member

    user = bot.get_user(int(user_id))
    if user is not None:
        return user

    try:
        return await bot.fetch_user(int(user_id))
    except Exception:
        return None


def _credential_display_name(
    guild: discord.Guild | None,
    user: discord.Member | discord.User | None,
    user_id: int | str,
) -> str:
    try:
        numeric_id = int(user_id)
    except (TypeError, ValueError):
        numeric_id = 0

    if guild is not None and numeric_id:
        member = guild.get_member(numeric_id)
        if member is not None:
            return str(member.display_name)

    if user is not None:
        return str(
            getattr(user, "display_name", None)
            or getattr(user, "global_name", None)
            or getattr(user, "name", None)
            or user_id
        )

    return str(user_id)


async def _resolve_credential_owner(
    guild: discord.Guild | None,
) -> discord.Member | discord.User | None:
    if int(CREDENTIAL_OWNER_USER_ID or 0) > 0:
        return await _credential_user_for_id(guild, int(CREDENTIAL_OWNER_USER_ID))

    try:
        app_info = await bot.application_info()
    except Exception:
        app_info = None

    owner = getattr(app_info, "owner", None) if app_info is not None else None
    if owner is not None:
        owner_id = _to_int(getattr(owner, "id", None))
        if owner_id is not None:
            resolved = await _credential_user_for_id(guild, owner_id)
            return resolved or owner

    team = getattr(app_info, "team", None) if app_info is not None else None
    team_owner_id = _to_int(getattr(team, "owner_id", None)) if team is not None else None
    if team_owner_id is not None:
        return await _credential_user_for_id(guild, team_owner_id)

    return None


async def revoke_order_credential_messages(
    order_id: int,
    *,
    reason: str,
    ticket_channel: discord.TextChannel | None = None,
    notify_customer: bool = True,
) -> dict:
    from services.order_credentials import (
        get_order_context,
        list_active_deliveries,
        mark_delivery_revoked,
    )

    deliveries = list_active_deliveries(int(order_id))
    context = get_order_context(int(order_id)) or {}

    deleted_count = 0
    failed_count = 0
    recipient_lines: list[str] = []

    for delivery in deliveries:
        recipient_id = _to_int(delivery.get("recipient_discord_id"))
        message_id = _to_int(delivery.get("dm_message_id"))
        recipient_type = str(delivery.get("recipient_type") or "recipient")
        recipient_name = str(
            delivery.get("recipient_display_name")
            or delivery.get("recipient_discord_id")
            or "未知"
        )

        label = "店長" if recipient_type == "owner" else "接單人員"
        recipient_lines.append(f"・{label}：{recipient_name}")

        if recipient_id is None or message_id is None:
            mark_delivery_revoked(
                int(delivery["id"]),
                status="metadata_missing",
                reason=reason,
            )
            deleted_count += 1
            continue

        user = await _credential_user_for_id(
            ticket_channel.guild if ticket_channel is not None else bot.get_guild(GUILD_ID),
            recipient_id,
        )

        if user is None:
            failed_count += 1
            continue

        try:
            dm_channel = getattr(user, "dm_channel", None)
            if dm_channel is None:
                dm_channel = await user.create_dm()

            try:
                message = await dm_channel.fetch_message(message_id)
                await message.delete()
                revoke_status = "deleted"
            except discord.NotFound:
                revoke_status = "already_missing"

            mark_delivery_revoked(
                int(delivery["id"]),
                status=revoke_status,
                reason=reason,
            )
            deleted_count += 1
        except (discord.Forbidden, discord.HTTPException):
            failed_count += 1
        except Exception:
            failed_count += 1

    if notify_customer and deliveries:
        customer_id = _to_int(context.get("customer_discord_id"))
        order_no = str(
            context.get("bot_order_no")
            or f"WEB-{order_id}"
        )
        unique_recipient_lines = list(dict.fromkeys(recipient_lines))

        if failed_count == 0:
            body = (
                f"✅ **帳號資料已銷毀**\\n"
                f"訂單：**{order_no}**\\n\\n"
                "系統已撤回所有由魔丸娛樂機器人發送的帳號密碼訊息。\\n"
                "本次帳號與密碼內容從未寫入魔丸娛樂資料庫；"
                "系統只保留不含帳密的授權與撤回紀錄。"
            )
        else:
            body = (
                f"⚠️ **帳號資料撤回未完全成功**\\n"
                f"訂單：**{order_no}**\\n\\n"
                f"已撤回 **{deleted_count}** 則，另有 **{failed_count}** 則 Discord 私訊目前無法確認撤回。\\n"
                "魔丸娛樂系統本身未保存帳號或密碼內容。"
            )

        if unique_recipient_lines:
            body += "\\n\\n原授權人員：\\n" + "\\n".join(unique_recipient_lines)

        body += (
            f"\\n\\n處理時間：{get_taipei_now_iso()}\\n"
            "🔒 為了最高帳號安全性，服務完成後仍建議更換密碼。"
        )

        delivered_notice = False
        if customer_id is not None:
            customer_user = await _credential_user_for_id(
                ticket_channel.guild if ticket_channel is not None else bot.get_guild(GUILD_ID),
                customer_id,
            )
            if customer_user is not None:
                try:
                    await customer_user.send(body)
                    delivered_notice = True
                except Exception:
                    delivered_notice = False

        if not delivered_notice and ticket_channel is not None:
            try:
                mention = f"<@{customer_id}> " if customer_id is not None else ""
                await ticket_channel.send(
                    mention + body,
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
            except Exception:
                pass

    return {
        "total": len(deliveries),
        "deleted": deleted_count,
        "failed": failed_count,
    }


async def ensure_order_credential_request(
    *,
    channel: discord.TextChannel,
    customer_id: int,
    data: dict,
) -> discord.Message | None:
    if not _order_requires_credentials(data):
        return None

    existing_message_id = _to_int(data.get("credential_request_message_id"))

    if existing_message_id is not None:
        try:
            existing_message = await channel.fetch_message(existing_message_id)
            await existing_message.edit(view=OrderCredentialEntryView())
            return existing_message
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    embed = discord.Embed(
        title="🔐 代肝／代解登入資料",
        description=(
            "此訂單需要登入您的遊戲帳號。\\n\\n"
            "帳號與密碼**不會寫入魔丸娛樂資料庫**，只會在您送出時由機器人"
            "直接私訊給目前接單人員與店長。\\n"
            "結單或取消後，機器人會自動撤回這些帳密私訊；"
            "系統只保留不含帳密內容的授權／撤回紀錄。"
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="誰會取得帳密？",
        value="目前實際接單人員與店長。送出後會明確列出姓名。",
        inline=False,
    )
    embed.add_field(
        name="安全提醒",
        value="服務完成後仍建議更換密碼；若接單人員異動，請重新提交登入資料。",
        inline=False,
    )

    message = await channel.send(
        content=f"<@{customer_id}> 請填寫本單登入資料。",
        embed=embed,
        view=OrderCredentialEntryView(),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False,
        ),
    )

    data["credential_request_message_id"] = message.id
    data["credential_request_created_at"] = get_taipei_now_iso()
    remember_order_data(channel.id, data)
    save_bot_data()
    return message


class OrderCredentialModal(discord.ui.Modal, title="代肝／代解登入資料"):
    account = discord.ui.TextInput(
        label="登入帳號",
        placeholder="請輸入此訂單使用的遊戲登入帳號",
        required=True,
        max_length=200,
    )
    password = discord.ui.TextInput(
        label="登入密碼",
        placeholder="請輸入此訂單使用的登入密碼",
        required=True,
        max_length=200,
    )
    login_note = discord.ui.TextInput(
        label="登入方式／備註（選填）",
        placeholder="例如 Steam、Garena、Google 登入，或其他登入注意事項",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=500,
    )

    def __init__(self, order_channel_id: int):
        super().__init__()
        self.order_channel_id = int(order_channel_id)

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("無法確認此訂單票口。", ephemeral=True)
            return

        channel = interaction.channel
        data = SELF_SERVICE_ORDER_SELECTIONS.get(self.order_channel_id)

        if not isinstance(data, dict):
            await interaction.response.send_message("找不到這張訂單資料，請通知客服。", ephemeral=True)
            return

        customer_id = _to_int(data.get("customer_id"))
        if customer_id is None or int(interaction.user.id) != customer_id:
            await interaction.response.send_message("只有此訂單的老闆可以提交登入資料。", ephemeral=True)
            return

        if str(data.get("status") or "").lower() != "active":
            await interaction.response.send_message("訂單尚未付款成立，或目前已不在進行中。", ephemeral=True)
            return

        if not _order_requires_credentials(data):
            await interaction.response.send_message("這張訂單不需要提交登入資料。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        from services.order_credentials import (
            get_active_worker_ids,
            get_order_context,
            get_order_id_by_ticket_channel,
            record_delivery,
        )

        order_id = _to_int(data.get("web_order_id"))
        if order_id is None:
            order_id = get_order_id_by_ticket_channel(self.order_channel_id)

        if order_id is None:
            await interaction.followup.send("找不到網站訂單資料，請通知客服。", ephemeral=True)
            return

        context = get_order_context(order_id) or {}
        if str(context.get("status") or "").lower() != "active":
            await interaction.followup.send("這張訂單目前不是進行中狀態。", ephemeral=True)
            return

        worker_ids = get_active_worker_ids(order_id)
        if not worker_ids:
            await interaction.followup.send("目前找不到正式接單人員，請通知客服確認接單狀態。", ephemeral=True)
            return

        owner_user = await _resolve_credential_owner(interaction.guild)
        owner_id = _to_int(getattr(owner_user, "id", None))

        if owner_user is None or owner_id is None:
            await interaction.followup.send(
                "目前無法確認店長 Discord 帳號，登入資料尚未送出，請通知客服。",
                ephemeral=True,
            )
            return

        # 重新提交時，先撤回上一輪私訊；帳密內容本身沒有資料庫副本。
        await revoke_order_credential_messages(
            order_id,
            reason="resubmitted",
            ticket_channel=channel,
            notify_customer=False,
        )

        recipients: list[tuple[int, str, discord.Member | discord.User]] = []
        seen_ids: set[int] = set()

        for worker_id_text in worker_ids:
            worker_id = _to_int(worker_id_text)
            if worker_id is None or worker_id in seen_ids:
                continue
            worker_user = await _credential_user_for_id(interaction.guild, worker_id)
            if worker_user is None:
                await revoke_order_credential_messages(
                    order_id,
                    reason="delivery_failed",
                    ticket_channel=channel,
                    notify_customer=False,
                )
                await interaction.followup.send(
                    f"無法私訊其中一位接單人員（ID {worker_id}），帳密尚未完成交付。請通知客服。",
                    ephemeral=True,
                )
                return
            seen_ids.add(worker_id)
            recipients.append((worker_id, "worker", worker_user))

        if owner_id not in seen_ids:
            seen_ids.add(owner_id)
            recipients.append((owner_id, "owner", owner_user))

        order_no = str(
            data.get("order_no")
            or data.get("receipt_id")
            or context.get("bot_order_no")
            or f"WEB-{order_id}"
        )
        account_value = str(self.account.value or "").strip()
        password_value = str(self.password.value or "")
        note_value = str(self.login_note.value or "").strip()

        delivered_display: list[str] = []

        for recipient_id, recipient_type, recipient in recipients:
            display_name = _credential_display_name(
                interaction.guild,
                recipient,
                recipient_id,
            )
            label = "店長" if recipient_type == "owner" else "接單人員"

            credential_embed = discord.Embed(
                title="🔐 魔丸娛樂｜臨時帳號授權",
                description=(
                    "此登入資料僅限本訂單服務使用。\\n"
                    "完成、取消或重新提交後，機器人會嘗試自動撤回本訊息。"
                ),
                color=discord.Color.orange(),
            )
            credential_embed.add_field(name="訂單", value=order_no, inline=False)
            credential_embed.add_field(name="登入帳號", value=account_value[:1024], inline=False)
            credential_embed.add_field(name="登入密碼", value=password_value[:1024], inline=False)
            if note_value:
                credential_embed.add_field(
                    name="登入方式／備註",
                    value=note_value[:1024],
                    inline=False,
                )
            credential_embed.set_footer(text="請勿轉傳、截圖或用於本訂單以外用途")

            try:
                dm_message = await recipient.send(embed=credential_embed)
            except Exception:
                await revoke_order_credential_messages(
                    order_id,
                    reason="delivery_failed",
                    ticket_channel=channel,
                    notify_customer=False,
                )
                await interaction.followup.send(
                    f"無法將登入資料交付給{label}「{display_name}」。"
                    "已撤回本次其他已送出的帳密訊息，請通知客服。",
                    ephemeral=True,
                )
                return

            record_delivery(
                order_id=order_id,
                submitted_by_discord_id=customer_id,
                recipient_discord_id=recipient_id,
                recipient_type=recipient_type,
                recipient_display_name=display_name,
                dm_channel_id=dm_message.channel.id,
                dm_message_id=dm_message.id,
            )
            delivered_display.append(f"・{label}：{display_name}")

        data["web_order_id"] = int(order_id)
        data["credential_last_submitted_at"] = get_taipei_now_iso()
        data["credential_delivery_count"] = len(recipients)
        remember_order_data(self.order_channel_id, data)
        save_bot_data()

        receipt_text = (
            f"🛡️ **帳號資料已安全交付**\\n"
            f"訂單：**{order_no}**\\n\\n"
            "目前取得本次帳號資料的人員：\\n"
            + "\\n".join(delivered_display)
            + "\\n\\n除上述人員外，機器人未將帳密送給其他店內成員。"
            "\\n帳號與密碼內容未寫入魔丸娛樂資料庫；"
            "結單或取消後機器人會自動撤回這些帳密私訊。"
        )

        customer_notice_sent = False
        try:
            await interaction.user.send(receipt_text)
            customer_notice_sent = True
        except Exception:
            customer_notice_sent = False

        if not customer_notice_sent:
            try:
                await channel.send(
                    f"<@{customer_id}> {receipt_text}",
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
            except Exception:
                pass

        await interaction.followup.send(
            "登入資料已交付完成。\\n\\n" + "\\n".join(delivered_display),
            ephemeral=True,
        )


class OrderCredentialEntryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="🔐 填寫／更新帳號資料",
        style=discord.ButtonStyle.primary,
        custom_id="order_credentials:submit",
    )
    async def submit_credentials(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("請在原訂單票口操作。", ephemeral=True)
            return

        data = SELF_SERVICE_ORDER_SELECTIONS.get(interaction.channel.id)
        if not isinstance(data, dict):
            await interaction.response.send_message("找不到這張訂單資料，請通知客服。", ephemeral=True)
            return

        customer_id = _to_int(data.get("customer_id"))
        if customer_id is None or int(interaction.user.id) != customer_id:
            await interaction.response.send_message("只有此訂單的老闆可以填寫登入資料。", ephemeral=True)
            return

        if str(data.get("status") or "").lower() != "active":
            await interaction.response.send_message("這張訂單目前不是進行中狀態。", ephemeral=True)
            return

        if not _order_requires_credentials(data):
            await interaction.response.send_message("這張訂單不需要登入資料。", ephemeral=True)
            return

        await interaction.response.send_modal(
            OrderCredentialModal(interaction.channel.id)
        )


async def finalize_accepted_pending_payment(
    *,
    interaction: discord.Interaction,
    customer_id: int,
    channel_id: int,
) -> None:
    guild = interaction.guild

    if guild is None:
        await interaction.response.send_message("這個功能只能在伺服器內使用。", ephemeral=True)
        return

    if not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
        return

    data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})

    if str(data.get("status") or "").lower() != "accepted_pending_pay":
        await interaction.response.send_message("這張單目前不是等待付款狀態。", ephemeral=True)
        return

    if data.get("payment_finalizing"):
        await interaction.response.send_message("這張單正在確認付款，請稍等，不要重複送出。", ephemeral=True)
        return

    payment_method = data.get("payment_method")

    if not payment_method or str(payment_method) in {"待付款", "未紀錄"}:
        await interaction.response.send_message("請先選擇付款方式，再按送出。", ephemeral=True)
        return

    amount = _to_int(data.get("amount"), 0) or _to_int(data.get("total_amount"), 0) or 0

    if amount < 0:
        await interaction.response.send_message("訂單金額異常，請通知客服確認。", ephemeral=True)
        return

    dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID

    if dispatch_message_id is None:
        await interaction.response.send_message("找不到派單訊息，請通知客服確認。", ephemeral=True)
        return

    external_review_methods = {"街口", "轉帳"}

    if str(payment_method) in external_review_methods and not data.get("payment_review_approved"):
        if data.get("payment_review_pending"):
            await interaction.response.send_message(
                "這筆付款已送出網站審核，請不要重複送出。\n"
                "請將付款截圖直接傳在此票口，方便客服核對。",
                ephemeral=True,
            )
            return

        web_order_id = _to_int(data.get("web_order_id"))

        if web_order_id is None:
            try:
                from shared.order_acceptance import find_acceptance_order_id_by_dispatch_message_id
                web_order_id = find_acceptance_order_id_by_dispatch_message_id(dispatch_message_id)
            except Exception:
                web_order_id = None

        if web_order_id is None:
            await interaction.response.send_message(
                "找不到這張訂單的網站資料，暫時無法送出付款審核，請通知客服。",
                ephemeral=True,
            )
            return

        customer_member_for_review = guild.get_member(customer_id)
        customer_display_name = (
            getattr(customer_member_for_review, "display_name", None)
            or getattr(customer_member_for_review, "global_name", None)
            or getattr(customer_member_for_review, "name", None)
            or str(data.get("customer_display_name") or "").strip()
            or "未知顧客"
        )

        try:
            from services.payment_reviews import (
                create_payment_review,
                set_payment_review_notification,
            )

            review = create_payment_review(
                source_type="order",
                source_id=web_order_id,
                ticket_channel_id=channel_id,
                customer_discord_id=customer_id,
                customer_display_name=customer_display_name,
                amount=amount,
                payment_method=str(payment_method),
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        data["web_order_id"] = int(web_order_id)
        data["payment_review_id"] = int(review["id"])
        data["payment_review_no"] = str(review.get("review_no") or "")
        data["payment_review_pending"] = True
        data["payment_review_submitted_at"] = get_taipei_now_iso()
        data["payment_review_submitted_by"] = int(getattr(interaction.user, "id", 0) or 0)
        remember_order_data(channel_id, data)
        save_bot_data()

        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        category_label = str(
            data.get("category_label")
            or ORDER_CATEGORY_LABELS.get(
                data.get("category"),
                data.get("category") or "未紀錄",
            )
        )
        item = str(data.get("item") or "未紀錄")
        quantity = _to_int(data.get("quantity"), 1) or 1
        companion_preference = data.get("companion_preference")

        pending_embed = build_payment_method_embed(
            customer_id=customer_id,
            category_label=category_label,
            item=item,
            quantity=quantity,
            payment_method=str(payment_method),
            companion_preference=companion_preference,
            amount=amount,
            receiver_text=str(data.get("accepted_staff_display_text") or "").strip() or None,
        )
        pending_embed.add_field(
            name="付款狀態",
            value=(
                "已送出網站審核，等待客服確認收款。\n"
                "請將付款截圖直接傳在本票口，方便客服核對。"
            ),
            inline=False,
        )

        payment_channel_id = _to_int(
            data.get("payment_channel_id"),
            interaction.channel.id,
        ) or interaction.channel.id
        payment_message_id = _to_int(data.get("payment_message_id"))
        payment_channel = guild.get_channel(payment_channel_id)

        if isinstance(payment_channel, discord.TextChannel) and payment_message_id is not None:
            try:
                payment_message = await payment_channel.fetch_message(payment_message_id)
                await payment_message.edit(
                    embed=pending_embed,
                    view=PaymentMethodView(
                        customer_id=customer_id,
                        channel_id=channel_id,
                        submitted=True,
                        selected_method=str(payment_method),
                    ),
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
            except discord.HTTPException:
                pass

        review_notice = await interaction.channel.send(
            (
                f"<@{customer_id}> ✅ **付款資料已送出審核**\n"
                f"付款方式：**{payment_method}**｜金額：**{amount:,}T**\n\n"
                "📎 **請將轉帳／街口付款截圖直接傳在此票口**，"
                "方便客服核對後到網站完成付款審核。\n"
                "客服確認前，訂單不會正式成立。"
            ),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )

        data["payment_review_notification_message_id"] = review_notice.id
        remember_order_data(channel_id, data)
        save_bot_data()

        try:
            set_payment_review_notification(int(review["id"]), review_notice.id)
        except Exception:
            pass

        await interaction.followup.send(
            "付款已送出網站審核。請記得把付款截圖貼在這個票口，等待客服確認。",
            ephemeral=True,
        )
        return

    data["payment_finalizing"] = True
    remember_order_data(channel_id, data)

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    try:
        category_label = str(data.get("category_label") or ORDER_CATEGORY_LABELS.get(data.get("category"), data.get("category") or "未紀錄"))
        item = str(data.get("item") or "未紀錄")
        quantity = _to_int(data.get("quantity"), 1) or 1
        companion_preference = data.get("companion_preference")
        staff_note = str(data.get("staff_note") or data.get("customer_service_note") or "").strip() or None

        customer_member = guild.get_member(customer_id)
        if customer_member is None:
            try:
                customer_member = await fetch_member_safely(guild, customer_id)
            except Exception:
                customer_member = None

        order_point_benefit_result = None
        order_loyalty_benefit_result = None

        try:
            precheck_order_point_benefit_for_payment(data, customer_id)
            precheck_order_loyalty_coupon_for_payment(data, customer_id)
        except ValueError as exc:
            data.pop("payment_finalizing", None)
            remember_order_data(channel_id, data)
            save_bot_data()
            message = str(exc)
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return

        if payment_method == WALLET_PAYMENT_METHOD:
            existing_wallet_tx_id = data.get("wallet_transaction_id")

            if not existing_wallet_tx_id:
                try:
                    wallet_tx = adjust_customer_wallet_balance(
                        customer_id=customer_id,
                        amount=-amount,
                        tx_type="payment",
                        operator=interaction.user,
                        order_channel_id=channel_id,
                        order_no=data.get("order_no") or data.get("receipt_id"),
                        note=f"訂單扣款：{item}",
                    )
                except ValueError as exc:
                    data.pop("payment_finalizing", None)
                    remember_order_data(channel_id, data)
                    await interaction.followup.send(str(exc), ephemeral=True)
                    return

                data["wallet_transaction_id"] = wallet_tx["id"]
                data["wallet_paid_amount"] = amount
                data["wallet_balance_before"] = wallet_tx["balance_before"]
                data["wallet_balance_after"] = wallet_tx["balance_after"]
                remember_order_data(channel_id, data)

                await send_wallet_log(
                    guild,
                    title="錢包訂單扣款",
                    customer=customer_member if customer_member is not None else interaction.user,
                    operator=interaction.user,
                    tx=wallet_tx,
                )

        try:
            order_point_benefit_result = await redeem_order_point_benefit_on_payment(
                interaction=interaction,
                data=data,
                customer_id=customer_id,
                channel_id=channel_id,
            )
        except ValueError as exc:
            data.pop("payment_finalizing", None)
            remember_order_data(channel_id, data)
            save_bot_data()
            message = str(exc)
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return

        try:
            order_loyalty_benefit_result = consume_order_loyalty_coupon_on_payment(
                data, customer_id, channel_id
            )
        except ValueError as exc:
            data.pop("payment_finalizing", None)
            remember_order_data(channel_id, data)
            save_bot_data()
            await interaction.followup.send(str(exc), ephemeral=True)
            return

        data["amount"] = amount
        data["total_amount"] = amount
        data["amount_text"] = _format_plain_amount(amount) if "_format_plain_amount" in globals() else format_t_amount(amount)
        data["payment_submitted_at"] = get_taipei_now_iso()
        data["payment_submitted_by"] = interaction.user.id
        data["closed"] = False
        data["payment_processing"] = True
        remember_order_data(channel_id, data)

        reward_result = await add_customer_reward_from_order(
            guild=guild,
            order_channel_id=channel_id,
            customer_id=customer_id,
            amount_text=str(amount),
            notify_channel=interaction.channel,
        )

        receipt_staff_member = interaction.user
        amount_set_by = _to_int(data.get("amount_set_by"))

        if amount_set_by is not None:
            possible_staff_member = guild.get_member(amount_set_by)
            if possible_staff_member is not None:
                receipt_staff_member = possible_staff_member

        receipt_id, receipt_message = await ensure_payment_submit_receipt(
            guild=guild,
            order_channel=interaction.channel,
            customer_id=customer_id,
            customer_member=customer_member,
            staff_member=receipt_staff_member,
            category_label=category_label,
            item=item,
            quantity=quantity,
            amount=amount,
            payment_method=payment_method,
            companion_preference=companion_preference,
        )

        if receipt_id:
            data["receipt_id"] = receipt_id
            data["order_no"] = receipt_id

        if receipt_message is not None:
            data["receipt_message_id"] = receipt_message.id
            data["receipt_channel_id"] = receipt_message.channel.id

        web_order_id = _to_int(data.get("web_order_id"))

        if web_order_id is None:
            try:
                from shared.order_acceptance import find_acceptance_order_id_by_dispatch_message_id
                web_order_id = find_acceptance_order_id_by_dispatch_message_id(dispatch_message_id)
            except Exception:
                web_order_id = None

        if web_order_id is not None:
            data["web_order_id"] = int(web_order_id)
            from shared.order_acceptance import promote_acceptance_claims_to_assignments
            payout_base_amount = _to_int(data.get("payout_base_amount"), amount) or amount
            promoted_count = promote_acceptance_claims_to_assignments(
                order_id=web_order_id,
                payment_method=str(payment_method),
                amount=amount,
                payout_base_amount=payout_base_amount,
                original_amount=_to_int(data.get("original_amount"), payout_base_amount) or payout_base_amount,
                manual_discount_amount=_to_int(data.get("manual_discount_amount"), 0) or 0,
                cash_coupon_amount=_to_int(data.get("cash_coupon_amount"), 0) or 0,
                store_absorbed_amount=_to_int(data.get("store_absorbed_amount"), 0) or 0,
                customer_pay_amount=amount,
                bot_order_no=data.get("order_no") or data.get("receipt_id"),
            )
            data["promoted_assignment_count"] = promoted_count

        dispatch_channel = guild.get_channel(dispatch_channel_id)
        dispatch_url = None

        if isinstance(dispatch_channel, discord.TextChannel):
            try:
                dispatch_message = await dispatch_channel.fetch_message(dispatch_message_id)
                dispatch_url = dispatch_message.jump_url

                claim_data = ORDER_CLAIMS.setdefault(dispatch_message_id, {})
                claim_data["locked"] = True
                claim_data["status"] = "active"
                claim_data["payment_method"] = str(payment_method)
                claim_data["amount"] = amount
                claim_data["total_amount"] = amount
                claim_data["customer_id"] = customer_id
                claim_data["category_label"] = category_label
                claim_data["item"] = item
                claim_data["quantity"] = quantity
                claim_data["source_channel_id"] = channel_id
                claim_data["dispatch_channel_id"] = dispatch_channel_id

                receiver_text = _build_receiver_text_from_claim_data(claim_data)

                dispatch_embed = build_self_service_order_embed(
                    customer_mention=f"<@{customer_id}>",
                    category_label=category_label,
                    item=item,
                    quantity=quantity,
                    payment_method=str(payment_method),
                    source_channel=interaction.channel,
                    companion_preference=companion_preference,
                    receiver_text=receiver_text,
                    staff_note=staff_note,
                )
                add_self_service_financial_breakdown_fields(
                    dispatch_embed,
                    data,
                    final_label="顧客實付",
                )

                dispatch_embed.add_field(name="付款狀態", value="已付款，接單人員已確認", inline=False)

                await dispatch_message.edit(
                    embed=dispatch_embed,
                    view=DispatchClaimView(
                        customer_id=customer_id,
                        category_label=category_label,
                        item=item,
                        quantity=quantity,
                        payment_method=str(payment_method),
                        source_channel_id=channel_id,
                        companion_preference=companion_preference,
                        locked=True,
                        status="active",
                    ),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )

                remember_claim_data(dispatch_message_id, claim_data)
            except discord.HTTPException:
                pass

        await rename_ticket_channel(interaction.channel, item, member=customer_member)

        payment_channel_id = _to_int(data.get("payment_channel_id"), interaction.channel.id) or interaction.channel.id
        payment_message_id = _to_int(data.get("payment_message_id"))
        payment_channel = guild.get_channel(payment_channel_id)

        submitted_embed = build_payment_method_embed(
            customer_id=customer_id,
            category_label=category_label,
            item=item,
            quantity=quantity,
            payment_method=str(payment_method),
            companion_preference=companion_preference,
            amount=amount,
            receiver_text=str(data.get("accepted_staff_display_text") or "").strip() or None,
            submitted=True,
            dispatch_url=dispatch_url,
        )

        if isinstance(payment_channel, discord.TextChannel) and payment_message_id is not None:
            try:
                payment_message = await payment_channel.fetch_message(payment_message_id)
                await payment_message.edit(
                    embed=submitted_embed,
                    view=PaymentMethodView(
                        customer_id=customer_id,
                        channel_id=channel_id,
                        submitted=True,
                        selected_method=str(payment_method),
                    ),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            except discord.HTTPException:
                pass

        if _to_int(data.get("operation_panel_message_id")) is None:
            operation_embed = discord.Embed(
                title="訂單操作",
                description="請客服從下拉式清單選擇後，按下確認。",
                color=discord.Color.green(),
            )
            operation_message = await interaction.channel.send(embed=operation_embed, view=StaffOrderOperationView())
            data["operation_panel_message_id"] = operation_message.id

        data["status"] = "active"
        data["closed"] = False
        data.pop("payment_processing", None)
        data.pop("payment_finalizing", None)
        if data.get("payment_review_approved"):
            data["payment_review_pending"] = False
            data["payment_review_applied_at"] = get_taipei_now_iso()
        if data.get("payment_review_approved") and data.get("payment_review_id"):
            data["payment_review_finalized_id"] = int(data["payment_review_id"])
        remember_order_data(channel_id, data)
        save_bot_data()

        if _order_requires_credentials(data):
            try:
                await ensure_order_credential_request(
                    channel=interaction.channel,
                    customer_id=customer_id,
                    data=data,
                )
            except Exception as exc:
                print(
                    f"[credentials] request panel failed channel_id={channel_id}: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

        response_text = f"已確認付款方式：{payment_method}，訂單正式成立。"
        if _order_requires_credentials(data):
            response_text += "\n🔐 請在票口的登入資料面板填寫代肝／代解帳號資料。"
        if data.get("receipt_id"):
            response_text += f"\n交易收據已產生：{data.get('receipt_id')}"
        if order_point_benefit_result:
            response_text += f"\n\n{order_point_benefit_result}"
        if order_loyalty_benefit_result:
            response_text += f"\n\n{order_loyalty_benefit_result}"
        if reward_result:
            response_text += f"\n\n{reward_result}"

        await interaction.followup.send(response_text, ephemeral=True)

        await send_order_log(
            guild,
            title="等待接單訂單已付款成立",
            fields=[
                ("顧客", f"<@{customer_id}>", True),
                ("訂單", f"{category_label}｜{item} x{quantity}", False),
                ("訂單總價", _format_plain_amount(amount) if "_format_plain_amount" in globals() else format_t_amount(amount), True),
                ("付款方式", str(payment_method), True),
                ("票口", interaction.channel.mention, False),
            ],
            color=discord.Color.green(),
        )

    except Exception as exc:
        data.pop("payment_processing", None)
        data.pop("payment_finalizing", None)
        remember_order_data(channel_id, data)
        save_bot_data()
        print(f"[acceptance] waiting_acceptance 付款成立失敗 channel_id={channel_id}: {exc}")
        await interaction.followup.send(f"付款成立失敗：`{type(exc).__name__}: {exc}`", ephemeral=True)

async def maybe_handle_prepay_acceptance_claim(
    view: "DispatchClaimView",
    interaction: discord.Interaction,
) -> bool:
    if interaction.message is None:
        return False

    try:
        from shared.order_acceptance import (
            ACCEPTED_PENDING_PAY,
            claim_acceptance_order,
            find_acceptance_order_id_by_dispatch_message_id,
        )

        acceptance_order_id = find_acceptance_order_id_by_dispatch_message_id(interaction.message.id)
    except Exception as exc:
        print(f"[acceptance] 查詢 Discord 派單是否為新流程失敗 message_id={getattr(interaction.message, 'id', None)}: {exc}")
        return False

    if acceptance_order_id is None:
        return False

    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return True

    # acceptance_claim_ack_v1
    # Acknowledge Discord before synchronous DB validation/write.
    await interaction.response.defer(
        ephemeral=True
    )

    try:
        state = claim_acceptance_order(
            order_id=acceptance_order_id,
            staff_discord_id=str(interaction.user.id),
            staff_display_name=_member_display_name(interaction.user),
            staff_role_ids=_member_role_id_texts(interaction.user),
            source="discord",
        )
    except ValueError as exc:
        print(
            "[acceptance] claim rejected "
            f"order_id={acceptance_order_id} "
            f"user_id={interaction.user.id} "
            f"role_ids={_member_role_id_texts(interaction.user)} "
            f"reason={exc}"
        )
        await interaction.followup.send(
            str(exc),
            ephemeral=True,
        )
        return True
    except Exception as exc:
        print(
            "[acceptance] Discord new-flow claim failed "
            f"order_id={acceptance_order_id} "
            f"user_id={interaction.user.id}: "
            f"{type(exc).__name__}: {exc}"
        )
        await interaction.followup.send(
            "接單失敗，請稍後再試或通知客服。",
            ephemeral=True,
        )
        return True

    ticket_access_ok = await grant_order_ticket_access(
        interaction.guild,
        view.source_channel_id,
        interaction.user,
    )

    claim_data = view.get_claim_data(interaction.message.id)
    _apply_acceptance_state_to_claim_data(claim_data, state)
    remember_claim_data(interaction.message.id, claim_data)

    if not ticket_access_ok:
        await interaction.followup.send(
            "已接單，但票口權限同步失敗，請通知客服檢查票口權限。",
            ephemeral=True,
        )

    try:
        await send_order_log(
            interaction.guild,
            title="我要接單｜待付款",
            fields=[
                ("接單人員", interaction.user.mention, True),
                ("顧客", f"<@{view.customer_id}>", True),
                ("訂單", f"{view.category_label}｜{view.item} x{view.quantity}", False),
                ("接單進度", f"{state.accepted_count}/{state.required_staff_count}", True),
                ("狀態", "人數已滿，等待付款" if state.status == ACCEPTED_PENDING_PAY else "等待接單", True),
            ],
            color=discord.Color.green(),
        )
    except Exception as exc:
        print(f"[acceptance] 接單日誌送出失敗：{exc}")

    await view.refresh_panel(interaction)

    if str(getattr(state, "status", "")) == "accepted_pending_pay":
        await send_acceptance_payment_panel_if_ready(view, interaction, state)

    return True


async def maybe_handle_prepay_acceptance_unclaim(
    view: "DispatchClaimView",
    interaction: discord.Interaction,
) -> bool:
    if interaction.message is None:
        return False

    try:
        from shared.order_acceptance import (
            find_acceptance_order_id_by_dispatch_message_id,
            unclaim_acceptance_order,
        )

        acceptance_order_id = find_acceptance_order_id_by_dispatch_message_id(interaction.message.id)
    except Exception as exc:
        print(f"[acceptance] 查詢 Discord 派單是否為新流程失敗 message_id={getattr(interaction.message, 'id', None)}: {exc}")
        return False

    if acceptance_order_id is None:
        return False

    if not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("無法確認你的身分組。", ephemeral=True)
        return True

    # acceptance_unclaim_ack_v1
    await interaction.response.defer(
        ephemeral=True
    )

    try:
        state = unclaim_acceptance_order(
            order_id=acceptance_order_id,
            staff_discord_id=str(interaction.user.id),
            source="discord",
        )
    except ValueError as exc:
        await interaction.followup.send(
            str(exc),
            ephemeral=True,
        )
        return True
    except Exception as exc:
        print(
            "[acceptance] Discord new-flow unclaim failed "
            f"order_id={acceptance_order_id} "
            f"user_id={interaction.user.id}: "
            f"{type(exc).__name__}: {exc}"
        )
        await interaction.followup.send(
            "取消接單失敗，請稍後再試或通知客服。",
            ephemeral=True,
        )
        return True

    ticket_access_ok = await revoke_order_ticket_access(
        interaction.guild,
        view.source_channel_id,
        interaction.user,
    )

    claim_data = view.get_claim_data(interaction.message.id)
    _apply_acceptance_state_to_claim_data(claim_data, state)
    remember_claim_data(interaction.message.id, claim_data)

    if not ticket_access_ok:
        await interaction.followup.send(
            "已取消接單，但票口權限同步失敗，請通知客服檢查票口權限。",
            ephemeral=True,
        )

    try:
        await send_order_log(
            interaction.guild,
            title="取消接單｜待付款",
            fields=[
                ("操作人", interaction.user.mention, True),
                ("顧客", f"<@{view.customer_id}>", True),
                ("訂單", f"{view.category_label}｜{view.item} x{view.quantity}", False),
                ("接單進度", f"{state.accepted_count}/{state.required_staff_count}", True),
            ],
            color=discord.Color.orange(),
        )
    except Exception as exc:
        print(f"[acceptance] 取消接單日誌送出失敗：{exc}")

    await view.refresh_panel(interaction)
    return True

class DispatchClaimView(discord.ui.View):
    def __init__(
        self,
        customer_id: int,
        category_label: str,
        item: str,
        quantity: int,
        payment_method: str,
        source_channel_id: int,
        companion_preference: str | None = None,
        locked: bool = False,
        status: str = "active",
    ):
        super().__init__(timeout=None)
        self.customer_id = customer_id
        self.category_label = category_label
        self.item = item
        self.quantity = quantity
        self.payment_method = payment_method
        self.source_channel_id = source_channel_id
        self.companion_preference = companion_preference
        self.locked = locked
        self.status = status

        self.add_item(DispatchCancelClaimButton(disabled=locked))

        if locked:
            for item in self.children:
                item.disabled = True


    def get_receiver_label(self, claim_type: str) -> str:
        return "我要接單"


    def get_required_role_id(self, claim_type: str) -> int:
        return BOOSTER_RECEIVER_ROLE_ID

    def get_claim_data(self, message_id: int) -> dict:
        data = ORDER_CLAIMS.setdefault(
            message_id,
            {
                "companion": set(),
                "booster": set(),
                "locked": False,
            }
        )

        data.setdefault("customer_id", self.customer_id)
        data.setdefault("category_label", self.category_label)
        data.setdefault("item", self.item)
        data.setdefault("quantity", self.quantity)
        data.setdefault("payment_method", self.payment_method)
        data.setdefault("source_channel_id", self.source_channel_id)
        data.setdefault("companion_preference", self.companion_preference)
        data.setdefault("dispatch_channel_id", DISPATCH_CHANNEL_ID)
        data.setdefault("status", self.status)

        return data


    def build_receiver_text(self, claim_data: dict) -> str | None:
        receiver_ids = sorted(
            set(claim_data.get("companion", set()))
            | set(claim_data.get("booster", set()))
        )

        if not receiver_ids:
            return None

        return "、".join(f"<@{user_id}>" for user_id in receiver_ids)

    async def refresh_panel(self, interaction: discord.Interaction, locked: bool | None = None):
        guild = interaction.guild

        # dispatch_refresh_after_defer_v1
        async def send_ephemeral(message: str) -> None:
            if interaction.response.is_done():
                await interaction.followup.send(
                    message,
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    message,
                    ephemeral=True,
                )

        if guild is None:
            await send_ephemeral("這個功能只能在伺服器內使用。")
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await send_ephemeral("這個功能只能在派單文字頻道使用。")
            return

        source_channel = guild.get_channel(self.source_channel_id)

        if source_channel is None or not isinstance(source_channel, discord.TextChannel):
            await send_ephemeral("找不到來源票口。")
            return

        claim_data = self.get_claim_data(interaction.message.id)

        if locked is not None:
            claim_data["locked"] = locked

        remember_claim_data(interaction.message.id, claim_data)

        receiver_text = self.build_receiver_text(claim_data)

        new_embed = build_self_service_order_embed(
            customer_mention=f"<@{self.customer_id}>",
            category_label=self.category_label,
            item=self.item,
            quantity=_to_int(claim_data.get("quantity"), self.quantity) or 1,
            payment_method=self.payment_method,
            source_channel=source_channel,
            companion_preference=self.companion_preference,
            receiver_text=receiver_text
        )

        status = claim_data.get("status", "active")

        if status == "stored":
            new_embed.add_field(
                name="狀態",
                value=(
                    "已存單，接單面板已鎖定\n"
                    f"存單原因：{claim_data.get('stored_reason') or '未填寫'}\n"
                    f"預計恢復：{claim_data.get('stored_expected_time') or '未填寫'}"
                ),
                inline=False
            )
        elif claim_data.get("locked"):
            new_embed.add_field(
                name="狀態",
                value="已結單，接單面板已鎖定",
                inline=False
            )

        updated_view = DispatchClaimView(
            customer_id=self.customer_id,
            category_label=self.category_label,
            item=self.item,
            quantity=_to_int(
                claim_data.get("quantity"),
                self.quantity,
            ) or 1,
            payment_method=self.payment_method,
            source_channel_id=self.source_channel_id,
            companion_preference=self.companion_preference,
            locked=bool(
                claim_data.get("locked")
            ),
            status=str(
                claim_data.get(
                    "status",
                    "active",
                )
            ),
        )

        edit_kwargs = {
            "embed": new_embed,
            "view": updated_view,
            "allowed_mentions": discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        }

        if interaction.response.is_done():
            await interaction.edit_original_response(
                **edit_kwargs
            )
        else:
            await interaction.response.edit_message(
                **edit_kwargs
            )


    async def claim_order(self, interaction: discord.Interaction, claim_type: str):
        handled = await maybe_handle_prepay_acceptance_claim(self, interaction)

        if handled:
            return

        await interaction.response.send_message(
            "舊接單流程已停用。這張接單面板不是目前的付款前接單流程，請客服重新用自助下單送出等待接單。",
            ephemeral=True,
        )

    async def cancel_claim(self, interaction: discord.Interaction):
        handled = await maybe_handle_prepay_acceptance_unclaim(self, interaction)

        if handled:
            return

        await interaction.response.send_message(
            "舊取消接單流程已停用。這張接單面板不是目前的付款前接單流程，請客服確認訂單狀態。",
            ephemeral=True,
        )


    async def companion_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.claim_order(interaction, "companion")

    @discord.ui.button(
        label="我要接單",
        style=discord.ButtonStyle.primary,
        custom_id="dispatch_claim_booster"
    )
    async def booster_claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.claim_order(interaction, "booster")


async def delete_dispatch_claim_panel_for_order(
    guild: discord.Guild,
    order_channel_id: int,
    *,
    actor_discord_id: str | int | None = None,
    cancellation_reason_code: str | None = None,
    cancellation_reason_text: str | None = None,
):
    """取消票口時，一併刪除派單頻道對應的接單面板，並清除保存資料。"""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel_id, {})
    coupon_id = _to_int(data.get("selected_loyalty_coupon_id"), None)
    if coupon_id is not None:
        try:
            from services.loyalty_benefits import restore_coupon
            restore_coupon(coupon_id, customer_id=data.get("customer_id"))
        except Exception as exc:
            print(f"[loyalty] 取消訂單退回福利券失敗 channel_id={order_channel_id}: {exc}")
    dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID

    if dispatch_message_id is not None:
        try:
            from shared.order_acceptance import (
                cancel_acceptance_order,
                find_acceptance_order_id_by_dispatch_message_id,
            )

            acceptance_order_id = find_acceptance_order_id_by_dispatch_message_id(dispatch_message_id)
            if acceptance_order_id is not None:
                cancel_acceptance_order(
                    acceptance_order_id,
                    source="discord_cancel",
                    actor_discord_id=actor_discord_id,
                    cancellation_reason_code=cancellation_reason_code,
                    cancellation_reason_text=cancellation_reason_text,
                )
                print(f"[acceptance] cancelled order_id={acceptance_order_id} dispatch_message_id={dispatch_message_id}")
        except Exception as exc:
            print(f"[acceptance] 取消訂單同步付款前接單狀態失敗 dispatch_message_id={dispatch_message_id}: {exc}")

        dispatch_channel = guild.get_channel(dispatch_channel_id)

        if isinstance(dispatch_channel, discord.TextChannel):
            try:
                message = await dispatch_channel.fetch_message(dispatch_message_id)
                await message.delete()
            except discord.NotFound:
                pass
            except discord.Forbidden:
                print("Bot 權限不足，無法刪除派單接單面板。")
            except discord.HTTPException as e:
                print(f"刪除派單接單面板失敗：{e}")

        ORDER_CLAIMS.pop(dispatch_message_id, None)
        delete_claim_row_from_db(message_id=dispatch_message_id)

    if _order_requires_credentials(data):
        try:
            from services.order_credentials import get_order_id_by_ticket_channel
            credential_order_id = _to_int(data.get("web_order_id")) or get_order_id_by_ticket_channel(order_channel_id)
            if credential_order_id is not None:
                credential_ticket_channel = guild.get_channel(order_channel_id)
                await revoke_order_credential_messages(
                    credential_order_id,
                    reason="cancelled",
                    ticket_channel=credential_ticket_channel if isinstance(credential_ticket_channel, discord.TextChannel) else None,
                    notify_customer=True,
                )
        except Exception as exc:
            print(f"[credentials] 取消票口撤回失敗 channel_id={order_channel_id}: {exc}")

    if order_channel_id in SELF_SERVICE_ORDER_SELECTIONS:
        SELF_SERVICE_ORDER_SELECTIONS.pop(order_channel_id, None)
        delete_order_row_from_db(order_channel_id)
        save_bot_data()
    elif dispatch_message_id is not None:
        save_bot_data()


async def lock_dispatch_claim_panel(guild: discord.Guild, order_channel_id: int):
    """客服結單後，鎖定派單頻道對應的陪玩 / 打手接單面板。

    這版會同時處理「恢復訂單後重新發派單面板」的情況：
    如果 orders 裡記到的是舊 dispatch_message_id，會再從 ORDER_CLAIMS 裡找同一張票口的派單訊息，
    並把找到的派單面板全部鎖定，避免最新那則恢復訂單面板還能繼續被按。
    """
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel_id, {})
    dispatch_channel_id = data.get("dispatch_channel_id", DISPATCH_CHANNEL_ID)

    source_channel = guild.get_channel(order_channel_id)

    if source_channel is None or not isinstance(source_channel, discord.TextChannel):
        return

    if _order_requires_credentials(data):
        try:
            from services.order_credentials import get_order_id_by_ticket_channel
            credential_order_id = _to_int(data.get("web_order_id")) or get_order_id_by_ticket_channel(order_channel_id)
            if credential_order_id is not None:
                await revoke_order_credential_messages(
                    credential_order_id,
                    reason="closed",
                    ticket_channel=source_channel,
                    notify_customer=True,
                )
        except Exception as exc:
            print(f"[credentials] 結單撤回失敗 channel_id={order_channel_id}: {exc}")

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    # 優先鎖 orders 目前記錄的派單訊息，同時補抓所有 claims 裡來源票口相同的派單訊息。
    candidate_message_ids: list[int] = []

    first_dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    if first_dispatch_message_id is not None:
        candidate_message_ids.append(first_dispatch_message_id)

    for message_id, claim in list(ORDER_CLAIMS.items()):
        claim_source_channel_id = _to_int(claim.get("source_channel_id"))
        if claim_source_channel_id == order_channel_id:
            parsed_message_id = _to_int(message_id)
            if parsed_message_id is not None and parsed_message_id not in candidate_message_ids:
                candidate_message_ids.append(parsed_message_id)

    if not candidate_message_ids:
        return

    customer_id = data.get("customer_id")
    category = data.get("category")
    item = data.get("item", "未紀錄")
    quantity = _to_int(data.get("quantity"), 1) or 1
    payment_method = data.get("payment_method", "未紀錄")
    companion_preference = data.get("companion_preference")
    category_label = ORDER_CATEGORY_LABELS.get(category, category or data.get("category_label") or "未紀錄")
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "未紀錄"

    data["closed"] = True
    data["status"] = "closed"
    data["closed_at"] = get_taipei_now_iso()
    data["quantity"] = quantity

    try:
        from services.loyalty_benefits import record_paid_service
        source_order_key = (
            f"WEB-{int(data['web_order_id'])}"
            if _to_int(data.get("web_order_id"), None) is not None
            else f"DC-{int(order_channel_id)}"
        )
        loyalty_result = record_paid_service(
            customer_id=customer_id or data.get("customer_id") or 0,
            rule_key=str(data.get("order_rule_key") or ""),
            player_count=_to_int(data.get("player_count"), 1) or 1,
            paid_units=float(quantity),
            source_order_key=source_order_key,
            completed_at=data["closed_at"],
        )
        issued = loyalty_result.get("issued") or []
        if issued:
            reward_lines = "\n".join(
                f"・**{coupon.get('display_name') or '累積福利'}**"
                for coupon in issued
            )
            await source_channel.send(
                f"<@{customer_id}> 🎁 **累積福利已達標！**\n{reward_lines}\n下次點同商品、同人數規格時即可使用，陪玩可以重新選。",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
    except Exception as exc:
        print(f"[loyalty] 結單累積失敗 channel_id={order_channel_id}: {type(exc).__name__}: {exc}")
    data["dispatch_channel_id"] = dispatch_channel_id

    locked_any = False
    newest_existing_message_id: int | None = None

    for dispatch_message_id in candidate_message_ids:
        claim_data = ORDER_CLAIMS.setdefault(
            dispatch_message_id,
            {
                "companion": set(),
                "booster": set(),
                "locked": False,
            }
        )

        # 先把 canonical claim 狀態終結並移除持久化資料。
        # Discord 訊息即使已被刪除／無權限讀取，也不能讓 bot.db 留著 active claim。
        claim_data["customer_id"] = claim_data.get("customer_id") or customer_id
        claim_data["category_label"] = claim_data.get("category_label") or category_label
        claim_data["item"] = claim_data.get("item") or item
        claim_data["quantity"] = _to_int(claim_data.get("quantity"), quantity) or quantity
        claim_data["payment_method"] = claim_data.get("payment_method") or payment_method
        claim_data["source_channel_id"] = order_channel_id
        claim_data["companion_preference"] = claim_data.get("companion_preference") or companion_preference
        claim_data["dispatch_channel_id"] = dispatch_channel_id
        claim_data["locked"] = True
        claim_data["status"] = "closed"
        remember_claim_data(dispatch_message_id, claim_data)

        if not isinstance(dispatch_channel, discord.TextChannel):
            continue

        try:
            message = await dispatch_channel.fetch_message(dispatch_message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            continue

        companion_ids = sorted(claim_data.get("companion", set()))
        booster_ids = sorted(claim_data.get("booster", set()))
        lines = []

        if companion_ids:
            lines.extend(f"<@{user_id}>" for user_id in companion_ids)

        if booster_ids:
            lines.extend(f"<@{user_id}>" for user_id in booster_ids)

        receiver_text = "、".join(dict.fromkeys(lines)) if lines else None

        embed = build_self_service_order_embed(
            customer_mention=customer_mention,
            category_label=str(claim_data.get("category_label") or category_label),
            item=str(claim_data.get("item") or item),
            quantity=_to_int(claim_data.get("quantity"), quantity) or quantity,
            payment_method=str(claim_data.get("payment_method") or payment_method),
            source_channel=source_channel,
            companion_preference=claim_data.get("companion_preference") or companion_preference,
            receiver_text=receiver_text
        )
        embed.add_field(
            name="狀態",
            value="已結單，接單面板已鎖定",
            inline=False
        )

        try:
            await message.edit(
                embed=embed,
                view=DispatchClaimView(
                    customer_id=_to_int(claim_data.get("customer_id"), _to_int(customer_id, 0) or 0) or 0,
                    category_label=str(claim_data.get("category_label") or category_label),
                    item=str(claim_data.get("item") or item),
                    quantity=_to_int(claim_data.get("quantity"), quantity) or quantity,
                    payment_method=str(claim_data.get("payment_method") or payment_method),
                    source_channel_id=order_channel_id,
                    companion_preference=claim_data.get("companion_preference") or companion_preference,
                    locked=True,
                    status="closed"
                ),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False
                )
            )
            locked_any = True
            newest_existing_message_id = dispatch_message_id
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            continue

    # 用實際成功鎖定的最新派單訊息覆蓋，避免之後再找到舊面板。
    if newest_existing_message_id is not None:
        data["dispatch_message_id"] = newest_existing_message_id

    # 即使 Discord panel 已不存在，訂單與 claim 的 final 狀態仍必須落地。
    remember_order_data(order_channel_id, data)
    save_bot_data()



def sync_web_order_status_from_bot(ticket_channel_id, status: str, dispatch_message_id=None, note: str | None = None) -> None:
    """DC bot 訂單狀態變更後，同步網站 web_orders.status。"""
    try:
        from shared.web_order_sync import update_web_order_status_by_ticket_channel

        ok = update_web_order_status_by_ticket_channel(
            ticket_channel_id=ticket_channel_id,
            status=status,
            dispatch_message_id=dispatch_message_id,
            note=note,
        )
        print(
            f"[web-sync] order status sync "
            f"ticket_channel_id={ticket_channel_id} "
            f"dispatch_message_id={dispatch_message_id} "
            f"status={status} ok={ok}"
        )
    except Exception as exc:
        print(
            f"[web-sync] 訂單狀態同步網站失敗 "
            f"ticket_channel_id={ticket_channel_id} "
            f"status={status}: {exc}"
        )


async def store_dispatch_claim_panel(
    guild: discord.Guild,
    order_channel: discord.TextChannel,
    staff_member: discord.Member,
    reason: str,
    expected_time: str | None = None,
    note: str | None = None,
):
    """將訂單標記為存單，鎖定派單接單面板但保留票口。"""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel.id, {})
    dispatch_message_id = data.get("dispatch_message_id")
    dispatch_channel_id = data.get("dispatch_channel_id", DISPATCH_CHANNEL_ID)

    if dispatch_message_id is None:
        raise ValueError("找不到這張訂單對應的派單訊息，請確認顧客是否已完成付款方式並送出派單。")

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        raise ValueError("找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。")

    try:
        message = await dispatch_channel.fetch_message(dispatch_message_id)
    except discord.NotFound as exc:
        raise ValueError("找不到派單訊息，可能已被刪除。") from exc
    except discord.Forbidden as exc:
        raise ValueError("Bot 權限不足，無法讀取派單訊息。") from exc
    except discord.HTTPException as exc:
        raise ValueError(f"讀取派單訊息失敗：{exc}") from exc

    customer_id = data.get("customer_id") or get_order_customer_id_from_channel(order_channel)
    category = data.get("category")
    item = data.get("item", "未紀錄")
    quantity = _to_int(data.get("quantity"), 1) or 1
    payment_method = data.get("payment_method", "未紀錄")
    companion_preference = data.get("companion_preference")
    category_label = ORDER_CATEGORY_LABELS.get(category, category or data.get("category_label") or "未紀錄")
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "未紀錄"

    claim_data = ORDER_CLAIMS.setdefault(
        dispatch_message_id,
        {
            "companion": set(),
            "booster": set(),
            "locked": False,
        }
    )
    claim_data["customer_id"] = customer_id
    claim_data["category_label"] = category_label
    claim_data["item"] = item
    claim_data["quantity"] = quantity
    claim_data["payment_method"] = payment_method
    claim_data["source_channel_id"] = order_channel.id
    claim_data["companion_preference"] = companion_preference
    claim_data["dispatch_channel_id"] = dispatch_channel_id
    claim_data["locked"] = True
    claim_data["status"] = "stored"
    claim_data["stored_at"] = get_taipei_now_iso()
    claim_data["stored_by"] = staff_member.id
    claim_data["stored_reason"] = reason
    claim_data["stored_expected_time"] = expected_time or None
    claim_data["stored_note"] = note or None

    data["customer_id"] = customer_id
    data["quantity"] = quantity
    data["dispatch_message_id"] = dispatch_message_id
    data["dispatch_channel_id"] = dispatch_channel_id
    data["closed"] = False
    data["status"] = "stored"
    data["stored_at"] = claim_data["stored_at"]
    data["stored_by"] = staff_member.id
    data["stored_reason"] = reason
    data["stored_expected_time"] = expected_time or None
    data["stored_note"] = note or None
    data["stored_reminders_sent"] = []

    remember_order_data(order_channel.id, data)

    try:
        from shared.order_acceptance import (
            find_acceptance_order_id_by_dispatch_message_id,
            pause_acceptance_order,
        )

        acceptance_order_id = find_acceptance_order_id_by_dispatch_message_id(dispatch_message_id)
        if acceptance_order_id is not None:
            pause_acceptance_order(acceptance_order_id, source="discord_store")
            print(f"[acceptance] stored order_id={acceptance_order_id} dispatch_message_id={dispatch_message_id}")
    except Exception as exc:
        print(f"[acceptance] 存單同步付款前接單狀態失敗 dispatch_message_id={dispatch_message_id}: {exc}")

    sync_web_order_status_from_bot(
        ticket_channel_id=order_channel.id,
        status="stored",
        dispatch_message_id=dispatch_message_id,
        note="由 DC bot 存單同步。",
    )

    if _order_requires_credentials(data):
        try:
            from services.order_credentials import get_order_id_by_ticket_channel
            credential_order_id = _to_int(data.get("web_order_id")) or get_order_id_by_ticket_channel(order_channel.id)
            if credential_order_id is not None:
                await revoke_order_credential_messages(
                    credential_order_id,
                    reason="stored",
                    ticket_channel=order_channel,
                    notify_customer=True,
                )
        except Exception as exc:
            print(f"[credentials] 存單撤回失敗 channel_id={order_channel.id}: {exc}")

    remember_claim_data(dispatch_message_id, claim_data)

    companion_ids = sorted(claim_data.get("companion", set()))
    booster_ids = sorted(claim_data.get("booster", set()))
    lines = []

    if companion_ids:
        lines.extend(f"<@{user_id}>" for user_id in companion_ids)

    if booster_ids:
        lines.extend(f"<@{user_id}>" for user_id in booster_ids)

    receiver_text = "、".join(dict.fromkeys(lines)) if lines else None

    embed = build_self_service_order_embed(
        customer_mention=customer_mention,
        category_label=category_label,
        item=item,
        quantity=quantity,
        payment_method=payment_method,
        source_channel=order_channel,
        companion_preference=companion_preference,
        receiver_text=receiver_text
    )
    embed.add_field(
        name="狀態",
        value=(
            "已存單，接單面板已鎖定\n"
            f"存單原因：{reason}\n"
            f"預計恢復：{expected_time or '未填寫'}"
        ),
        inline=False
    )

    if note:
        embed.add_field(
            name="存單備註",
            value=note,
            inline=False
        )

    await message.edit(
        embed=embed,
        view=DispatchClaimView(
            customer_id=customer_id or 0,
            category_label=category_label,
            item=item,
            quantity=quantity,
            payment_method=payment_method,
            source_channel_id=order_channel.id,
            companion_preference=companion_preference,
            locked=True,
            status="stored"
        ),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=False,
            everyone=False
        )
    )


async def resume_stored_order(
    guild: discord.Guild,
    order_channel: discord.TextChannel,
    staff_member: discord.Member,
):
    """恢復已存單的訂單，保留原本接單人員，重新發派單面板，並清掉舊派單訊息。"""
    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel.id, {})
    old_dispatch_message_id = _to_int(data.get("dispatch_message_id"))
    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID

    # 收集這張票口所有舊派單訊息，避免同一張存單恢復後派單頻道殘留舊面板。
    old_dispatch_message_ids: set[int] = set()

    if old_dispatch_message_id:
        old_dispatch_message_ids.add(old_dispatch_message_id)

    for message_id, claim in list(ORDER_CLAIMS.items()):
        if not isinstance(claim, dict):
            continue

        claim_source_channel_id = _to_int(claim.get("source_channel_id"))

        if claim_source_channel_id == order_channel.id:
            parsed_message_id = _to_int(message_id)
            if parsed_message_id:
                old_dispatch_message_ids.add(parsed_message_id)

    if not old_dispatch_message_ids:
        raise ValueError("找不到這張訂單對應的派單訊息，無法恢復。")

    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if dispatch_channel is None or not isinstance(dispatch_channel, discord.TextChannel):
        raise ValueError("找不到派單頻道，請確認 DISPATCH_CHANNEL_ID 是否正確。")

    # 優先取原本 dispatch_message_id 的 claim；沒有的話，找同票口任一 claim。
    claim_data = ORDER_CLAIMS.get(old_dispatch_message_id) if old_dispatch_message_id else None

    if not claim_data:
        for message_id in old_dispatch_message_ids:
            possible_claim = ORDER_CLAIMS.get(message_id)
            if isinstance(possible_claim, dict):
                claim_data = possible_claim
                break

    if not claim_data:
        raise ValueError("找不到已保存的接單資料，請重新派單。")

    customer_id = claim_data.get("customer_id") or data.get("customer_id") or get_order_customer_id_from_channel(order_channel)
    category_label = claim_data.get("category_label") or ORDER_CATEGORY_LABELS.get(data.get("category"), data.get("category") or "未紀錄")
    item = claim_data.get("item") or data.get("item", "未紀錄")
    quantity = _to_int(claim_data.get("quantity"), _to_int(data.get("quantity"), 1)) or 1
    payment_method = claim_data.get("payment_method") or data.get("payment_method", "未紀錄")
    companion_preference = claim_data.get("companion_preference") or data.get("companion_preference")
    customer_mention = f"<@{customer_id}>" if customer_id is not None else "未紀錄"

    resume_status = "active"
    acceptance_state = None
    acceptance_order_id = None

    try:
        from shared.order_acceptance import (
            find_acceptance_order_id_by_dispatch_message_id,
            resume_acceptance_order,
        )

        for candidate_message_id in [old_dispatch_message_id, *old_dispatch_message_ids]:
            parsed_candidate_id = _to_int(candidate_message_id)
            if parsed_candidate_id is None:
                continue

            acceptance_order_id = find_acceptance_order_id_by_dispatch_message_id(parsed_candidate_id)
            if acceptance_order_id is not None:
                break

        if acceptance_order_id is not None:
            acceptance_state = resume_acceptance_order(acceptance_order_id, source="discord_resume")
            resume_status = str(acceptance_state.status or "waiting_acceptance")
            _apply_acceptance_state_to_claim_data(claim_data, acceptance_state)
            print(
                f"[acceptance] resumed order_id={acceptance_order_id} "
                f"status={resume_status} old_dispatch={old_dispatch_message_id}"
            )
    except Exception as exc:
        raise ValueError(f"恢復付款前接單狀態失敗：{exc}") from exc

    claim_data["locked"] = False
    claim_data["status"] = resume_status
    claim_data["customer_id"] = customer_id
    claim_data["category_label"] = str(category_label)
    claim_data["item"] = str(item)
    claim_data["quantity"] = quantity
    claim_data["payment_method"] = str(payment_method)
    claim_data["source_channel_id"] = order_channel.id
    claim_data["companion_preference"] = companion_preference
    claim_data["dispatch_channel_id"] = dispatch_channel.id

    # 存單相關資料保留在資料中當紀錄；舊單回 active，新流程回 waiting_acceptance / accepted_pending_pay。
    data["closed"] = False
    data["status"] = resume_status
    data["quantity"] = quantity
    data["dispatch_channel_id"] = dispatch_channel.id
    data["stored_at"] = None
    data["stored_by"] = None
    data["stored_reason"] = None
    data["stored_expected_time"] = None
    data["stored_note"] = None

    if resume_status == "active" and _order_requires_credentials(data):
        try:
            await ensure_order_credential_request(
                channel=order_channel,
                customer_id=_to_int(customer_id, 0) or 0,
                data=data,
            )
            if customer_id is not None:
                await order_channel.send(
                    f"<@{customer_id}> 🔐 訂單已恢復。先前登入資料私訊已撤回，請重新提交本單登入資料。",
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
        except Exception as exc:
            print(f"[credentials] 恢復訂單登入資料提示失敗 channel_id={order_channel.id}: {exc}")

    companion_ids = sorted(claim_data.get("companion", set()))
    booster_ids = sorted(claim_data.get("booster", set()))
    lines = []

    if companion_ids:
        lines.extend(f"<@{user_id}>" for user_id in companion_ids)

    if booster_ids:
        lines.extend(f"<@{user_id}>" for user_id in booster_ids)

    receiver_text = "、".join(dict.fromkeys(lines)) if lines else None

    embed = build_self_service_order_embed(
        customer_mention=customer_mention,
        category_label=str(category_label),
        item=str(item),
        quantity=quantity,
        payment_method=str(payment_method),
        source_channel=order_channel,
        companion_preference=companion_preference,
        receiver_text=receiver_text
    )
    embed.add_field(
        name="狀態",
        value=f"已由 {staff_member.mention} 恢復訂單，接單面板已重新發到最新位置。",
        inline=False
    )

    resume_smart_dispatch = None
    resume_allowed_role_ids: list[str] = []
    resume_required_game_role_ids: list[str] = []
    resume_specified_staff_ids = [
        str(item)
        for item in (
            data.get("specified_staff_ids")
            or claim_data.get("specified_staff_ids")
            or []
        )
        if str(item).strip()
    ]
    resume_unresolved_specified_ids = list(
        resume_specified_staff_ids
    )

    if (
        resume_status == "waiting_acceptance"
        and acceptance_state is not None
        and acceptance_order_id is not None
    ):
        try:
            from services.order_rules import (
                get_allowed_role_ids,
                get_required_game_role_ids,
            )

            resume_rule = _get_rule_from_self_service_data(
                data
            )
            resume_allowed_role_ids = get_allowed_role_ids(
                resume_rule
            )
            resume_required_game_role_ids = get_required_game_role_ids(
                resume_rule
            )
            accepted_ids = {
                str(claim.staff_discord_id)
                for claim in acceptance_state.claims
            }
            resume_unresolved_specified_ids = [
                staff_id
                for staff_id in resume_specified_staff_ids
                if staff_id not in accepted_ids
            ]
            remaining_count = max(
                1,
                int(acceptance_state.required_staff_count or 1)
                - int(acceptance_state.accepted_count or 0),
            )

            resume_smart_dispatch = prepare_initial_smart_dispatch(
                guild,
                customer_id=customer_id,
                allowed_role_ids=resume_allowed_role_ids,
                specified_staff_ids=resume_unresolved_specified_ids,
                required_staff_count=remaining_count,
                required_game_role_ids=resume_required_game_role_ids,
                excluded_staff_ids=accepted_ids,
            )
        except Exception as exc:
            print(
                f"[smart-dispatch] resume prepare failed "
                f"order_id={acceptance_order_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    new_message = await dispatch_channel.send(
        content=None,
        embed=embed,
        view=DispatchClaimView(
            customer_id=customer_id or 0,
            category_label=str(category_label),
            item=str(item),
            quantity=quantity,
            payment_method=str(payment_method),
            source_channel_id=order_channel.id,
            companion_preference=companion_preference,
            locked=False,
            status=resume_status
        ),
        allowed_mentions=discord.AllowedMentions(
            users=True,
            roles=resume_smart_dispatch is not None,
            everyone=False
        )
    )

    if resume_smart_dispatch is not None:
        try:
            await send_initial_smart_dispatch_alert(
                guild,
                content=resume_smart_dispatch["content"],
                dispatch_jump_url=new_message.jump_url,
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"[smart-dispatch] resume initial alert failed: {exc}", flush=True)

    # 刪除同一張票口的所有舊派單訊息，避免存單恢復後殘留不能操作的舊面板。
    for message_id in old_dispatch_message_ids:
        if message_id == new_message.id:
            continue

        try:
            old_message = await dispatch_channel.fetch_message(message_id)
        except discord.NotFound:
            old_message = None
        except (discord.Forbidden, discord.HTTPException):
            old_message = None

        if old_message is not None:
            try:
                await old_message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException, TypeError):
                pass

        ORDER_CLAIMS.pop(message_id, None)
        delete_claim_row_from_db(message_id=message_id, source_channel_id=order_channel.id)

    # 把接單資料移到新的 message_id，保留原本陪玩/打手接單人員。
    ORDER_CLAIMS[new_message.id] = claim_data
    data["dispatch_message_id"] = new_message.id
    data["dispatch_channel_id"] = dispatch_channel.id

    if (
        resume_smart_dispatch is not None
        and acceptance_order_id is not None
        and acceptance_state is not None
    ):
        try:
            create_smart_dispatch_plan(
                order_id=int(acceptance_order_id),
                dispatch_channel_id=dispatch_channel.id,
                dispatch_message_id=new_message.id,
                required_staff_count=int(
                    acceptance_state.required_staff_count
                    or 1
                ),
                allowed_role_ids=resume_allowed_role_ids,
                specified_staff_ids=resume_specified_staff_ids,
                required_game_role_ids=resume_required_game_role_ids,
                ranked_candidate_ids=resume_smart_dispatch[
                    "ranked_candidate_ids"
                ],
                notified_candidate_ids=resume_smart_dispatch[
                    "initial_notified_ids"
                ],
                reset_existing=True,
            )

            if resume_unresolved_specified_ids:
                dm_sent_ids, dm_failed_ids = (
                    await send_specified_staff_dispatch_dms(
                        guild,
                        specified_staff_ids=resume_unresolved_specified_ids,
                        category_label=str(category_label),
                        item_label=str(item),
                        required_staff_count=int(
                            acceptance_state.required_staff_count
                            or 1
                        ),
                        dispatch_jump_url=new_message.jump_url,
                        allowed_role_ids=resume_allowed_role_ids,
                        required_game_role_ids=resume_required_game_role_ids,
                    )
                )
                set_specified_dm_results(
                    int(acceptance_order_id),
                    sent_ids=dm_sent_ids,
                    failed_ids=dm_failed_ids,
                )
        except Exception as exc:
            print(
                f"[smart-dispatch] resume lifecycle failed "
                f"order_id={acceptance_order_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    remember_order_data(order_channel.id, data)
    sync_web_order_status_from_bot(
        ticket_channel_id=order_channel.id,
        status=resume_status,
        dispatch_message_id=data.get("dispatch_message_id"),
        note="由 DC bot 恢復存單同步。",
    )
    remember_claim_data(new_message.id, claim_data)
    save_bot_data()


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
