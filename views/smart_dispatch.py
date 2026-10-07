from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import discord

SMART_DISPATCH_ALERT_CHANNEL_ID = 1555881625844191322
PUBLIC_ACCEPTANCE_OPEN_SECONDS = 60
# 保留第一版智慧派單節奏：公開開放後 3 分鐘擴大一批、6 分鐘全量通知。
SECOND_WAVE_AFTER_OPEN_SECONDS = 180
FULL_EXPANSION_AFTER_OPEN_SECONDS = 360
SECOND_WAVE_SECONDS = PUBLIC_ACCEPTANCE_OPEN_SECONDS + SECOND_WAVE_AFTER_OPEN_SECONDS
FULL_EXPANSION_SECONDS = PUBLIC_ACCEPTANCE_OPEN_SECONDS + FULL_EXPANSION_AFTER_OPEN_SECONDS
REPEAT_REMINDER_SECONDS = 600
SMART_DISPATCH_LOOP_SECONDS = 10

from core.vip_levels import VIP_LEVELS
from services.order_rules import role_ids_match_requirements
from services.smart_dispatch import (
    choose_initial_candidate_ids,
    get_completed_favorite_worker_ids,
    complete_smart_dispatch_plan,
    list_pending_smart_dispatch_plans,
    mark_smart_dispatch_stage,
    next_candidate_batch,
    plan_age_seconds,
    rank_dispatch_candidates,
)


def get_eligible_dispatch_candidate_ids(
    guild: discord.Guild,
    *,
    allowed_role_ids: Iterable[str | int],
    specified_staff_ids: Iterable[str | int] = (),
    required_game_role_ids: Iterable[str | int] = (),
) -> list[str]:
    # specified_staff_ids intentionally does not bypass qualification. It is
    # kept in the signature for caller compatibility and ranking context.
    _ = specified_staff_ids
    allowed = [
        str(role_id)
        for role_id in allowed_role_ids
        if str(role_id).strip()
    ]
    required_games = [
        str(role_id)
        for role_id in required_game_role_ids
        if str(role_id).strip()
    ]

    result: list[str] = []

    for member in guild.members:
        if getattr(member, "bot", False):
            continue

        member_roles = {
            str(role.id)
            for role in getattr(member, "roles", [])
            if getattr(role, "id", None) is not None
        }

        if role_ids_match_requirements(
            member_roles,
            allowed,
            required_games,
        ):
            result.append(str(member.id))

    return result


def customer_has_familiar_worker_benefit(
    guild: discord.Guild,
    customer_id: str | int | None,
) -> bool:
    """Return whether the customer currently has the Diamond+ familiar-worker perk."""
    customer_key = str(customer_id or "").strip()
    if not customer_key:
        return False

    try:
        numeric_id = int(customer_key)
    except (TypeError, ValueError):
        return False

    member = None
    get_member = getattr(guild, "get_member", None)
    if callable(get_member):
        member = get_member(numeric_id)

    if member is None:
        member = next(
            (
                item
                for item in getattr(guild, "members", [])
                if int(getattr(item, "id", 0) or 0) == numeric_id
            ),
            None,
        )

    if member is None:
        return False

    familiar_role_ids = {
        str(level.get("role_id"))
        for level in VIP_LEVELS
        if "familiar_worker" in (level.get("benefit_keys") or [])
    }
    member_role_ids = {
        str(role.id)
        for role in getattr(member, "roles", [])
        if getattr(role, "id", None) is not None
    }

    return bool(familiar_role_ids & member_role_ids)


