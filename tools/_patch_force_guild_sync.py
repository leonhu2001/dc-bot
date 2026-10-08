from pathlib import Path

path = Path('bot.py')
text = path.read_text(encoding='utf-8')
old = '''    try:\n        guild = discord.Object(id=GUILD_ID)\n        synced = await asyncio.wait_for(\n            bot.tree.sync(guild=guild),\n            timeout=30,\n        )\n        print(f"Slash commands synced: {len(synced)}", flush=True)\n'''
new = '''    try:\n        from core.command_registry import force_replace_remote_guild_commands\n        synced = await asyncio.wait_for(\n            force_replace_remote_guild_commands(bot.tree, GUILD_ID),\n            timeout=60,\n        )\n        print(f"Slash commands synced and verified: {len(synced)}", flush=True)\n'''
if old not in text:
    raise SystemExit('target sync block not found')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')
