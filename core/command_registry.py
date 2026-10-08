from __future__ import annotations

import asyncio

import discord
from discord import app_commands


def move_global_commands_to_guild(
    tree: app_commands.CommandTree,
    guild_id: int,
) -> int:
    """Merge global declarations into one guild without replacing guild commands.

    ``CommandTree.copy_global_to`` replaces the guild command mapping with a copy
    of the global mapping. That is unsafe for this bot because many commands are
    declared directly against the production guild in ``bot.py``. Instead, add
    each global top-level command to the guild individually, preserving unrelated
    guild-only commands, then remove the local global tree so it cannot be synced.
    """

    guild = discord.Object(id=int(guild_id))
    global_commands = list(tree.get_commands())

    for command in global_commands:
        tree.add_command(command, guild=guild, override=True)

    tree.clear_commands(guild=None)
    return len(global_commands)


async def clear_stale_remote_global_commands(tree: app_commands.CommandTree) -> None:
    """Publish and verify an empty global command set.

    The production bot is guild-only. Its local global tree must already be empty
    after startup moves Cog declarations into the configured guild. This function
    bulk-overwrites Discord's global commands with an empty set and then reads the
    remote state back. A small retry covers transient Discord API/cache lag.
    """

    tree.clear_commands(guild=None)

    last_error: Exception | None = None
    remaining_names: list[str] = []

    for attempt in range(1, 4):
        try:
            await tree.sync()
            remote_global_commands = await tree.fetch_commands()
        except discord.HTTPException as exc:
            last_error = exc
            remote_global_commands = []
        else:
            remaining_names = [command.name for command in remote_global_commands]
            if not remaining_names:
                print(
                    f"[commands] verified remote global commands empty on attempt {attempt}",
                    flush=True,
                )
                return

        if attempt < 3:
            await asyncio.sleep(1)

    if last_error is not None and not remaining_names:
        raise RuntimeError(
            "Discord global Slash command cleanup could not be verified"
        ) from last_error

    raise RuntimeError(
        "Discord global Slash commands still exist after cleanup: "
        + ", ".join(sorted(remaining_names))
    )


async def force_replace_remote_guild_commands(
    tree: app_commands.CommandTree,
    guild_id: int,
) -> list[app_commands.AppCommand]:
    """Replace the remote guild command set from a clean slate and verify it."""

    guild = discord.Object(id=int(guild_id))
    desired_commands = list(tree.get_commands(guild=guild))
    expected_names = sorted(command.name for command in desired_commands)

    if not desired_commands:
        raise RuntimeError("Refusing to publish an empty guild Slash command set")

    tree.clear_commands(guild=guild)
    try:
        try:
            await tree.sync(guild=guild)
        except discord.HTTPException as exc:
            print(
                "[commands] empty guild overwrite failed; "
                f"continuing with desired sync: {type(exc).__name__}: {exc}",
                flush=True,
            )
    finally:
        for command in desired_commands:
            tree.add_command(command, guild=guild, override=True)

    synced = await tree.sync(guild=guild)
    remote_commands = await tree.fetch_commands(guild=guild)
    actual_names = sorted(command.name for command in remote_commands)

    if actual_names != expected_names:
        missing = sorted(set(expected_names) - set(actual_names))
        unexpected = sorted(set(actual_names) - set(expected_names))
        raise RuntimeError(
            "Discord guild Slash command verification failed; "
            f"missing={missing}, unexpected={unexpected}"
        )

    print(
        "[commands] verified guild commands after clean replace: "
        f"{len(actual_names)}",
        flush=True,
    )
    return synced
