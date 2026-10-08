from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"expected block not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


bot = Path("bot.py")
replace_once(
    bot,
    '''            from core.command_registry import clear_stale_remote_global_commands\n            await clear_stale_remote_global_commands(bot.tree)\n            bot.tree.copy_global_to(guild=discord.Object(id=GUILD_ID))\n            bot._extensions_loaded = True\n''',
    '''            guild_command_scope = discord.Object(id=GUILD_ID)\n            bot.tree.copy_global_to(guild=guild_command_scope)\n            # This bot publishes Slash commands only to the configured guild.\n            # After copying Cog/global declarations into that guild, drop the\n            # local global tree so a later bare sync can never republish them.\n            bot.tree.clear_commands(guild=None)\n            bot._extensions_loaded = True\n''',
)

replace_once(
    bot,
    '''    try:\n        from core.command_registry import force_replace_remote_guild_commands\n        synced = await asyncio.wait_for(\n            force_replace_remote_guild_commands(bot.tree, GUILD_ID),\n            timeout=60,\n        )\n''',
    '''    try:\n        from core.command_registry import clear_stale_remote_global_commands\n        await asyncio.wait_for(\n            clear_stale_remote_global_commands(bot.tree),\n            timeout=30,\n        )\n    except asyncio.TimeoutError:\n        print(\n            "Global command cleanup timeout: Discord global cleanup exceeded 30 seconds.",\n            flush=True,\n        )\n    except Exception as e:\n        print(f"Global command cleanup error: {e}", flush=True)\n\n    try:\n        from core.command_registry import force_replace_remote_guild_commands\n        synced = await asyncio.wait_for(\n            force_replace_remote_guild_commands(bot.tree, GUILD_ID),\n            timeout=60,\n        )\n''',
)

registry = Path("core/command_registry.py")
registry_text = registry.read_text(encoding="utf-8")
start = registry_text.index("async def clear_stale_remote_global_commands")
end = registry_text.index("\n\nasync def force_replace_remote_guild_commands", start)
new_cleanup = '''async def clear_stale_remote_global_commands(tree: app_commands.CommandTree) -> None:\n    \"\"\"Publish and verify an empty global command set.\n\n    The production bot is guild-only. Its local global tree must already be empty\n    after startup copies Cog declarations into the configured guild. This function\n    bulk-overwrites Discord's global commands with an empty set and then reads the\n    remote state back. A small retry covers transient Discord API/cache lag.\n    \"\"\"\n\n    # Idempotently enforce the invariant locally as well. Do not restore these\n    # objects: keeping them around is what made accidental global republishing\n    # possible in earlier revisions.\n    tree.clear_commands(guild=None)\n\n    last_error: Exception | None = None\n    remaining_names: list[str] = []\n\n    for attempt in range(1, 4):\n        try:\n            await tree.sync()\n            remote_global_commands = await tree.fetch_commands()\n        except discord.HTTPException as exc:\n            last_error = exc\n            remote_global_commands = []\n        else:\n            remaining_names = [command.name for command in remote_global_commands]\n            if not remaining_names:\n                print(\n                    f\"[commands] verified remote global commands empty on attempt {attempt}\",\n                    flush=True,\n                )\n                return\n\n        if attempt < 3:\n            await asyncio.sleep(1)\n\n    if last_error is not None and not remaining_names:\n        raise RuntimeError(\n            \"Discord global Slash command cleanup could not be verified\"\n        ) from last_error\n\n    raise RuntimeError(\n        \"Discord global Slash commands still exist after cleanup: \"\n        + \", \".join(sorted(remaining_names))\n    )\n'''
registry_text = registry_text[:start] + new_cleanup + registry_text[end:]
if "import asyncio\n" not in registry_text:
    registry_text = registry_text.replace("from __future__ import annotations\n\n", "from __future__ import annotations\n\nimport asyncio\n\n", 1)
registry.write_text(registry_text, encoding="utf-8")

test_path = Path("tests/test_command_registry.py")
test_text = test_path.read_text(encoding="utf-8")n