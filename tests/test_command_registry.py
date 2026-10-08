from __future__ import annotations

import ast
import re
from pathlib import Path

import discord
from discord import app_commands

from core.command_registry import (
    canonical_command_name,
    canonicalize_tree,
    install_canonical_command_registry,
)


ROOT = Path(__file__).resolve().parents[1]
ASCII_COMMAND_CHARS = re.compile(r"[A-Za-z_]")


def _iter_literal_app_command_names() -> list[tuple[Path, int, str]]:
    paths = [ROOT / "bot.py"]
    paths.extend(sorted((ROOT / "cogs").rglob("*.py")))

    found: list[tuple[Path, int, str]] = []

    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call):
                        continue
                    if not isinstance(decorator.func, ast.Attribute):
                        continue
                    if decorator.func.attr != "command":
                        continue

                    for keyword in decorator.keywords:
                        if keyword.arg != "name":
                            continue
                        if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                            found.append((path, decorator.lineno, keyword.value.value))

            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "Group":
                continue

            for keyword in node.keywords:
                if keyword.arg != "name":
                    continue
                if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    found.append((path, node.lineno, keyword.value.value))

    return found


def test_every_literal_slash_command_has_a_chinese_canonical_name():
    missing: list[str] = []

    for path, line, source_name in _iter_literal_app_command_names():
        canonical = canonical_command_name(source_name)
        if ASCII_COMMAND_CHARS.search(canonical):
            missing.append(f"{path.relative_to(ROOT)}:{line} {source_name!r} -> {canonical!r}")
        if not (1 <= len(canonical) <= 32):
            missing.append(f"{path.relative_to(ROOT)}:{line} invalid length {canonical!r}")

    assert not missing, "Untranslated canonical Slash command names:\n" + "\n".join(missing)


def test_command_tree_uses_chinese_names_and_keeps_legacy_panel_lookups():
    install_canonical_command_registry()

    client = discord.Client(intents=discord.Intents.none())
    tree = app_commands.CommandTree(client)

    @app_commands.command(name="order_search", description="search")
    async def order_search(interaction: discord.Interaction):
        pass

    reward = app_commands.Group(name="reward", description="reward")

    @reward.command(name="adjust_points", description="adjust")
    async def adjust_points(interaction: discord.Interaction, points: int):
        pass

    tree.add_command(order_search)
    tree.add_command(reward)

    canonicalize_tree(tree)

    assert tree.get_command("訂單查詢") is order_search
    assert tree.get_command("order_search") is order_search
    assert order_search.name == "訂單查詢"

    reward_group = tree.get_command("會員管理")
    assert reward_group is reward
    assert tree.get_command("reward") is reward
    assert reward.name == "會員管理"

    child = reward.get_command("調整點數")
    assert child is not None
    assert reward.get_command("adjust_points") is child
    assert child.name == "調整點數"


def test_guild_copy_is_canonicalized_without_breaking_legacy_lookup():
    install_canonical_command_registry()

    client = discord.Client(intents=discord.Intents.none())
    tree = app_commands.CommandTree(client)

    @app_commands.command(name="stored_orders", description="stored")
    async def stored_orders(interaction: discord.Interaction):
        pass

    tree.add_command(stored_orders)
    guild = discord.Object(id=1129474191226306672)
    tree.copy_global_to(guild=guild)

    canonicalize_tree(tree, guild=guild)

    canonical = tree.get_command("存單查詢", guild=guild)
    legacy = tree.get_command("stored_orders", guild=guild)
    assert canonical is not None
    assert legacy is canonical
    assert canonical.name == "存單查詢"
