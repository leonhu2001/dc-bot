from pathlib import Path


def repair_payment_panel_command() -> None:
    path = Path("bot.py")
    source = path.read_text(encoding="utf-8")
    start_marker = '@bot.tree.command(\n    name="fix_acceptance_payment_panel",'
    end_marker = '@bot.tree.command(\n    name="staff_profile_panel",'
    start = source.index(start_marker)
    end = source.index(end_marker, start)

    replacement = '''@bot.tree.command(
    name="fix_acceptance_payment_panel",
    description="依票口 ID 補送等待付款 Panel",
    guild=discord.Object(id=GUILD_ID),
)
@app_commands.describe(
    ticket_channel_id="Discord 票口頻道 ID，例如 1557267849578545252"
)
@app_commands.default_permissions(manage_messages=True)
async def fix_acceptance_payment_panel(
    interaction: discord.Interaction,
    ticket_channel_id: str,
):
    if not _require_customer_staff_or_manager(interaction):
        await interaction.response.send_message(
            "只有客服、店長或管理員可以補送付款 Panel。",
            ephemeral=True,
        )
        return

    if interaction.guild is None:
        await interaction.response.send_message(
            "這個功能只能在伺服器內使用。",
            ephemeral=True,
        )
        return

    # 先 ACK Discord，避免後續 DB / API 查詢超過 interaction timeout。
    await interaction.response.defer(ephemeral=True)

    try:
        channel_id = int(str(ticket_channel_id).strip())
    except (TypeError, ValueError):
        await interaction.followup.send(
            "票口 ID 格式錯誤，請輸入純數字 Discord 頻道 ID。",
            ephemeral=True,
        )
        return

    ticket_channel = interaction.guild.get_channel(channel_id)

    if not isinstance(ticket_channel, discord.TextChannel):
        try:
            fetched_channel = await interaction.guild.fetch_channel(channel_id)
            ticket_channel = (
                fetched_channel
                if isinstance(fetched_channel, discord.TextChannel)
                else None
            )
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            ticket_channel = None

    if ticket_channel is None:
        await interaction.followup.send(
            f"找不到票口頻道 `{channel_id}`。",
            ephemeral=True,
        )
        return

    import sqlite3

    db_path = Path(__file__).parent / "web_dashboard.db"
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row

    try:
        row = conn.execute(
            """
            SELECT id, status, ticket_channel_id
            FROM web_orders
            WHERE CAST(ticket_channel_id AS TEXT) = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (str(channel_id),),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        await interaction.followup.send(
            f"票口 <#{channel_id}> 找不到對應的 WEB 訂單。",
            ephemeral=True,
        )
        return

    target_order_id = int(row["id"])
    current_status = str(row["status"] or "").strip().lower()

    if current_status not in {
        "accepted_pending_pay",
        "waiting_acceptance",
    }:
        await interaction.followup.send(
            f"WEB-{target_order_id} 目前狀態為 `{current_status}`，"
            "只有等待接單或接單完成待付款的訂單可以補送付款 Panel。",
            ephemeral=True,
        )
        return

    # 清除舊付款訊息記錄，讓 restore function 重新送出付款 Panel。
    order_data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(
        channel_id,
        {},
    )

    old_message_id = order_data.pop(
        "payment_message_id",
        None,
    )
    order_data.pop(
        "payment_channel_id",
        None,
    )

    remember_order_data(
        channel_id,
        order_data,
    )

    try:
        ok, message = await asyncio.wait_for(
            restore_acceptance_payment_panel_for_order(
                interaction.guild,
                target_order_id,
                reason=f"manual_ticket_repair_by_{interaction.user.id}",
            ),
            timeout=20,
        )
    except asyncio.TimeoutError:
        await interaction.followup.send(
            "補送付款 Panel 超過 20 秒，已停止等待。\n"
            "請先確認票口權限與 Bot 狀態，再重新執行此指令。\n"
            f"票口：<#{channel_id}>｜訂單：WEB-{target_order_id}",
            ephemeral=True,
        )
        return
    except Exception as exc:
        print(
            f"[payment-panel-fix] "
            f"ticket={channel_id} "
            f"order={target_order_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        await interaction.followup.send(
            f"補送付款 Panel 失敗：`{type(exc).__name__}: {exc}`\n"
            f"票口：<#{channel_id}>｜訂單：WEB-{target_order_id}",
            ephemeral=True,
        )
        return

    if ok:
        await interaction.followup.send(
            "✅ 付款 Panel 已重新送出。\n"
            f"票口：<#{channel_id}>\n"
            f"訂單：WEB-{target_order_id}\n"
            f"舊 Panel 訊息 ID：{old_message_id or '無'}\n"
            f"{message}",
            ephemeral=True,
        )
    else:
        await interaction.followup.send(
            "❌ 無法補送付款 Panel。\n"
            f"票口：<#{channel_id}>\n"
            f"訂單：WEB-{target_order_id}\n"
            f"{message}",
            ephemeral=True,
        )



'''
    block = source[start:end]
    if "???" not in block:
        raise RuntimeError("payment panel command no longer contains corrupted copy")
    path.write_text(source[:start] + replacement + source[end:], encoding="utf-8")


def repair_dispatch_stages() -> None:
    path = Path("views/smart_dispatch.py")
    source = path.read_text(encoding="utf-8")
    guard = '                if stage >= 1:\n                    updated_text = str(plan.get("updated_at") or "").strip()'
    if guard not in source:
        raise RuntimeError("repeat reminder stage guard not found")
    source = source.replace(
        guard,
        '                # 第三次通知起才進入每 10 分鐘循環；第二輪完成前不可提前進入。\n'
        '                if stage >= 2:\n'
        '                    updated_text = str(plan.get("updated_at") or "").strip()',
        1,
    )

    tail = '''                    mark_smart_dispatch_stage(
                        order_id,
                        stage=1,
                    )
'''
    if tail not in source:
        raise RuntimeError("repeat reminder stage tail not found")
    source = source.replace(
        tail,
        '''                    mark_smart_dispatch_stage(
                        order_id,
                        # 保留第二輪 stage=2；不可降回 1，否則下一輪會重送第二輪通知。
                        stage=stage,
                    )
''',
        1,
    )
    path.write_text(source, encoding="utf-8")


def add_regressions() -> None:
    Path("tests/test_payment_panel_and_dispatch_source_regressions.py").write_text(
        '''from pathlib import Path


def test_payment_panel_repair_command_has_readable_copy():
    source = Path("bot.py").read_text(encoding="utf-8")
    start = source.index('name="fix_acceptance_payment_panel"')
    end = source.index('name="staff_profile_panel"', start)
    block = source[start:end]

    assert "???" not in block
    assert "依票口 ID 補送等待付款 Panel" in block
    assert "只有客服、店長或管理員可以補送付款 Panel" in block


def test_repeat_reminders_only_start_after_second_round_and_keep_stage_two():
    source = Path("views/smart_dispatch.py").read_text(encoding="utf-8")
    assert "if stage >= 2:" in source
    assert "第三次通知起才進入每 10 分鐘循環" in source
    assert "不可降回 1" in source
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    repair_payment_panel_command()
    repair_dispatch_stages()
    add_regressions()
