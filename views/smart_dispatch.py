from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import discord

SMART_DISPATCH_ALERT_CHANNEL_ID = 1555881625844191322
REPEAT_REMINDER_SECONDS = 600

from services.order_rules import role_ids_match_requirements
from services.smart_dispatch import (
    FIRST_EXPANSION_SECONDS,
        choose_initial_candidate_ids,
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


def prepare_initial_smart_dispatch(
    guild: discord.Guild,
    *,
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

    ranked_ids = rank_dispatch_candidates(
        candidate_ids,
        specified_staff_ids=specified_staff_ids,
        db_file=db_file,
    )

    initial_ids = choose_initial_candidate_ids(
        ranked_ids,
        specified_staff_ids=specified_staff_ids,
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
    general_initial = [
        worker_id
        for worker_id in initial_ids
        if worker_id not in specified_set
    ]

    lines: list[str] = []

    if specified_initial:
        lines.append(
            "🎯 **指定單優先通知**｜"
            + " ".join(f"<@{worker_id}>" for worker_id in specified_initial)
        )

    if general_initial:
        prefix = "🔔 **優先派單**｜" if not specified_initial else "🔔 **剩餘名額優先通知**｜"
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
        "initial_notified_ids": initial_ids,
        "required_game_role_ids": [
            str(role_id)
            for role_id in required_game_role_ids
            if str(role_id).strip()
        ],
        "content": "\n".join(lines),
    }


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

                if age >= FIRST_EXPANSION_SECONDS and stage < 1:
                    next_ids = []

                    if unrestricted_missing > 0:
                        next_ids = [
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
                        *next_ids,
                    ]))

                    if reminder_ids:
                        lines = [
                            "🔔 **派單仍缺人｜第二輪通知**",
                            f"WEB-{order_id} 目前仍缺 **{missing} 人**。",
                        ]

                        if unresolved_specified:
                            lines.append(
                                "指定人員提醒："
                                + " ".join(
                                    f"<@{worker_id}>"
                                    for worker_id in unresolved_specified
                                )
                            )

                        if next_ids:
                            lines.append(
                                "剩餘名額通知："
                                + " ".join(
                                    f"<@{worker_id}>"
                                    for worker_id in next_ids
                                )
                            )

                        lines.append(f"前往原派單：{jump_url}")

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
                        stage=1,
                        newly_notified_ids=next_ids,
                    )
                    continue

                if stage >= 1:
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
                        *[
                            worker_id
                            for worker_id in (plan.get("ranked_candidate_ids") or [])
                            if (
                                worker_id in currently_eligible_ids
                                and worker_id not in accepted_ids
                                and worker_id not in specified_ids
                            )
                        ],
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
                        stage=1,
                    )

        except Exception as exc:
            print(
                f"[smart-dispatch] escalation loop error: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

        await asyncio.sleep(60)

