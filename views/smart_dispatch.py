from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Iterable

import discord

from services.smart_dispatch import (
    FIRST_EXPANSION_SECONDS,
    FULL_EXPANSION_SECONDS,
    choose_initial_candidate_ids,
    complete_smart_dispatch_plan,
    list_pending_smart_dispatch_plans,
    mark_smart_dispatch_stage,
    next_candidate_batch,
    plan_age_seconds,
    rank_dispatch_candidates,
)


def _member_has_required_role(
    member,
    required_role_id: str | int | None,
) -> bool:
    required = str(required_role_id or "").strip()
    if not required:
        return True

    return any(
        str(getattr(role, "id", "") or "") == required
        for role in getattr(member, "roles", []) or []
    )


def _guild_member_has_required_role(
    guild: discord.Guild,
    worker_id: str | int,
    required_role_id: str | int | None,
) -> bool:
    try:
        member = guild.get_member(int(str(worker_id)))
    except (TypeError, ValueError):
        member = None

    return (
        member is not None
        and _member_has_required_role(
            member,
            required_role_id,
        )
    )


def get_eligible_dispatch_candidate_ids(
    guild: discord.Guild,
    *,
    allowed_role_ids: Iterable[str | int],
    specified_staff_ids: Iterable[str | int] = (),
    required_role_id: str | int | None = None,
) -> list[str]:
    allowed = {
        str(role_id)
        for role_id in allowed_role_ids
        if str(role_id).strip()
    }

    result: list[str] = []

    for member in guild.members:
        if getattr(member, "bot", False):
            continue

        member_roles = {
            str(role.id)
            for role in getattr(member, "roles", [])
            if getattr(role, "id", None) is not None
        }

        if (
            member_roles & allowed
            and _member_has_required_role(
                member,
                required_role_id,
            )
        ):
            result.append(str(member.id))

    # 指定人員在建立訂單前已由訂單規則驗證過；
    # 這裡只補 guild cache 邊界，避免指定人員因 cache 暫時不完整漏掉第一輪通知。
    for staff_id in specified_staff_ids:
        staff_id_text = str(staff_id).strip()
        if not staff_id_text or staff_id_text in result:
            continue

        try:
            member = guild.get_member(int(staff_id_text))
        except (TypeError, ValueError):
            member = None

        if (
            member is not None
            and not getattr(member, "bot", False)
            and _member_has_required_role(
                member,
                required_role_id,
            )
        ):
            result.append(staff_id_text)

    return result


def prepare_initial_smart_dispatch(
    guild: discord.Guild,
    *,
    allowed_role_ids: list[str],
    specified_staff_ids: list[str],
    required_staff_count: int,
    required_role_id: str | int | None = None,
    excluded_staff_ids: Iterable[str | int] = (),
    db_file: str | Path | None = None,
) -> dict:
    candidate_ids = get_eligible_dispatch_candidate_ids(
        guild,
        allowed_role_ids=allowed_role_ids,
        specified_staff_ids=specified_staff_ids,
        required_role_id=required_role_id,
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
        if required_role_id:
            lines.append(
                "⚠️ 目前找不到同時符合接單職位與平台身分的可通知人員，"
                "請客服確認端遊 / 手遊身分組設定。"
            )
        else:
            role_mentions = []
            for role_id in allowed_role_ids:
                try:
                    role = guild.get_role(int(role_id))
                except (TypeError, ValueError):
                    role = None
                if role is not None and role.mention not in role_mentions:
                    role_mentions.append(role.mention)

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
    required_role_id: str | int | None = None,
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

        if not _member_has_required_role(
            member,
            required_role_id,
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
                    channel_id = int(str(plan.get("dispatch_channel_id") or "0"))
                    message_id = int(str(plan.get("dispatch_message_id") or "0"))
                except (TypeError, ValueError):
                    complete_smart_dispatch_plan(
                        order_id,
                        reason="invalid_dispatch_reference",
                    )
                    continue

                channel = guild.get_channel(channel_id)
                if not isinstance(channel, discord.TextChannel):
                    complete_smart_dispatch_plan(
                        order_id,
                        reason="dispatch_channel_missing",
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
                required_role_id = str(
                    plan.get("required_role_id") or ""
                ).strip()

                unresolved_specified = sorted(
                    worker_id
                    for worker_id in (specified_ids - accepted_ids)
                    if (
                        not required_role_id
                        or _guild_member_has_required_role(
                            guild,
                            worker_id,
                            required_role_id,
                        )
                    )
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
                    f"https://discord.com/channels/{guild.id}/{channel_id}/{message_id}"
                )

                # 如果 Bot 曾離線到超過完整擴大時間，直接做最終通知，
                # 避免重啟瞬間連發第二輪 + 第三輪兩則提醒。
                if age >= FULL_EXPANSION_SECONDS and stage < 2:
                    constrained_user_mentions: list[str] = []

                    if required_role_id and unrestricted_missing > 0:
                        constrained_user_mentions = [
                            worker_id
                            for worker_id in (
                                plan.get("ranked_candidate_ids") or []
                            )
                            if (
                                worker_id not in accepted_ids
                                and worker_id not in specified_ids
                            )
                        ]

                    role_mentions = (
                        _role_mentions(
                            guild,
                            plan.get("allowed_role_ids") or [],
                        )
                        if (
                            unrestricted_missing > 0
                            and not required_role_id
                        )
                        else []
                    )

                    lines = [
                        "⚠️ **派單仍缺人｜最終擴大通知**",
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

                    if constrained_user_mentions:
                        lines.append(
                            "剩餘非指定名額已擴大通知所有符合職位 + 平台資格人員："
                            + " ".join(
                                f"<@{worker_id}>"
                                for worker_id in constrained_user_mentions
                            )
                        )

                    if role_mentions:
                        lines.append(
                            "剩餘非指定名額已擴大通知全部符合資格身分組："
                            + " ".join(role_mentions)
                        )

                    lines.append(f"原派單：{jump_url}")

                    try:
                        await channel.send(
                            "\n".join(lines),
                            allowed_mentions=discord.AllowedMentions(
                                users=True,
                                roles=bool(role_mentions),
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

                    complete_smart_dispatch_plan(
                        order_id,
                        reason="full_expansion_sent",
                    )
                    continue

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
                                worker_id not in accepted_ids
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

                        lines.append(f"原派單：{jump_url}")

                        try:
                            await channel.send(
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

        except Exception as exc:
            print(
                f"[smart-dispatch] escalation loop error: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

        await asyncio.sleep(60)
