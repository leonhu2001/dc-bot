from pathlib import Path

path = Path("bot.py")
text = path.read_text(encoding="utf-8")

worker_code = r'''

WEB_SYNC_EVENT_TASK = None


def _web_dashboard_db_path_for_bot() -> str:
    from pathlib import Path

    return str(Path(__file__).with_name("web_dashboard.db"))


def _web_sync_fetch_pending_events(limit: int = 10) -> list[dict]:
    import sqlite3

    conn = sqlite3.connect(_web_dashboard_db_path_for_bot())
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT
                e.id AS event_id,
                e.order_id,
                e.event_type,
                e.retry_count,
                w.id AS web_order_id,
                w.dispatch_channel_id,
                w.dispatch_message_id,
                w.category,
                w.item,
                w.quantity,
                w.amount,
                w.customer_discord_id,
                w.customer_display_name
            FROM sync_events e
            JOIN web_orders w ON w.id = e.order_id
            WHERE e.status = 'pending'
            ORDER BY e.id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        conn.close()


def _web_sync_get_assignments(order_id: int) -> list[dict]:
    import sqlite3

    conn = sqlite3.connect(_web_dashboard_db_path_for_bot())
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT
                worker_discord_id,
                worker_display_name,
                role_type,
                is_active
            FROM order_assignments
            WHERE order_id = ?
              AND is_active = 1
            ORDER BY id ASC
            """,
            (order_id,),
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        conn.close()


def _web_sync_mark_event_done(event_id: int) -> None:
    import sqlite3

    conn = sqlite3.connect(_web_dashboard_db_path_for_bot())

    try:
        conn.execute(
            """
            UPDATE sync_events
            SET status = 'done',
                error_message = NULL,
                processed_at = datetime('now')
            WHERE id = ?
            """,
            (event_id,),
        )
        conn.commit()
    finally:
        conn.close()


def _web_sync_mark_event_failed(event_id: int, error_message: str, retry_count: int) -> None:
    import sqlite3

    next_retry = int(retry_count or 0) + 1
    next_status = "failed" if next_retry >= 3 else "pending"

    conn = sqlite3.connect(_web_dashboard_db_path_for_bot())

    try:
        conn.execute(
            """
            UPDATE sync_events
            SET status = ?,
                error_message = ?,
                retry_count = ?,
                processed_at = CASE WHEN ? = 'failed' THEN datetime('now') ELSE processed_at END
            WHERE id = ?
            """,
            (next_status, error_message[:1000], next_retry, next_status, event_id),
        )
        conn.commit()
    finally:
        conn.close()


def _web_sync_build_receiver_text(assignments: list[dict]) -> str:
    companions = []
    boosters = []

    for row in assignments:
        user_id = str(row.get("worker_discord_id") or "").strip()
        display_name = str(row.get("worker_display_name") or user_id).strip()
        role_type = str(row.get("role_type") or "booster").strip()

        if not user_id:
            continue

        text = f"<@{user_id}>"

        if role_type == "companion":
            companions.append(text)
        else:
            boosters.append(text)

    parts = []

    if boosters:
        parts.append("打手：" + "、".join(boosters))

    if companions:
        parts.append("陪玩：" + "、".join(companions))

    if not parts:
        return "尚未有人接單"

    return "\n".join(parts)


def _web_sync_embed_without_receiver_fields(embed):
    blocked_names = {
        "目前接單",
        "目前接單人",
        "接單狀態",
        "接單人員",
        "打手接單",
        "陪玩接單",
        "已接人員",
    }

    old_fields = list(embed.fields)
    embed.clear_fields()

    for field in old_fields:
        if str(field.name).strip() in blocked_names:
            continue

        embed.add_field(
            name=field.name,
            value=field.value,
            inline=field.inline,
        )

    return embed


async def process_one_web_sync_event(event: dict) -> None:
    event_id = int(event["event_id"])
    retry_count = int(event.get("retry_count") or 0)

    try:
        dispatch_channel_id = int(event.get("dispatch_channel_id") or 0)
        dispatch_message_id = int(event.get("dispatch_message_id") or 0)

        if not dispatch_channel_id or not dispatch_message_id:
            raise RuntimeError("web order missing dispatch channel/message id")

        channel = bot.get_channel(dispatch_channel_id)

        if channel is None:
            channel = await bot.fetch_channel(dispatch_channel_id)

        message = await channel.fetch_message(dispatch_message_id)

        assignments = _web_sync_get_assignments(int(event["order_id"]))
        receiver_text = _web_sync_build_receiver_text(assignments)

        if message.embeds:
            embed = message.embeds[0].copy()
        else:
            embed = discord.Embed(title="派單訊息", color=discord.Color.blue())

        embed = _web_sync_embed_without_receiver_fields(embed)
        embed.add_field(
            name="目前接單",
            value=receiver_text,
            inline=False,
        )

        await message.edit(
            embed=embed,
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

        _web_sync_mark_event_done(event_id)
        print(f"[web-sync] event_id={event_id} done order_id={event.get('order_id')}")

    except Exception as exc:
        _web_sync_mark_event_failed(event_id, str(exc), retry_count)
        print(f"處理網站同步事件失敗 event_id={event_id}：{exc}")


async def web_sync_event_worker() -> None:
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            events = _web_sync_fetch_pending_events(limit=10)

            for event in events:
                await process_one_web_sync_event(event)

        except Exception as exc:
            print(f"[web-sync] 背景處理器失敗：{exc}")

        await asyncio.sleep(5)


def ensure_web_sync_event_worker_started() -> None:
    global WEB_SYNC_EVENT_TASK

    if WEB_SYNC_EVENT_TASK is not None and not WEB_SYNC_EVENT_TASK.done():
        return

    WEB_SYNC_EVENT_TASK = bot.loop.create_task(web_sync_event_worker())
    print("[web-sync] 背景同步事件處理器已啟動")
'''

if "async def web_sync_event_worker" not in text:
    marker = "# ========= 資料庫健康檢查指令 ========="
    if marker not in text:
        raise RuntimeError("找不到插入位置")
    text = text.replace(marker, worker_code + "\n\n" + marker, 1)
    print("inserted web sync worker")
else:
    print("web sync worker already exists")

# 在 on_ready 裡啟動 worker
if "ensure_web_sync_event_worker_started()" not in text:
    on_ready = text.find("async def on_ready")
    if on_ready == -1:
        raise RuntimeError("找不到 async def on_ready")

    line_end = text.find("\n", on_ready)
    insert_at = line_end + 1

    text = text[:insert_at] + "    ensure_web_sync_event_worker_started()\n" + text[insert_at:]
    print("patched on_ready to start web sync worker")
else:
    print("on_ready already starts web sync worker")

path.write_text(text, encoding="utf-8")
print("done")
