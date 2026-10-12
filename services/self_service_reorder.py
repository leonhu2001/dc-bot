from __future__ import annotations

import json
from typing import Any, Callable

import discord


_CONFIGURED = False


def configure_self_service_reorder(
    *,
    order_category_labels,
    order_item_groups_by_category,
    get_order_rule_by_item_label: Callable,
    role_key_for_member: Callable,
    to_int: Callable,
    order_item_details_for_group: Callable,
    order_item_group_label: Callable,
    self_service_quantity_meta: Callable,
    taipei_now_iso: Callable,
    staff_price_required: Callable,
    customer_role_id: int,
    customer_category_id: int,
    order_control_view,
    self_service_order_view,
    panel_embed_builder: Callable,
    self_service_order_selections: dict,
    remember_data: Callable,
    save_data: Callable,
    ticket_channel_name_builder: Callable,
    delete_order_row: Callable,
    order_log_sender: Callable,
) -> None:
    """Bind the explicit APIs needed by the reorder ticket workflow."""
    global _CONFIGURED
    global ORDER_CATEGORY_LABELS, ORDER_ITEM_GROUPS_BY_CATEGORY
    global _get_order_rule_by_item_label, _role_key_for_member, _to_int
    global get_order_item_details_for_group, get_order_item_group_label
    global get_self_service_quantity_meta, get_taipei_now_iso
    global is_self_service_staff_price_required
    global CUSTOMER_ROLE_ID, CUSTOMER_CATEGORY_ID
    global OrderControlView, SelfServiceOrderView, build_self_service_panel_embed
    global SELF_SERVICE_ORDER_SELECTIONS, remember_order_data, save_bot_data
    global build_ticket_channel_name, delete_order_row_from_db, send_order_log

    ORDER_CATEGORY_LABELS = order_category_labels
    ORDER_ITEM_GROUPS_BY_CATEGORY = order_item_groups_by_category
    _get_order_rule_by_item_label = get_order_rule_by_item_label
    _role_key_for_member = role_key_for_member
    _to_int = to_int
    get_order_item_details_for_group = order_item_details_for_group
    get_order_item_group_label = order_item_group_label
    get_self_service_quantity_meta = self_service_quantity_meta
    get_taipei_now_iso = taipei_now_iso
    is_self_service_staff_price_required = staff_price_required
    CUSTOMER_ROLE_ID = int(customer_role_id)
    CUSTOMER_CATEGORY_ID = int(customer_category_id)
    OrderControlView = order_control_view
    SelfServiceOrderView = self_service_order_view
    build_self_service_panel_embed = panel_embed_builder
    SELF_SERVICE_ORDER_SELECTIONS = self_service_order_selections
    remember_order_data = remember_data
    save_bot_data = save_data
    build_ticket_channel_name = ticket_channel_name_builder
    delete_order_row_from_db = delete_order_row
    send_order_log = order_log_sender
    _CONFIGURED = True


def _reorder_order_value(
    order,
    key: str,
    default=None,
):
    if order is None:
        return default

    try:
        value = order[key]
    except (
        KeyError,
        IndexError,
        TypeError,
    ):
        value = getattr(
            order,
            key,
            default,
        )

    return (
        default
        if value is None
        else value
    )


def _reorder_json_dict(value) -> dict:
    if isinstance(value, dict):
        return dict(value)

    try:
        parsed = json.loads(
            str(value or "")
        )
    except Exception:
        return {}

    return (
        parsed
        if isinstance(parsed, dict)
        else {}
    )


