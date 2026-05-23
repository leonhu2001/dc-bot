from pathlib import Path
import re

path = Path("bot.py")
text = path.read_text(encoding="utf-8")

# 1. 移除會整包覆蓋網站資料的舊同步
text = text.replace(
    "        _sync_dispatch_claims_to_web_from_bot(interaction.message.id, claim_data, interaction.guild)\n",
    "",
)

# 2. 移除舊的 sync_web_worker_claim_from_dispatch try 區塊，避免跟新邏輯打架
text = re.sub(
    r"\n        try:\n"
    r"            sync_web_worker_claim_from_dispatch\(\n"
    r"                dispatch_message_id=interaction\.message\.id,\n"
    r"                worker_discord_id=interaction\.user\.id,\n"
    r"                worker_display_name=getattr\(interaction\.user, \"display_name\", None\) or getattr\(interaction\.user, \"name\", None\),\n"
    r"                role_type=\"booster\",\n"
    r"                claimed=False,\n"
    r"            \)\n"
    r"        except Exception as e:\n"
    r"            print\(f\"同步 Discord 取消接單到網站失敗：\{e\}\"\)\n",
    "\n",
    text,
)

# 3. 確保接單後只新增目前這個人
claim_old = """        claim_data[claim_type].add(interaction.user.id)
        remember_claim_data(interaction.message.id, claim_data)
"""

claim_new = """        claim_data[claim_type].add(interaction.user.id)
        remember_claim_data(interaction.message.id, claim_data)
        sync_single_discord_claim_event_to_web(interaction, claim_type, "claim")
"""

if claim_new not in text:
    text = text.replace(claim_old, claim_new, 1)

# 4. 確保取消接單後只移除目前這個人
cancel_old = """        remember_claim_data(interaction.message.id, claim_data)

        await send_order_log(
"""

cancel_new = """        remember_claim_data(interaction.message.id, claim_data)
        sync_single_discord_claim_event_to_web(interaction, "booster", "unclaim")
        sync_single_discord_claim_event_to_web(interaction, "companion", "unclaim")

        await send_order_log(
"""

if cancel_new not in text:
    text = text.replace(cancel_old, cancel_new, 1)

path.write_text(text, encoding="utf-8")
print("patched claim/cancel merge logic")
