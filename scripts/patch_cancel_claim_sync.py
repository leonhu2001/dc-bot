from pathlib import Path

path = Path("bot.py")
text = path.read_text(encoding="utf-8")

start = text.find("    async def cancel_claim")
if start == -1:
    raise RuntimeError("找不到 async def cancel_claim")

next_method = text.find("\n    async def ", start + 1)
next_button = text.find("\n    @discord.ui.button", start + 1)

candidates = [pos for pos in [next_method, next_button] if pos != -1]
end = min(candidates) if candidates else len(text)

block = text[start:end]

insert = '''        sync_single_discord_claim_event_to_web(interaction, "booster", "unclaim")
        sync_single_discord_claim_event_to_web(interaction, "companion", "unclaim")
'''

if insert in block:
    print("cancel_claim already patched")
else:
    target = "        remember_claim_data(interaction.message.id, claim_data)\n"
    idx = block.find(target)

    if idx == -1:
        raise RuntimeError("cancel_claim 找不到 remember_claim_data")

    insert_at = start + idx + len(target)
    text = text[:insert_at] + insert + text[insert_at:]
    path.write_text(text, encoding="utf-8")
    print("patched cancel_claim unclaim sync")