async def build_reorder_self_service_draft(
    *,
    guild: discord.Guild,
    order,
    targets: list[dict],
    customer_id: int,
) -> tuple[dict, list[str]]:
    """
    從已結單 WebOrder 建立一份新的自助下單草稿。

    不繼承：
    - 舊付款方式
    - 舊折扣
    - 舊點數福利
    - 舊客服手動報價

    自動價會由目前規則重新試算。
    """

    source_order_id = _to_int(
        _reorder_order_value(
            order,
            "id",
        )
    )

    source_ticket_channel_id = _to_int(
        _reorder_order_value(
            order,
            "ticket_channel_id",
        )
    )

    source_dispatch_message_id = _to_int(
        _reorder_order_value(
            order,
            "dispatch_message_id",
        )
    )

    old_category_label = str(
        _reorder_order_value(
            order,
            "category",
            "",
        )
        or ""
    ).strip()

    old_item = str(
        _reorder_order_value(
            order,
            "item",
            "",
        )
        or ""
    ).strip()

    stored_rule_key = str(
        _reorder_order_value(
            order,
            "order_rule_key",
            "",
        )
        or ""
    ).strip()

    price_snapshot = _reorder_json_dict(
        _reorder_order_value(
            order,
            "price_snapshot_json",
            None,
        )
    )

    rule_snapshot = _reorder_json_dict(
        _reorder_order_value(
            order,
            "rule_snapshot_json",
            None,
        )
    )

    warnings = []

    data = {
        "customer_id": int(customer_id),
        "status": "draft",
        "closed": False,

        "reorder_source_order_id": (
            source_order_id
        ),

        "reorder_source_ticket_channel_id": (
            source_ticket_channel_id
        ),

        "reorder_source_dispatch_message_id": (
            source_dispatch_message_id
        ),

        "reorder_source_category": (
            old_category_label
        ),

        "reorder_source_item": (
            old_item
        ),

        "reorder_created_at": (
            get_taipei_now_iso()
        ),

        "reorder_draft_version": 2,

        "companion_preference": (
            "不指定陪玩/打手"
        ),
    }

    try:
        from services.order_rules import (
            ORDER_RULES,
            get_required_staff_count,
        )
    except Exception as exc:
        warnings.append(
            f"讀取目前訂單規則失敗：{exc}"
        )

        return data, warnings

    rule = None

    if stored_rule_key:
        rule = ORDER_RULES.get(
            stored_rule_key
        )

    if (
        rule is None
        and old_item
    ):
        rule = _get_order_rule_by_item_label(
            old_item
        )

    category_key = None

    if rule is not None:
        category_key = str(
            getattr(
                rule,
                "category",
                "",
            )
            or ""
        )

        old_item = str(
            getattr(
                rule,
                "label",
                old_item,
            )
            or old_item
        )

        stored_rule_key = str(
            getattr(
                rule,
                "key",
                stored_rule_key,
            )
            or stored_rule_key
        )

    if not category_key:
        for key, label in (
            ORDER_CATEGORY_LABELS.items()
        ):
            if (
                str(label).strip()
                == old_category_label
            ):
                category_key = str(key)
                break

    if (
        category_key
        and category_key
        in ORDER_CATEGORY_LABELS
    ):
        data["category"] = (
            category_key
        )

    item_group = None

    if old_item:
        try:
            item_group = (
                get_order_item_group_label(
                    old_item
                )
            )
        except Exception:
            item_group = None

    valid_groups = (
        ORDER_ITEM_GROUPS_BY_CATEGORY.get(
            category_key,
            [],
        )
        if category_key
        else []
    )

    if (
        item_group
        and item_group in valid_groups
    ):
        data["item_group"] = (
            item_group
        )
    else:
        item_group = None

    detail = None

    if (
        category_key
        and item_group
    ):
        details = (
            get_order_item_details_for_group(
                category_key,
                item_group,
            )
        )

        for candidate in details:
            candidate_rule_key = str(
                candidate.get(
                    "rule_key"
                )
                or ""
            )

            candidate_item = str(
                candidate.get(
                    "item"
                )
                or ""
            )

            if (
                stored_rule_key
                and candidate_rule_key
                == stored_rule_key
            ):
                detail = candidate
                break

            if (
                old_item
                and candidate_item
                == old_item
            ):
                detail = candidate
                break

    if detail is not None:
        data["item_detail_value"] = str(
            detail.get("value")
            or ""
        )

        data["item"] = str(
            detail.get("item")
            or old_item
        )

        data["order_rule_key"] = str(
            detail.get("rule_key")
            or stored_rule_key
        )

        if (
            detail.get(
                "player_count"
            )
            is not None
        ):
            data["player_count"] = int(
                detail["player_count"]
            )

        try:
            rule = ORDER_RULES.get(
                data["order_rule_key"]
            ) or rule
        except Exception:
            pass

        old_quantity = (
            _to_int(
                _reorder_order_value(
                    order,
                    "quantity",
                    1,
                ),
                1,
            )
            or 1
        )

        meta = (
            get_self_service_quantity_meta(
                category_key,
                item_group,
                data[
                    "item_detail_value"
                ],
            )
        )

        if meta:
            minimum = int(
                meta.get(
                    "min",
                    1,
                )
                or 1
            )

            maximum = int(
                meta.get(
                    "max",
                    minimum,
                )
                or minimum
            )

            old_quantity = max(
                minimum,
                min(
                    maximum,
                    old_quantity,
                ),
            )

        data["quantity"] = (
            old_quantity
        )

    elif category_key:
        warnings.append(
            "上一張單的品項目前無法完整對應新版自助下單，"
            "已先帶入可辨識的類別，請重新確認品項與規格。"
        )

    else:
        warnings.append(
            "上一張單的類別目前已不在自助下單清單，"
            "請在新票口重新選擇。"
        )

    # 非把 player_count 寫在第三欄的項目，
    # 從上一單 snapshot 嘗試還原。
    if (
        rule is not None
        and bool(
            getattr(
                rule,
                "player_count_enabled",
                False,
            )
        )
        and not data.get(
            "player_count"
        )
    ):
        old_player_count = (
            _to_int(
                price_snapshot.get(
                    "player_count"
                ),
                None,
            )
        )

        if old_player_count is None:
            old_player_count = (
                _to_int(
                    rule_snapshot.get(
                        "player_count"
                    ),
                    None,
                )
            )

        if old_player_count is not None:
            minimum = max(
                1,
                int(
                    getattr(
                        rule,
                        "min_player_count",
                        1,
                    )
                    or 1
                ),
            )

            maximum_raw = getattr(
                rule,
                "max_player_count",
                None,
            )

            maximum = (
                int(maximum_raw)
                if maximum_raw
                is not None
                else None
            )

            old_player_count = max(
                minimum,
                old_player_count,
            )

            if maximum is not None:
                old_player_count = min(
                    maximum,
                    old_player_count,
                )

            data["player_count"] = (
                old_player_count
            )

    # 上一張單的接單成員：
    # 只有「現在仍符合這個品項可指定資格」的人才帶入。
    if (
        rule is not None
        and bool(
            getattr(
                rule,
                "allow_specify",
                False,
            )
        )
        and targets
    ):
        player_count = (
            _to_int(
                data.get(
                    "player_count"
                ),
                1,
            )
            or 1
        )

        try:
            required_staff_count = int(
                get_required_staff_count(
                    rule,
                    player_count,
                )
                or 1
            )
        except Exception:
            required_staff_count = 1

        max_specified = int(
            getattr(
                rule,
                "max_specified_count",
                None,
            )
            or required_staff_count
            or 1
        )

        max_specified = max(
            1,
            min(
                max_specified,
                required_staff_count,
            ),
        )

        valid_staff_ids = []
        rejected_staff_count = 0

        for target in targets:
            staff_id = str(
                target.get(
                    "staff_id"
                )
                or ""
            ).strip()

            if not staff_id:
                continue

            try:
                member_id = int(
                    staff_id
                )
            except ValueError:
                rejected_staff_count += 1
                continue

            member = guild.get_member(
                member_id
            )

            if member is None:
                try:
                    member = (
                        await guild.fetch_member(
                            member_id
                        )
                    )
                except Exception:
                    member = None

            if (
                member is None
                or _role_key_for_member(
                    rule,
                    member,
                )
                is None
            ):
                rejected_staff_count += 1
                continue

            if (
                staff_id
                not in valid_staff_ids
            ):
                valid_staff_ids.append(
                    staff_id
                )

        if len(
            valid_staff_ids
        ) > max_specified:
            rejected_staff_count += (
                len(valid_staff_ids)
                - max_specified
            )

            valid_staff_ids = (
                valid_staff_ids[
                    :max_specified
                ]
            )

        if valid_staff_ids:
            data[
                "specified_staff_ids"
            ] = valid_staff_ids

            data[
                "companion_preference"
            ] = "指定陪玩/打手"

        if rejected_staff_count:
            warnings.append(
                "上一單部分接單成員目前不符合這個品項的指定資格，"
                "因此沒有自動帶入。"
            )

    # 手動報價單絕對不沿用舊價格。
    if (
        rule is not None
        and is_self_service_staff_price_required(
            rule
        )
    ):
        warnings.append(
            "此品項需要客服重新報價，上一張單的舊報價不會沿用。"
        )

    return data, warnings


