from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"{label}: target block not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def repair_vip_benefit_display() -> None:
    path = ROOT / "core" / "vip_levels.py"
    text = path.read_text(encoding="utf-8")

    start = text.index("# Discord 會員資訊只顯示該等級新增的福利")
    end = text.index("VIP_LEVELS: list[dict[str, Any]]", start)
    replacement = (
        "# benefit_keys 是每個 VIP 等級『實際生效』的完整權益。\n"
        "# 高等級沿用低等級的一般福利；同類型回饋／折扣只保留當前最高值。\n"
    )
    text = text[:start] + replacement + text[end:]

    old = '''def build_vip_level_benefits() -> dict[str, str]:
    benefits: dict[str, str] = {"普通魔丸": "尚未解鎖 VIP 福利。"}

    for level in VIP_LEVELS:
        level_name = str(level["name"])
        lines = [f"累積消費 {int(level['threshold'])}⤴️"]
        display_lines = VIP_LEVEL_DISPLAY_BENEFITS.get(level_name)

        if display_lines is None:
            display_lines = tuple(
                VIP_BENEFIT_ITEMS[key]
                for key in level.get("benefit_keys", [])
                if key in VIP_BENEFIT_ITEMS
            )

        lines.extend(display_lines)
        benefits[level_name] = "\\n".join(lines)

    return benefits
'''
    new = '''def build_vip_level_benefits() -> dict[str, str]:
    benefits: dict[str, str] = {"普通魔丸": "尚未解鎖 VIP 福利。"}

    for level in VIP_LEVELS:
        lines = [f"累積消費 {int(level['threshold'])}⤴️"]
        lines.extend(
            VIP_BENEFIT_ITEMS[key]
            for key in level.get("benefit_keys", [])
            if key in VIP_BENEFIT_ITEMS
        )
        benefits[str(level["name"])] = "\\n".join(lines)

    return benefits
'''
    if old not in text:
        raise RuntimeError("VIP benefit builder target not found")
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


def repair_smart_dispatch_cadence() -> None:
    path = ROOT / "views" / "smart_dispatch.py"
    text = path.read_text(encoding="utf-8")

    old_constants = '''SMART_DISPATCH_ALERT_CHANNEL_ID = 1555881625844191322
PUBLIC_ACCEPTANCE_OPEN_SECONDS = 60
SECOND_ROUND_AFTER_OPEN_SECONDS = 360
SECOND_ROUND_SECONDS = PUBLIC_ACCEPTANCE_OPEN_SECONDS + SECOND_ROUND_AFTER_OPEN_SECONDS
REPEAT_REMINDER_SECONDS = 600
SMART_DISPATCH_LOOP_SECONDS = 10
'''
    new_constants = '''SMART_DISPATCH_ALERT_CHANNEL_ID = 1555881625844191322
PUBLIC_ACCEPTANCE_OPEN_SECONDS = 60
# 保留第一版智慧派單節奏：公開開放後 3 分鐘擴大一批、6 分鐘全量通知。
SECOND_WAVE_AFTER_OPEN_SECONDS = 180
FULL_EXPANSION_AFTER_OPEN_SECONDS = 360
SECOND_WAVE_SECONDS = PUBLIC_ACCEPTANCE_OPEN_SECONDS + SECOND_WAVE_AFTER_OPEN_SECONDS
FULL_EXPANSION_SECONDS = PUBLIC_ACCEPTANCE_OPEN_SECONDS + FULL_EXPANSION_AFTER_OPEN_SECONDS
REPEAT_REMINDER_SECONDS = 600
SMART_DISPATCH_LOOP_SECONDS = 10
'''
    if old_constants not in text:
        raise RuntimeError("smart dispatch constants target not found")
    text = text.replace(old_constants, new_constants, 1)

    old_sender = '''async def send_initial_smart_dispatch_alert(
    guild: discord.Guild,
    *,
    content: str | None,
    dispatch_jump_url: str,
) -> discord.Message | None:
    """Defer public smart-dispatch pings until the one-minute lock expires.

    Call sites remain unchanged; the persistent smart-dispatch plan drives the
    actual first public notification so process restarts do not lose it.
    Specified staff are still DM'd separately and may accept immediately.
    """
    _ = guild, content, dispatch_jump_url
    return None
'''
    new_sender = '''async def send_initial_smart_dispatch_alert(
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
        "🔒 **新單已建立｜1 分鐘接單保護期**\\n"
        "新訂單已建立，公開接單將於 **1 分鐘後** 開放。\\n"
        "指定人員若符合訂單資格，可立即接單。\\n"
        f"前往原派單：{dispatch_jump_url}",
        allowed_mentions=discord.AllowedMentions(
            users=False,
            roles=False,
            everyone=False,
            replied_user=False,
        ),
    )
'''
    if old_sender not in text:
        raise RuntimeError("initial dispatch sender target not found")
    text = text.replace(old_sender, new_sender, 1)

    block_start = text.index(
        "                # 公開接單後再過 6 分鐘仍未滿：全量提醒目前仍符合資格的人員並通知客服。"
    )
    block_end = text.index(
        "                # T+60 秒：公開接單正式開放，這時才發第一輪智慧派單通知。",
        block_start,
    )

    new_block = '''                # T+7 分鐘（公開後 6 分鐘）：第三輪全量通知並請客服介入。
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
                            "\\n".join(lines),
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
                                "\\n".join(lines),
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

'''
    text = text[:block_start] + new_block + text[block_end:]

    text = text.replace(
        "                # 第三次通知起才進入每 10 分鐘循環；第二輪完成前不可提前進入。\n"
        "                if stage >= 2:",
        "                # 第三輪全量通知完成後，才進入每 10 分鐘持續提醒。\n"
        "                if stage >= 3:",
        1,
    )
    text = text.replace(
        "                        # 保留第二輪 stage=2；不可降回 1，否則下一輪會重送第二輪通知。\n"
        "                        stage=stage,",
        "                        # 保留第三輪 stage=3；循環提醒不可讓 stage 倒退。\n"
        "                        stage=stage,",
        1,
    )

    path.write_text(text, encoding="utf-8")