def prepare_initial_smart_dispatch(
    guild: discord.Guild,
    *,
    customer_id: str | int | None = None,
    allowed_role_ids: list[str],
    specified_staff_ids: list[str],
    required_staff_count: int,
    required_game_role_ids: Iterable[str | int] = (),
    excluded_staff_ids: Iterable[str | int] = (),
    db_file: str | Path | None = None,
) -> dict:
    candidate_ids = get_eligible_dispatch_candidate_ids(
        guild,
        allowed_role_ids=allowed_role_ids,
        specified_staff_ids=specified_staff_ids,
        required_game_role_ids=required_game_role_ids,
    )

    excluded = {
        str(item)
        for item in excluded_staff_ids
        if str(item).strip()
    }

    if excluded:
        candidate_ids = [
            worker_id
            for worker_id in candidate_ids
            if worker_id not in excluded
        ]

    priority_ids: list[str] = []

    if customer_has_familiar_worker_benefit(
        guild,
        customer_id,
    ):
        priority_ids = get_completed_favorite_worker_ids(
            customer_id,
            candidate_ids,
            db_file=db_file,
        )

    ranked_ids = rank_dispatch_candidates(
        candidate_ids,
        specified_staff_ids=specified_staff_ids,
        priority_staff_ids=priority_ids,
        db_file=db_file,
    )

    initial_ids = choose_initial_candidate_ids(
        ranked_ids,
        specified_staff_ids=specified_staff_ids,
        priority_staff_ids=priority_ids,
        required_staff_count=required_staff_count,
    )

    specified_set = {
        str(item)
        for item in specified_staff_ids
        if str(item).strip()
    }

    specified_initial = [
        worker_id
        for worker_id in initial_ids
        if worker_id in specified_set
    ]
    priority_set = {
        str(item)
        for item in priority_ids
        if str(item).strip()
    }
    familiar_initial = [
        worker_id
        for worker_id in initial_ids
        if worker_id in priority_set
        and worker_id not in specified_set
    ]
    general_initial = [
        worker_id
        for worker_id in initial_ids
        if worker_id not in specified_set
        and worker_id not in priority_set
    ]

    lines: list[str] = []

    if specified_initial:
        lines.append(
            "🎯 **指定單優先通知**｜"
            + " ".join(f"<@{worker_id}>" for worker_id in specified_initial)
        )

    if familiar_initial:
        lines.append(
            "💎 **VIP 熟悉收藏優先**｜"
            + " ".join(f"<@{worker_id}>" for worker_id in familiar_initial)
        )

    if general_initial:
        prefix = (
            "🔔 **優先派單**｜"
            if not specified_initial and not familiar_initial
            else "🔔 **剩餘名額優先通知**｜"
        )
        lines.append(
            prefix
            + " ".join(f"<@{worker_id}>" for worker_id in general_initial)
        )

    if initial_ids:
        lines.append(
            f"目前需要 **{max(1, int(required_staff_count or 1))} 位**，"
            "請查看下方派單內容並按鈕接單。"
        )
    else:
        # AND 型資格不能安全地用單一 role mention 代替，否則會提醒
        # 只有遊戲身分或只有職位/階級的人。
        role_mentions = (
            []
            if list(required_game_role_ids)
            else _role_mentions(guild, allowed_role_ids)
        )

        if role_mentions:
            lines.append(
                "⚠️ 目前沒有可做個人優先排序的成員，改為通知符合資格身分組："
                + " ".join(role_mentions)
            )
        else:
            lines.append(
                "⚠️ 目前找不到可通知的符合資格人員，請客服確認人力與身分組設定。"
            )

    return {
        "ranked_candidate_ids": ranked_ids,
        "priority_candidate_ids": priority_ids,
        # 這一批現在代表「60 秒後第一輪要通知的人」。為了相容現有
        # plan schema 沿用欄位名稱，真正的 Discord 通知會由 escalation loop 發出。
        "initial_notified_ids": initial_ids,
        "required_game_role_ids": [
            str(role_id)
            for role_id in required_game_role_ids
            if str(role_id).strip()
        ],
        "content": "\n".join(lines),
    }