def _reorder_message_has_component(
    message: discord.Message,
    custom_id: str,
) -> bool:
    for row in getattr(message, "components", []) or []:
        for child in getattr(row, "children", []) or []:
            if str(getattr(child, "custom_id", "") or "") == str(custom_id):
                return True
    return False


async def _find_reorder_panel_message(
    channel: discord.TextChannel,
    custom_id: str,
) -> discord.Message | None:
    try:
        async for message in channel.history(limit=80):
            if _reorder_message_has_component(message, custom_id):
                return message
    except (discord.Forbidden, discord.HTTPException):
        return None
    return None


async def ensure_reorder_ticket_panels(
    *,
    guild: discord.Guild,
    channel: discord.TextChannel,
    customer_id: int,
    data: dict,
    source_order_id: int | None,
) -> tuple[discord.Message, discord.Message]:
    """
    再約票口固定維持兩個正式面板：
    1. 客服操作：填寫自助下單 / 取消訂單
    2. 已預填的自助下單面板

    重複按「再約」時會修復缺少的面板，不會一直重複建立。
    """

    support_role = guild.get_role(CUSTOMER_ROLE_ID)
    support_mention = support_role.mention if support_role is not None else "客服"
    source_text = (
        f"WEB-{source_order_id}"
        if source_order_id is not None
        else "上一張訂單"
    )

    control_message = await _find_reorder_panel_message(
        channel,
        "order_control_select",
    )

    control_embed = discord.Embed(
        title="客服操作選項",
        description=(
            f"這是由 {source_text} 建立的再約草稿。\n"
            "下方使用一般訂單控制：客服可開啟／更新自助下單，"
            "或直接取消這張再約訂單。"
        ),
        color=discord.Color.gold(),
    )
    control_embed.set_footer(
        text=(
            f"REORDER-{source_order_id or channel.id}"
            "｜客服操作"
        )
    )

    if control_message is None:
        control_message = await channel.send(
            content=f"{support_mention} 再約草稿待確認。",
            embed=control_embed,
            view=OrderControlView(),
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=True,
                everyone=False,
            ),
        )
    else:
        try:
            await control_message.edit(
                embed=control_embed,
                view=OrderControlView(),
                allowed_mentions=discord.AllowedMentions(
                    users=False,
                    roles=True,
                    everyone=False,
                ),
            )
        except discord.HTTPException:
            pass

    self_service_message = await _find_reorder_panel_message(
        channel,
        "self_service_order_category_select",
    )

    panel_embed = build_self_service_panel_embed(
        customer_id,
        data,
        guild,
    )
    panel_embed.set_footer(
        text=(
            f"REORDER-{source_order_id or channel.id}"
            "｜再約預填自助下單"
        )
    )
    panel_view = SelfServiceOrderView(
        customer_id=customer_id,
        channel_id=channel.id,
        selected_category=data.get("category"),
    )

    if self_service_message is None:
        self_service_message = await channel.send(
            content=(
                f"<@{customer_id}> "
                "這張是你的再約草稿，系統已帶入上一單可沿用內容，"
                "你可以直接修改。"
            ),
            embed=panel_embed,
            view=panel_view,
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        )
    else:
        try:
            await self_service_message.edit(
                embed=panel_embed,
                view=panel_view,
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=False,
                    everyone=False,
                ),
            )
        except discord.HTTPException:
            pass

    data["reorder_control_message_id"] = control_message.id
    data["self_service_panel_message_id"] = self_service_message.id
    remember_order_data(channel.id, data)
    save_bot_data()

    return control_message, self_service_message


