from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import discord
from discord import app_commands

import core.command_registry as command_registry
from views.staff_management import REQUIRED_COMMAND_PATHS, resolve_command


ROOT = Path(__file__).resolve().parents[1]
ASCII_COMMAND_CHARS = re.compile(r"[A-Za-z_]")


def _call_attr(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _literal_name(call: ast.Call) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
            return keyword.value.value
    return None


def _command_source_paths() -> list[Path]:
    paths = [ROOT / "bot.py"]
    paths.extend(sorted((ROOT / "cogs").rglob("*.py")))
    return paths


def _iter_registered_command_names() -> list[tuple[Path, int, str]]:
    found: list[tuple[Path, int, str]] = []

    for path in _command_source_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_attr(node) == "Group":
                name = _literal_name(node)
                if name is not None:
                    found.append((path, node.lineno, name))

            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or _call_attr(decorator) != "command":
                    continue
                name = _literal_name(decorator)
                found.append((path, decorator.lineno, name if name is not None else node.name))

    return found


def _registered_command_paths() -> set[str]:
    registered: set[str] = set()

    for path in _command_source_paths():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        group_names: dict[str, str] = {}

        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue

            value = node.value
            if not isinstance(value, ast.Call) or _call_attr(value) != "Group":
                continue

            group_name = _literal_name(value)
            if group_name is None:
                continue

            targets: list[ast.expr]
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            else:
                targets = [node.target]

            for target in targets:
                if isinstance(target, ast.Name):
                    group_names[target.id] = group_name

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or _call_attr(decorator) != "command":
                    continue

                command_name = _literal_name(decorator) or node.name
                func = decorator.func
                parent_name = None
                if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                    parent_name = func.value.id

                group_name = group_names.get(parent_name or "")
                if group_name:
                    registered.add(f"{group_name} {command_name}")
                else:
                    registered.add(command_name)

    return registered


def _dummy_command(name: str) -> app_commands.Command:
    async def callback(interaction: discord.Interaction):
        return None

    return app_commands.Command(name=name, description="test", callback=callback)


def _build_staff_panel_tree() -> tuple[discord.Client, app_commands.CommandTree]:
    client = discord.Client(intents=discord.Intents.none())
    tree = app_commands.CommandTree(client)
    groups: dict[str, app_commands.Group] = {}

    for path in REQUIRED_COMMAND_PATHS:
        parts = path.split()
        if len(parts) == 1:
            if tree.get_command(parts[0]) is None:
                tree.add_command(_dummy_command(parts[0]))
            continue

        group_name, command_name = parts
        group = groups.get(group_name)
        if group is None:
            group = app_commands.Group(name=group_name, description="test")
            groups[group_name] = group
            tree.add_command(group)
        if group.get_command(command_name) is None:
            group.add_command(_dummy_command(command_name))

    return client, tree


def test_every_registered_slash_command_is_natively_chinese():
    invalid: list[str] = []
    for path, line, name in _iter_registered_command_names():
        if ASCII_COMMAND_CHARS.search(name):
            invalid.append(f"{path.relative_to(ROOT)}:{line} {name!r}")
        if not (1 <= len(name) <= 32):
            invalid.append(f"{path.relative_to(ROOT)}:{line} invalid length {name!r}")
    assert not invalid, "Non-Chinese native Slash command names:\n" + "\n".join(invalid)


def test_staff_management_paths_match_real_registered_commands():
    registered = _registered_command_paths()
    missing = [path for path in REQUIRED_COMMAND_PATHS if path not in registered]
    assert not missing, "Staff management Panel paths missing from real command declarations: " + ", ".join(missing)


def test_staff_management_paths_are_native_chinese_and_resolve():
    _client, tree = _build_staff_panel_tree()
    missing: list[str] = []
    english: list[str] = []
    for path in REQUIRED_COMMAND_PATHS:
        if ASCII_COMMAND_CHARS.search(path):
            english.append(path)
        if resolve_command(tree, path) is None:
            missing.append(path)
    assert not english, "Staff management still uses English command paths: " + ", ".join(english)
    assert not missing, "Staff management command paths do not resolve: " + ", ".join(missing)


def test_stale_global_cleanup_keeps_local_tree_empty_and_verifies_remote():
    class FakeTree:
        def __init__(self):
            self.local = [SimpleNamespace(name="抽獎")]
            self.remote = [SimpleNamespace(name="lottery")]
            self.sync_snapshots: list[list[str]] = []

        def clear_commands(self, *, guild=None):
            assert guild is None
            self.local.clear()

        async def sync(self):
            self.sync_snapshots.append([item.name for item in self.local])
            self.remote = [SimpleNamespace(name=item.name) for item in self.local]
            return list(self.remote)

        async def fetch_commands(self):
            return list(self.remote)

    tree = FakeTree()
    asyncio.run(command_registry.clear_stale_remote_global_commands(tree))

    assert tree.sync_snapshots == [[]]
    assert tree.local == []
    assert tree.remote == []


def test_bot_copies_global_declarations_to_guild_then_drops_global_tree():
    source = (ROOT / "bot.py").read_text(encoding="utf-8")
    copy_at = source.index("bot.tree.copy_global_to(guild=guild_command_scope)")
    clear_at = source.index("bot.tree.clear_commands(guild=None)", copy_at)
    cleanup_at = source.index("clear_stale_remote_global_commands(bot.tree)", clear_at)
    guild_sync_at = source.index("force_replace_remote_guild_commands(bot.tree, GUILD_ID)", cleanup_at)

    assert copy_at < clear_at < cleanup_at < guild_sync_at


def test_force_replace_guild_commands_clears_stale_remote_and_verifies():
    desired = [SimpleNamespace(name="抽獎"), SimpleNamespace(name="訂單查詢")]

    class FakeTree:
        def __init__(self):
            self.local = list(desired)
            self.remote = [SimpleNamespace(name="lottery"), SimpleNamespace(name="delete_order")]
            self.sync_snapshots: list[list[str]] = []

        def get_commands(self, *, guild=None):
            assert guild is not None
            return list(self.local)

        def clear_commands(self, *, guild=None):
            assert guild is not None
            self.local.clear()

        def add_command(self, command, *, guild=None, override=False):
            assert guild is not None
            assert override is True
            self.local.append(command)

        async def sync(self, *, guild=None):
            assert guild is not None
            self.remote = [SimpleNamespace(name=item.name) for item in self.local]
            self.sync_snapshots.append([item.name for item in self.local])
            return list(self.remote)

        async def fetch_commands(self, *, guild=None):
            assert guild is not None
            return list(self.remote)

    tree = FakeTree()
    synced = asyncio.run(command_registry.force_replace_remote_guild_commands(tree, 123))

    assert tree.sync_snapshots == [[], ["抽獎", "訂單查詢"]]
    assert [item.name for item in tree.local] == ["抽獎", "訂單查詢"]
    assert [item.name for item in tree.remote] == ["抽獎", "訂單查詢"]
    assert [item.name for item in synced] == ["抽獎", "訂單查詢"]