def strengthen_compile_coverage() -> None:
    ci = ROOT / ".github" / "workflows" / "ci.yml"
    text = ci.read_text(encoding="utf-8")
    old = "          python -m compileall -q             bot.py             cogs             core             services             shared             web/app\n"
    new = '''          python -m compileall -q \\
            bot.py \\
            cogs \\
            core \\
            services \\
            shared \\
            views \\
            web/app \\
            tools \\
            scripts
'''
    if old not in text:
        raise RuntimeError("CI compile target not found")
    ci.write_text(text.replace(old, new, 1), encoding="utf-8")

    deploy = ROOT / "scripts" / "deploy_main.sh"
    text = deploy.read_text(encoding="utf-8")
    old = '''/opt/dc-bot/venv/bin/python -m compileall -q \\
    bot.py \\
    cogs \\
    core \\
    services \\
    shared \\
    web/app
'''
    new = '''/opt/dc-bot/venv/bin/python -m compileall -q \\
    bot.py \\
    cogs \\
    core \\
    services \\
    shared \\
    views \\
    web/app \\
    tools \\
    scripts
'''
    if old not in text:
        raise RuntimeError("deploy compile target not found")
    deploy.write_text(text.replace(old, new, 1), encoding="utf-8")


def update_regressions() -> None:
    path = ROOT / "tests" / "test_payment_panel_and_dispatch_source_regressions.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace('assert "if stage >= 2:" in source', 'assert "if stage >= 3:" in source')
    text = text.replace(
        'assert "第三次通知起才進入每 10 分鐘循環" in source',
        'assert "第三輪全量通知完成後，才進入每 10 分鐘持續提醒" in source',
    )
    text = text.replace('assert "不可降回 1" in source', 'assert "循環提醒不可讓 stage 倒退" in source')
    path.write_text(text, encoding="utf-8")

    vip_test = ROOT / "tests" / "test_vip_copy.py"
    text = vip_test.read_text(encoding="utf-8")
    old = '''    assert "・享有金級魔丸所有福利" in VIP_LEVEL_BENEFITS["白金魔丸"]
    assert "可建立 VIP 專屬私人文字頻道" not in VIP_LEVEL_BENEFITS["白金魔丸"]
    assert "・每月一次免費「機密航天保底1000w」或娛樂陪 2H" in VIP_LEVEL_BENEFITS["黑鑽魔丸"]
'''
    new = '''    diamond_lines = VIP_LEVEL_BENEFITS["鑽石魔丸"].splitlines()
    assert diamond_lines == [
        "累積消費 25000⤴️",
        "・專屬 VIP 身分組，可使用VIP專屬包廂",
        "・優先客服回覆",
        "・每月一張折現券200T",
        "・優先排單",
        "・優先安排熟悉打手",
        "・儲值返利3%",
        "・體驗單、趣味單外全館96折",
        '・可根據闆闆要求製作"自訂單"',
    ]
    assert "儲值返利2%" not in VIP_LEVEL_BENEFITS["鑽石魔丸"]
    assert "全館98折" not in VIP_LEVEL_BENEFITS["鑽石魔丸"]
    assert "享有白金魔丸所有福利" not in VIP_LEVEL_BENEFITS["鑽石魔丸"]
    assert "可建立 VIP 專屬私人文字頻道" not in VIP_LEVEL_BENEFITS["白金魔丸"]
    assert "・每月一次免費「機密航天保底1000w」或娛樂陪 2H" in VIP_LEVEL_BENEFITS["黑鑽魔丸"]
'''
    if old not in text:
        raise RuntimeError("VIP copy regression target not found")
    vip_test.write_text(text.replace(old, new, 1), encoding="utf-8")

    cadence_test = ROOT / "tests" / "test_smart_dispatch_cadence.py"
    cadence_test.write_text('''import asyncio\n\nfrom views import smart_dispatch\n\n\ndef test_smart_dispatch_restores_three_fixed_public_rounds():\n    assert smart_dispatch.PUBLIC_ACCEPTANCE_OPEN_SECONDS == 60\n    assert smart_dispatch.SECOND_WAVE_SECONDS == 240\n    assert smart_dispatch.FULL_EXPANSION_SECONDS == 420\n    assert smart_dispatch.REPEAT_REMINDER_SECONDS == 600\n\n\ndef test_initial_locked_alert_is_immediate_and_has_no_mentions():\n    sent = {}\n\n    class Channel:\n        async def send(self, content, **kwargs):\n            sent["content"] = content\n            sent.update(kwargs)\n            return object()\n\n    class Guild:\n        def get_channel(self, channel_id):\n            assert channel_id == smart_dispatch.SMART_DISPATCH_ALERT_CHANNEL_ID\n            return Channel()\n\n    result = asyncio.run(\n        smart_dispatch.send_initial_smart_dispatch_alert(\n            Guild(),\n            content="<@123> should never be forwarded",\n            dispatch_jump_url="https://discord.com/channels/1/2/3",\n        )\n    )\n\n    assert result is not None\n    assert "新單已建立｜1 分鐘接單保護期" in sent["content"]\n    assert "指定人員若符合訂單資格，可立即接單" in sent["content"]\n    assert "<@" not in sent["content"]\n    assert sent["allowed_mentions"].users is False\n    assert sent["allowed_mentions"].roles is False\n    assert sent["allowed_mentions"].everyone is False\n''', encoding="utf-8")


def source_text_sanity_check() -> None:
    bad = []
    roots = [ROOT / "bot.py", ROOT / "cogs", ROOT / "core", ROOT / "services", ROOT / "shared", ROOT / "views", ROOT / "web" / "app"]
    for root in roots:
        paths = [root] if root.is_file() else list(root.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix.lower() not in {".py", ".html", ".js", ".yml", ".yaml"}:
                continue
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            if "�" in text:
                bad.append(f"replacement character: {path.relative_to(ROOT)}")
            if "???" in text and "test" not in path.parts:
                bad.append(f"suspicious ???: {path.relative_to(ROOT)}")
    if bad:
        raise RuntimeError("source text sanity failed: " + "; ".join(bad))


if __name__ == "__main__":
    repair_vip_benefit_display()
    repair_smart_dispatch_cadence()
    strengthen_compile_coverage()
    update_regressions()
    source_text_sanity_check()
