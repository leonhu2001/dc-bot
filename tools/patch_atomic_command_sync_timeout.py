from pathlib import Path

path = Path("bot.py")
source = path.read_text(encoding="utf-8")

old = '''        synced = await asyncio.wait_for(\n            force_replace_remote_guild_commands(bot.tree, GUILD_ID),\n            timeout=60,\n        )\n        print(f"Slash commands synced and verified: {len(synced)}", flush=True)\n    except asyncio.TimeoutError:\n        print(\n            "Sync timeout: Discord command sync exceeded 30 seconds; "\n            "persistent views remain available.",\n            flush=True,\n        )\n'''

new = '''        synced = await asyncio.wait_for(\n            force_replace_remote_guild_commands(bot.tree, GUILD_ID),\n            timeout=180,\n        )\n        print(f"Slash commands synced and verified: {len(synced)}", flush=True)\n    except asyncio.TimeoutError:\n        print(\n            "Sync timeout: Discord guild command publish exceeded 180 seconds; "\n            "the remote guild command set was not pre-cleared.",\n            flush=True,\n        )\n'''

if old not in source:
    raise SystemExit("target sync timeout block not found")

path.write_text(source.replace(old, new, 1), encoding="utf-8")