async def send_initial_smart_dispatch_alert(
    guild: discord.Guild,
    *,
    content: str | None,
    dispatch_jump_url: str,
) -> discord.Message | None:
    """Announce a new order immediately without pinging public candidates.

    The actual first candidate mentions remain deferred until the 60-second
    public-acceptance lock expires. Specified qualified staff are DM'd
    separately and may accept during the lock.
    """
    _ = content
    alert_channel = guild.get_channel(SMART_DISPATCH_ALERT_CHANNEL_ID)
    if alert_channel is None or not callable(getattr(alert_channel, "send", None)):
        return None

    return await alert_channel.send(
        "🔒 **新單已建立｜1 分鐘接單保護期**\n"
        "新訂單已建立，公開接單將於 **1 分鐘後** 開放。\n"
        "指定人員若符合訂單資格，可立即接單。\n"
        f"前往原派單：{dispatch_jump_url}",
        allowed_mentions=discord.AllowedMentions(
            users=False,
            roles=False,
            everyone=False,
            replied_user=False,
        ),
    )


async def send_specified_staff_dispatch_dms(
    guild: discord.Guild,
    *,
    specified_staff_ids: list[str],
    category_label: str,
    item_label: str,
    required_staff_count: int,
    dispatch_jump_url: str,
    allowed_role_ids: Iterable[str | int] = (),
    required_game_role_ids: Iterable[str | int] = (),
) -> tuple[list[str], list[str]]:
    sent: list[str] = []
    failed: list[str] = []

    for staff_id in list(dict.fromkeys(
        str(item)
        for item in specified_staff_ids
        if str(item).strip()
    )):
        try:
            member = guild.get_member(int(staff_id))
        except (TypeError, ValueError):
            member = None

        if member is None:
            try:
                member = await guild.fetch_member(int(staff_id))
            except Exception:
                member = None

        if member is None:
            failed.append(staff_id)
            continue

        member_role_ids = {
            str(role.id)
            for role in getattr(member, "roles", [])
            if getattr(role, "id", None) is not None
        }
        if not role_ids_match_requirements(
            member_role_ids,
            allowed_role_ids,
            required_game_role_ids,
        ):
            failed.append(staff_id)
            continue

        try:
            await member.send(
                "🎯 **你有一張指定單等待接單**\n"
                f"類別：{category_label}\n"
                f"項目：{item_label}\n"
                f"需求人數：{max(1, int(required_staff_count or 1))} 位\n\n"
                "你是指定人員，可直接繞過 1 分鐘公開接單鎖。\n"
                "請前往派單頻道查看完整內容並接單：\n"
                f"{dispatch_jump_url}"
            )
            sent.append(staff_id)
        except (discord.Forbidden, discord.HTTPException):
            failed.append(staff_id)

    return sent, failed


def _customer_service_role_mention(
    bot: discord.Client,
    guild: discord.Guild,
) -> str | None:
    role_id = getattr(
        bot,
        "customer_service_role_id_value",
        None,
    )
    try:
        role = guild.get_role(int(role_id))
    except (TypeError, ValueError):
        role = None
    return role.mention if role is not None else None


def _role_mentions(
    guild: discord.Guild,
    role_ids: Iterable[str | int],
) -> list[str]:
    mentions: list[str] = []

    for role_id in role_ids:
        try:
            role = guild.get_role(int(role_id))
        except (TypeError, ValueError):
            role = None

        if role is None or role.mention in mentions:
            continue

        mentions.append(role.mention)

    return mentions


def _ordered_remaining_candidate_ids(
    *,
    ranked_candidate_ids: Iterable[str | int],
    currently_eligible_ids: set[str],
    accepted_ids: set[str],
    specified_ids: set[str],
) -> list[str]:
    ranked = list(dict.fromkeys(
        str(item)
        for item in ranked_candidate_ids
        if str(item).strip()
    ))
    ranked_set = set(ranked)
    ordered = [
        *ranked,
        *sorted(currently_eligible_ids - ranked_set),
    ]
    return [
        worker_id
        for worker_id in ordered
        if (
            worker_id in currently_eligible_ids
            and worker_id not in accepted_ids
            and worker_id not in specified_ids
        )
    ]


