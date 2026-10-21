from __future__ import annotations

import math

import discord


_INSTALLED = False
_PAGE_SIZE = 23
_SERVICE_ORDER = {
    "單陪": 0,
    "雙陪": 1,
    "三陪": 2,
    "四陪": 3,
}


def _game_rows() -> list[dict]:
    from services import orders
    from services import vip_timer_select_flow as flow
    from services.vip_timer_policy_v5 import _GAME_ORDER

    flow.refresh_vip_timer_self_service_catalog()
    groups = list(orders.SELF_SERVICE_ORDER_CATALOG.get(flow.VIP_TIMER_CATEGORY, ()) or ())
    by_label = {
        str(group.get("label") or ""): dict(group)
        for group in groups
        if str(group.get("label") or "").strip()
    }
    return [by_label[label] for label in _GAME_ORDER if label in by_label]


def _gameplay_groups(game_label: str) -> list[dict]:
    from services import vip_timer_select_flow as flow
    from services import vip_timer_selector_order_v3 as v3

    return list(v3._spec_groups(flow._details_for_game(str(game_label or ""))) or ())


def _detail_required_staff_count(detail: dict) -> int:
    from services.order_rules import ORDER_RULES

    rule = ORDER_RULES.get(str(detail.get("rule_key") or ""))
    if rule is None:
        return 0
    required = getattr(rule, "required_staff_count", 1)
    if required == "player_count":
        try:
            selected = int(detail.get("player_count") or 0)
        except (TypeError, ValueError):
            selected = 0
        if selected > 0:
            return selected
        return max(1, int(getattr(rule, "min_player_count", 1) or 1))
    try:
        return max(1, int(required or 1))
    except (TypeError, ValueError):
        return 0


def _service_details_for_roster(order_id: int, group: dict) -> list[dict]:
    from services import vip_timer_runtime as runtime

    staff_count = len(runtime._accepted_staff_ids(int(order_id)))
    rows = [
        dict(detail)
        for detail in (group.get("details") or ())
        if _detail_required_staff_count(detail) == staff_count
        and str(detail.get("vip_timer_service_type") or "") in _SERVICE_ORDER
    ]
    rows.sort(
        key=lambda detail: (
            _SERVICE_ORDER.get(str(detail.get("vip_timer_service_type") or ""), 99),
            str(detail.get("value") or ""),
        )
    )
    return rows


def _gameplay_group(game_label: str, group_key: str) -> dict | None:
    for group in _gameplay_groups(game_label):
        if str(group.get("key") or "") == str(group_key or ""):
            return group
    return None


async def _refresh_timer_message(interaction: discord.Interaction, order_id: int) -> None:
    from services import vip_timer_runtime as runtime

    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        return
    session = runtime.get_session(int(order_id)) or {}
    message_id = int(session.get("timer_message_id") or 0)
    if not message_id:
        return
    try:
        message = await channel.fetch_message(message_id)
        await message.edit(
            embed=runtime.build_vip_timer_embed(int(order_id)),
            view=runtime.VipTimerControlView(status=session.get("status")),
        )
    except (discord.NotFound, discord.HTTPException):
        pass