async def create_reorder_ticket_from_closed_order(
    *,
    interaction: discord.Interaction,
    order,
    targets: list[dict],
    order_content: str | None = None,
) -> dict:
    """
    再約 v2：
    已結單票口按再約
    -> 建立全新票口
    -> 預填自助下單
    -> 老闆可修改
    -> 客服確認送出
    """

    guild = interaction.guild
    member = interaction.user

    if (
        guild is None
        or not isinstance(
            member,
            discord.Member,
        )
    ):
        raise ValueError(
            "這個功能只能在伺服器內使用。"
        )

    source_order_id = _to_int(
        _reorder_order_value(
            order,
            "id",
        )
    )

    source_ticket_channel_id = _to_int(
        _reorder_order_value(
            order,
            "ticket_channel_id",
        )
    )

    old_item = str(
        _reorder_order_value(
            order,
            "item",
            "未紀錄",
        )
        or "未紀錄"
    )

    # 防止同一筆來源訂單連點建立很多草稿。
    if source_order_id is not None:
        marker = (
            f"reorder_source_order_id="
            f"{source_order_id}"
        )

        customer_marker = (
            f"order_customer_id="
            f"{member.id}"
        )

        for possible_channel in (
            guild.text_channels
        ):
            topic = str(
                possible_channel.topic
                or ""
            )

            if (
                marker not in topic
                or customer_marker
                not in topic
            ):
                continue

            existing_data = (
                SELF_SERVICE_ORDER_SELECTIONS.get(
                    possible_channel.id,
                    {},
                )
            )

            existing_status = str(
                existing_data.get(
                    "status"
                )
                or "draft"
            ).lower()

            if (
                not existing_data.get(
                    "closed"
                )
                and existing_status
                not in {
                    "closed",
                    "cancelled",
                    "canceled",
                }
            ):
                repair_warnings: list[str] = []

                # 舊版再約草稿可能只建立了文字訊息，
                # 或 Bot 重啟後缺少 panel message id。
                # 只有資料真的不存在時才重新從來源單建立草稿；
                # 已經被老闆修改過的草稿絕不覆蓋。
                if not existing_data:
                    existing_data, repair_warnings = (
                        await build_reorder_self_service_draft(
                            guild=guild,
                            order=order,
                            targets=targets,
                            customer_id=member.id,
                        )
                    )
                    SELF_SERVICE_ORDER_SELECTIONS[
                        possible_channel.id
                    ] = existing_data
                    remember_order_data(
                        possible_channel.id,
                        existing_data,
                    )

                await ensure_reorder_ticket_panels(
                    guild=guild,
                    channel=possible_channel,
                    customer_id=member.id,
                    data=existing_data,
                    source_order_id=source_order_id,
                )

                return {
                    "channel": (
                        possible_channel
                    ),
                    "created": False,
                    "warning": "；".join(repair_warnings),
                }

    category = guild.get_channel(
        CUSTOMER_CATEGORY_ID
    )

    if (
        category is None
        or not isinstance(
            category,
            discord.CategoryChannel,
        )
    ):
        raise ValueError(
            "找不到下單票口類別。"
        )

    customer_staff_role = (
        guild.get_role(
            CUSTOMER_ROLE_ID
        )
    )

    overwrites = {
        guild.default_role:
            discord.PermissionOverwrite(
                view_channel=False,
                send_messages=False,
                read_message_history=False,
            ),

        member:
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),

        guild.me:
            discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                read_message_history=True,
                attach_files=True,
            ),
    }

    if customer_staff_role is not None:
        overwrites[
            customer_staff_role
        ] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            attach_files=True,
        )

    topic_parts = [
        f"order_customer_id={member.id}",
    ]

    if source_order_id is not None:
        topic_parts.append(
            "reorder_source_order_id="
            f"{source_order_id}"
        )

    if source_ticket_channel_id is not None:
        topic_parts.append(
            "reorder_source_ticket_channel_id="
            f"{source_ticket_channel_id}"
        )

    new_channel = (
        await guild.create_text_channel(
            name=build_ticket_channel_name(
                "再約",
                member,
            ),
            category=category,
            overwrites=overwrites,
            topic=";".join(
                topic_parts
            ),
            reason=(
                f"{member} created reorder "
                f"from WEB-{source_order_id}"
            ),
        )
    )

    try:
        data, warnings = (
            await build_reorder_self_service_draft(
                guild=guild,
                order=order,
                targets=targets,
                customer_id=member.id,
            )
        )

        SELF_SERVICE_ORDER_SELECTIONS[
            new_channel.id
        ] = data

        remember_order_data(
            new_channel.id,
            data,
        )

        support_mention = (
            customer_staff_role.mention
            if customer_staff_role
            is not None
            else ""
        )

        source_text = (
            f"WEB-{source_order_id}"
            if source_order_id
            is not None
            else "上一張訂單"
        )

        intro_lines = [
            support_mention,
            "🔁 **再約訂單已建立**",
            "",
            f"老闆：{member.mention}",
            f"來源：{source_text}",
            f"上一單項目：{old_item}",
            "",
            "系統已先把上一張單可沿用的內容填入下方自助下單。",
            "老闆可以直接修改類別、品項、規格、數量、指定成員與點數福利。",
            "折扣、付款方式、舊點數福利與舊客服報價不會沿用。",
            "",
            "內容確認完成後，由客服按 **「客服確認送出」**。",
        ]

        if warnings:
            intro_lines.extend(
                [
                    "",
                    "⚠️ **系統提醒**",
                    *[
                        f"・{warning}"
                        for warning
                        in warnings
                    ],
                ]
            )

        await new_channel.send(
            content="\n".join(
                line
                for line in intro_lines
                if line is not None
            ),
            allowed_mentions=(
                discord.AllowedMentions(
                    users=True,
                    roles=True,
                    everyone=False,
                )
            ),
        )

        await ensure_reorder_ticket_panels(
            guild=guild,
            channel=new_channel,
            customer_id=member.id,
            data=data,
            source_order_id=source_order_id,
        )

        try:
            await send_order_log(
                guild,
                title="再約草稿已建立",
                fields=[
                    (
                        "顧客",
                        member.mention,
                        True,
                    ),
                    (
                        "來源訂單",
                        (
                            f"WEB-{source_order_id}"
                            if source_order_id
                            is not None
                            else "未紀錄"
                        ),
                        True,
                    ),
                    (
                        "新票口",
                        new_channel.mention,
                        False,
                    ),
                    (
                        "上一單項目",
                        old_item,
                        False,
                    ),
                    (
                        "流程",
                        (
                            "系統預填 → "
                            "顧客可修改 → "
                            "客服確認送出"
                        ),
                        False,
                    ),
                ],
                color=discord.Color.blue(),
            )
        except Exception as exc:
            print(
                "[reorder] log failed "
                f"channel_id="
                f"{new_channel.id}: {exc}"
            )

        return {
            "channel": new_channel,
            "created": True,
            "warning": (
                "；".join(warnings)
            ),
        }

    except Exception:
        # 草稿初始化失敗時不要留下空白垃圾票口。
        try:
            await new_channel.delete(
                reason=(
                    "Reorder draft initialization failed"
                )
            )
        except Exception:
            pass

        SELF_SERVICE_ORDER_SELECTIONS.pop(
            new_channel.id,
            None,
        )

        try:
            delete_order_row_from_db(
                new_channel.id
            )
        except Exception:
            pass

        raise