async def smart_dispatch_escalation_loop(bot: discord.Client) -> None:
    from shared.order_acceptance import WAITING_ACCEPTANCE, get_acceptance_state

    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            plans = list_pending_smart_dispatch_plans(limit=300)

            for plan in plans:
                order_id = int(plan.get("order_id") or 0)
                if not order_id:
                    continue

                try:
                    state = get_acceptance_state(order_id)
                except Exception as exc:
                    mark_smart_dispatch_stage(
                        order_id,
                        stage=int(plan.get("stage") or 0),
                        last_error=f"acceptance_state: {type(exc).__name__}: {exc}",
                    )
                    continue

                if state.status != WAITING_ACCEPTANCE or state.is_full:
                    complete_smart_dispatch_plan(
                        order_id,
                        reason=f"order_status:{state.status}",
                    )
                    continue

                guild = bot.get_guild(getattr(bot, "guild_id_value", 0))
                if guild is None:
                    continue

                try:
                    dispatch_channel_id = int(str(plan.get("dispatch_channel_id") or "0"))
                    dispatch_message_id = int(str(plan.get("dispatch_message_id") or "0"))
                except (TypeError, ValueError):
                    complete_smart_dispatch_plan(
                        order_id,
                        reason="invalid_dispatch_reference",
                    )
                    continue

                alert_channel = guild.get_channel(SMART_DISPATCH_ALERT_CHANNEL_ID)
                if not isinstance(alert_channel, discord.TextChannel):
                    mark_smart_dispatch_stage(
                        order_id,
                        stage=int(plan.get("stage") or 0),
                        last_error="smart_dispatch_alert_channel_missing",
                    )
                    continue

                age = plan_age_seconds(plan)
                stage = int(plan.get("stage") or 0)
                required_count = max(1, int(state.required_staff_count or 1))
                accepted_ids = {
                    str(claim.staff_discord_id)
                    for claim in state.claims
                }
                specified_ids = {
                    str(item)
                    for item in (plan.get("specified_staff_ids") or [])
                }
                currently_eligible_ids = set(
                    get_eligible_dispatch_candidate_ids(
                        guild,
                        allowed_role_ids=plan.get("allowed_role_ids") or [],
                        required_game_role_ids=(
                            plan.get("required_game_role_ids") or []
                        ),
                    )
                )
                unresolved_specified = sorted(
                    (specified_ids - accepted_ids) & currently_eligible_ids
                )
                unrestricted_total = max(0, required_count - len(specified_ids))
                accepted_unrestricted = sum(
                    1
                    for worker_id in accepted_ids
                    if worker_id not in specified_ids
                )
                unrestricted_missing = max(
                    0,
                    unrestricted_total - accepted_unrestricted,
                )
                missing = max(
                    0,
                    required_count - int(state.accepted_count or 0),
                )
                jump_url = (
                    f"https://discord.com/channels/{guild.id}/{dispatch_channel_id}/{dispatch_message_id}"
                )
                remaining_general_ids = _ordered_remaining_candidate_ids(
                    ranked_candidate_ids=(plan.get("ranked_candidate_ids") or []),
                    currently_eligible_ids=currently_eligible_ids,
                    accepted_ids=accepted_ids,
                    specified_ids=specified_ids,
                )

                # T+7 分鐘（公開後 6 分鐘）：第三輪全量通知並請客服介入。
                # 若 Bot 曾離線到超過此時間，直接進入全量通知，避免補發多輪舊提醒。
                if age >= FULL_EXPANSION_SECONDS and stage < 3:
                    final_user_ids = (
                        remaining_general_ids
                        if unrestricted_missing > 0
                        else []
                    )

                    lines = [
                        "⚠️ **派單仍缺人｜第三輪全量通知**",
                        f"WEB-{order_id} 目前仍缺 **{missing} 人**。",
                    ]

                    if unresolved_specified:
                        lines.append(
                            "尚未接單的指定人員："
                            + " ".join(
                                f"<@{worker_id}>"
                                for worker_id in unresolved_specified
                            )
                        )
                        lines.append(
                            "指定名額不可由其他人直接代接；若需更換指定，請由客服調整訂單。"
                        )

                    if final_user_ids:
                        lines.append(
                            "剩餘名額通知全部目前符合資格人員："
                            + " ".join(
                                f"<@{worker_id}>"
                                for worker_id in final_user_ids
                            )
                        )

                    support_mention = _customer_service_role_mention(bot, guild)
                    if support_mention:
                        lines.append(
                            "🚨 **客服介入提醒**｜"
                            f"{support_mention} "
                            "智慧派單已進入第三輪全量通知，"
                            f"目前仍缺 **{missing} 人**，請協助確認人力。"
                        )

                    lines.append(f"前往原派單：{jump_url}")

                    try:
                        await alert_channel.send(
                            "\n".join(lines),
                            allowed_mentions=discord.AllowedMentions(
                                users=True,
                                roles=bool(support_mention),
                                everyone=False,
                            ),
                        )
                    except (discord.Forbidden, discord.HTTPException) as exc:
                        mark_smart_dispatch_stage(
                            order_id,
                            stage=stage,
                            last_error=f"full_expansion: {type(exc).__name__}: {exc}",
                        )
                        continue

                    mark_smart_dispatch_stage(
                        order_id,
                        stage=3,
                        newly_notified_ids=final_user_ids,
                    )
                    continue

                # T+4 分鐘（公開後 3 分鐘）：恢復第一版的中間擴大通知。
                # stage=0 時先補第一輪，不跳過預留的第一輪候選人。
                if age >= SECOND_WAVE_SECONDS and 1 <= stage < 2:
                    second_ids: list[str] = []
                    if unrestricted_missing > 0:
                        second_ids = [
                            worker_id
                            for worker_id in next_candidate_batch(
                                plan.get("ranked_candidate_ids") or [],
                                plan.get("notified_candidate_ids") or [],
                                required_staff_count=unrestricted_missing,
                            )
                            if (
                                worker_id in currently_eligible_ids
                                and worker_id not in accepted_ids
                                and worker_id not in specified_ids
                            )
                        ]

                    reminder_ids = list(dict.fromkeys([
                        *unresolved_specified,
                        *second_ids,
                    ]))

                    if reminder_ids:
                        lines = [
                            "🔔 **派單仍缺人｜第二輪擴大通知**",
                            f"WEB-{order_id} 目前仍缺 **{missing} 人**。",
                            " ".join(f"<@{worker_id}>" for worker_id in reminder_ids),
                            f"前往原派單：{jump_url}",
                        ]

                        try:
                            await alert_channel.send(
                                "\n".join(lines),
                                allowed_mentions=discord.AllowedMentions(
                                    users=True,
                                    roles=False,
                                    everyone=False,
                                ),
                            )
                        except (discord.Forbidden, discord.HTTPException) as exc:
                            mark_smart_dispatch_stage(
                                order_id,
                                stage=stage,
                                last_error=f"second_wave: {type(exc).__name__}: {exc}",
                            )
                            continue

                    mark_smart_dispatch_stage(
                        order_id,
                        stage=2,
                        newly_notified_ids=second_ids,
                    )
                    continue

                # T+60 秒：公開接單正式開放，這時才發第一輪智慧派單通知。
                if age >= PUBLIC_ACCEPTANCE_OPEN_SECONDS and stage < 1:
                    first_ids: list[str] = []

                    if unrestricted_missing > 0:
                        first_ids = [
                            str(worker_id)
                            for worker_id in (plan.get("notified_candidate_ids") or [])
                            if (
                                str(worker_id) in currently_eligible_ids
                                and str(worker_id) not in accepted_ids
                                and str(worker_id) not in specified_ids
                            )
                        ]

                    # 若舊 plan 沒有預先保留第一輪名單，仍從排名中補出一批，
                    # 避免部署切換當下的等待單被漏通知。
                    if unrestricted_missing > 0 and not first_ids:
                        first_ids = [
                            worker_id
                            for worker_id in next_candidate_batch(
                                plan.get("ranked_candidate_ids") or [],
                                [],
                                required_staff_count=unrestricted_missing,
                            )
                            if (
                                worker_id in currently_eligible_ids
                                and worker_id not in accepted_ids
                                and worker_id not in specified_ids
                            )
                        ]

                    if unrestricted_missing > 0 and not first_ids:
                        first_ids = list(remaining_general_ids)

                    if first_ids:
                        lines = [
                            "🟢 **新單已開放接單｜第一輪通知**",
                            f"WEB-{order_id} 目前尚缺 **{missing} 人**。",
                            "開放接單通知："
                            + " ".join(
                                f"<@{worker_id}>"
                                for worker_id in first_ids
                            ),
                            f"前往原派單：{jump_url}",
                        ]

                        try:
                            await alert_channel.send(
                                "\n".join(lines),
                                allowed_mentions=discord.AllowedMentions(
                                    users=True,
                                    roles=False,
                                    everyone=False,
                                ),
                            )
                        except (discord.Forbidden, discord.HTTPException) as exc:
                            mark_smart_dispatch_stage(
                                order_id,
                                stage=stage,
                                last_error=f"first_wave_unlock: {type(exc).__name__}: {exc}",
                            )
                            continue

                    mark_smart_dispatch_stage(
                        order_id,
                        stage=1,
                        newly_notified_ids=first_ids,
                    )
                    continue

                # 第三輪全量通知完成後，才進入每 10 分鐘持續提醒。
                if stage >= 3:
                    updated_text = str(plan.get("updated_at") or "").strip()
                    try:
                        updated = datetime.fromisoformat(updated_text.replace("Z", "+00:00"))
                    except ValueError:
                        updated = None

                    if updated is not None:
                        if updated.tzinfo is None:
                            updated = updated.replace(tzinfo=timezone.utc)
                        seconds_since_update = max(
                            0,
                            int((datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds()),
                        )
                    else:
                        seconds_since_update = REPEAT_REMINDER_SECONDS

                    if seconds_since_update < REPEAT_REMINDER_SECONDS:
                        continue

                    repeat_ids = list(dict.fromkeys([
                        *unresolved_specified,
                        *remaining_general_ids,
                    ]))

                    if repeat_ids:
                        lines = [
                            "📣 **派單仍缺人｜10 分鐘提醒**",
                            f"WEB-{order_id} 目前仍缺 **{missing} 人**。",
                            " ".join(f"<@{worker_id}>" for worker_id in repeat_ids),
                            f"前往原派單：{jump_url}",
                        ]

                        try:
                            await alert_channel.send(
                                "\n".join(lines),
                                allowed_mentions=discord.AllowedMentions(
                                    users=True,
                                    roles=False,
                                    everyone=False,
                                ),
                            )
                        except (discord.Forbidden, discord.HTTPException) as exc:
                            mark_smart_dispatch_stage(
                                order_id,
                                stage=stage,
                                last_error=f"repeat_reminder: {type(exc).__name__}: {exc}",
                            )
                            continue

                    mark_smart_dispatch_stage(
                        order_id,
                        # 保留第三輪 stage=3；循環提醒不可讓 stage 倒退。
                        stage=stage,
                    )

        except Exception as exc:
            print(
                f"[smart-dispatch] escalation loop error: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

        await asyncio.sleep(SMART_DISPATCH_LOOP_SECONDS)
