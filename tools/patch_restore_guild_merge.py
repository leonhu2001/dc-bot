from pathlib import Path

path = Path("bot.py")
text = path.read_text(encoding="utf-8")
old = '''            guild_command_scope = discord.Object(id=GUILD_ID)\n            bot.tree.copy_global_to(guild=guild_command_scope)\n            # This bot publishes Slash commands only to the configured guild.\n            # After copying Cog/global declarations into that guild, drop the\n            # local global tree so a later bare sync can never republish them.\n            bot.tree.clear_commands(guild=None)\n            bot._extensions_loaded = True\n'''
new = '''            from core.command_registry import move_global_commands_to_guild\n            moved_global_commands = move_global_commands_to_guild(bot.tree, GUILD_ID)\n            print(\n                f"[commands] moved global declarations into guild without replacing existing commands: {moved_global_commands}",\n                flush=True,\n            )\n            bot._extensions_loaded = True\n'''

if old not in text:
    raise SystemExit("expected copy_global_to startup block not found")

text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
