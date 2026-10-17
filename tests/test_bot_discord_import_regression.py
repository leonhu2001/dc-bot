from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOT_PATH = ROOT / "bot.py"


def test_bot_imports_discord_module_before_using_discord_namespace():
    tree = ast.parse(BOT_PATH.read_text(encoding="utf-8"))
    imported_discord = any(
        isinstance(node, ast.Import)
        and any(alias.name == "discord" for alias in node.names)
        for node in tree.body
    )
    assert imported_discord, "bot.py uses discord.* and must import the discord module"