class VipTimerSwitchGameSelect(discord.ui.Select):
    def __init__(self, order_id: int):
        self.order_id = int(order_id)
        rows = _game_rows()
        options = [
            discord.SelectOption(label=str(row.get("label") or "遊戲")[:100], value=str(row.get("label") or "")[:100])
            for row in rows[:25]
        ]
        if not options:
            options = [discord.SelectOption(label="目前沒有可切換的遊戲", value="__none__")]
        super().__init__(
            placeholder="選擇遊戲",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        game_label = str((self.values or [""])[0])
        if game_label == "__none__":
            await interaction.response.send_message("目前沒有可切換的遊戲。", ephemeral=True)
            return
        await interaction.response.edit_message(
            content="選擇新的玩法：",
            view=VipTimerSwitchGameplayView(self.order_id, game_label, page=0),
        )


class VipTimerSwitchGameView(discord.ui.View):
    def __init__(self, order_id: int):
        super().__init__(timeout=180)
        self.add_item(VipTimerSwitchGameSelect(int(order_id)))


class VipTimerSwitchGameplaySelect(discord.ui.Select):
    def __init__(self, order_id: int, game_label: str, page: int = 0):
        self.order_id = int(order_id)
        self.game_label = str(game_label)
        self.page = max(0, int(page))
        groups = _gameplay_groups(self.game_label)
        start = self.page * _PAGE_SIZE
        rows = groups[start : start + _PAGE_SIZE]
        options = [
            discord.SelectOption(
                label=str(group.get("label") or "玩法")[:100],
                value=str(group.get("key") or "")[:100],
                description="選完後只顯示目前接單人數可用的陪玩形式"[:100],
            )
            for group in rows
        ]
        if not options:
            options = [discord.SelectOption(label="這一頁沒有可用玩法", value="__none__")]
        super().__init__(
            placeholder="選擇玩法",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        group_key = str((self.values or [""])[0])
        if group_key == "__none__":
            await interaction.response.send_message("這一頁沒有可用玩法。", ephemeral=True)
            return
        await interaction.response.edit_message(
            content="選擇陪玩形式：",
            view=VipTimerSwitchServiceView(self.order_id, self.game_label, group_key),
        )


class VipTimerSwitchGameplayView(discord.ui.View):
    def __init__(self, order_id: int, game_label: str, page: int = 0):
        super().__init__(timeout=180)
        self.order_id = int(order_id)
        self.game_label = str(game_label)
        groups = _gameplay_groups(self.game_label)
        self.pages = max(1, math.ceil(len(groups) / _PAGE_SIZE))
        self.page = min(max(0, int(page)), self.pages - 1)
        self.add_item(VipTimerSwitchGameplaySelect(self.order_id, self.game_label, self.page))
        if self.pages > 1:
            previous = discord.ui.Button(
                label="上一頁",
                style=discord.ButtonStyle.secondary,
                disabled=self.page <= 0,
            )
            following = discord.ui.Button(
                label="下一頁",
                style=discord.ButtonStyle.secondary,
                disabled=self.page >= self.pages - 1,
            )

            async def previous_callback(interaction: discord.Interaction):
                await interaction.response.edit_message(
                    content="選擇新的玩法：",
                    view=VipTimerSwitchGameplayView(self.order_id, self.game_label, self.page - 1),
                )

            async def following_callback(interaction: discord.Interaction):
                await interaction.response.edit_message(
                    content="選擇新的玩法：",
                    view=VipTimerSwitchGameplayView(self.order_id, self.game_label, self.page + 1),
                )

            previous.callback = previous_callback
            following.callback = following_callback
            self.add_item(previous)
            self.add_item(following)


class VipTimerSwitchServiceSelect(discord.ui.Select):
    def __init__(self, order_id: int, game_label: str, group_key: str):
        self.order_id = int(order_id)
        self.game_label = str(game_label)
        self.group_key = str(group_key)

        from services import vip_timer_runtime as runtime
        from services import vip_timer_select_flow as flow

        group = _gameplay_group(self.game_label, self.group_key)
        rows = _service_details_for_roster(self.order_id, group or {})
        staff_count = len(runtime._accepted_staff_ids(self.order_id))
        options: list[discord.SelectOption] = []
        for detail in rows[:25]:
            service_type = str(detail.get("vip_timer_service_type") or "陪玩")
            rate = int(flow._effective_rate(detail) or 0)
            options.append(
                discord.SelectOption(
                    label=service_type[:100],
                    value=str(detail.get("value") or "")[:100],
                    description=(f"{rate:,}T / H" if rate > 0 else "切換時重新驗證")[:100],
                )
            )
        if not options:
            options = [
                discord.SelectOption(
                    label=f"目前 {staff_count} 位接單人員沒有可用形式"[:100],
                    value="__none__",
                )
            ]
        super().__init__(
            placeholder="選擇陪玩形式",
            min_values=1,
            max_values=1,
            options=options,
            disabled=(len(rows) == 0),
        )

    async def callback(self, interaction: discord.Interaction):
        selected = str((self.values or [""])[0])
        if selected == "__none__":
            await interaction.response.send_message("目前接單人數不支援這個玩法。", ephemeral=True)
            return

        from services import vip_timer_runtime as runtime

        session = runtime.get_session(self.order_id)
        if session is None or not runtime._can_operate(interaction, session):
            await interaction.response.send_message("你沒有操作這張計時單的權限。", ephemeral=True)
            return

        group = _gameplay_group(self.game_label, self.group_key)
        detail = next(
            (
                row
                for row in _service_details_for_roster(self.order_id, group or {})
                if str(row.get("value") or "") == selected
            ),
            None,
        )
        if detail is None:
            await interaction.response.send_message("陪玩形式已更新，請重新選擇。", ephemeral=True)
            return

        rule_key = str(detail.get("rule_key") or "").strip()
        staff_ids = runtime._accepted_staff_ids(self.order_id)
        try:
            runtime.switch_rule(self.order_id, rule_key, interaction.user.id, staff_ids)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        runtime.clear_pause_request(self.order_id, actor_id=interaction.user.id, reason="rule_switched")
        await interaction.response.edit_message(
            content="✅ 已切換玩法，新的計費區段已開始。",
            view=None,
        )
        await _refresh_timer_message(interaction, self.order_id)


class VipTimerSwitchServiceView(discord.ui.View):
    def __init__(self, order_id: int, game_label: str, group_key: str):
        super().__init__(timeout=180)
        self.add_item(VipTimerSwitchServiceSelect(int(order_id), str(game_label), str(group_key)))


def install_vip_timer_runtime_selector_v6() -> None:
    """Make in-ticket switching use the same game -> gameplay -> headcount flow as checkout."""
    global _INSTALLED
    if _INSTALLED:
        return

    from services import vip_timer_runtime as runtime

    runtime.VipTimerCategorySelect = VipTimerSwitchGameSelect
    runtime.VipTimerCategoryView = VipTimerSwitchGameView
    _INSTALLED = True


__all__ = [
    "VipTimerSwitchGameSelect",
    "VipTimerSwitchGameView",
    "VipTimerSwitchGameplaySelect",
    "VipTimerSwitchGameplayView",
    "VipTimerSwitchServiceSelect",
    "VipTimerSwitchServiceView",
    "install_vip_timer_runtime_selector_v6",
]
