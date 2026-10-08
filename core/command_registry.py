from __future__ import annotations

import asyncio

import discord
from discord import app_commands


async def clear_stale_remote_global_commands(tree: app_commands.CommandTree) -> None:
    """Publish and verify an empty global command set.

    The production bot is guild-only. Its local global tree must already be empty
    after startup copies Cog declarations into the configured guild. This function
    bulk-overwrites Discord's global commands with an empty set and then reads the
    remote state back. A small retry covers transient Discord API/cache lag.
    """

    # Idempotently enforce the invariant locally as well. Do not restore these
    # objects: keeping them around is what made accidental global republishing
    # possible in earlier revisions.
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
    """Replace the remote guild command set from a clean slate and verify it.

    A normal guild sync should already be a bulk overwrite, but historical command
    migrations left stale English commands visible in Discord. This helper makes
    the cleanup explicit: snapshot the desired local guild tree, publish an empty
    guild command set, restore the local tree, publish the desired set, then fetch
    Discord's remote state and verify the top-level command names exactly match.

    The local command objects are restored in a finally block, so a failed empty
    sync cannot erase the bot's in-memory command tree.
    """

    guild = discord.Object(id=int(guild_id))
    desired_commands = list(tree.get_commands(guild=guild))
    expected_names = sorted(command.name for command in desired_commands)

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
