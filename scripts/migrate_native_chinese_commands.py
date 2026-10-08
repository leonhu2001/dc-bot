from __future__ import annotations

import ast
import re
import tokenize
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# These become the actual names registered with Discord. They are not localizations.
COMMAND_NAMES = {
    # top-level groups
    "order": "訂單",
    "vip": "貴賓",
    "member": "會員",
    "reward": "會員管理",
    "customer": "顧客管理",
    "stats": "營運",
    "audit": "系統",
    "setup": "設定",
    "lottery": "抽獎",
    "staff": "人員",

    # public / member commands
    "my_favorites": "我的收藏",
    "browse_staff_profiles": "瀏覽個人牆",
    "my_wallet_history": "我的錢包流水",
    "my_info": "我的會員資料",
    "points": "我的資料",

    # staff profile / repair tools
    "fix_acceptance_payment_panel": "補送付款面板",
    "staff_profile_panel": "建立個人牆面板",
    "refresh_staff_profile_panel": "更新個人牆面板",
    "reward_redeem_panel": "點數兌換面板",
    "set_customer_level": "設定會員等級",

    # order tools
    "order_search": "訂單查詢",
    "stored_orders": "存單查詢",
    "check_stored_orders": "檢查逾期存單",
    "delete_order": "刪除訂單",
    "fix_order_amount": "修正訂單金額",
    "fix_order_customer": "修正訂單顧客",
    "resend_dispatch": "重新派單",
    "delete_dispatch_panel": "刪除派單面板",

    # wallet
    "wallet_history": "錢包流水",
    "wallet_add": "錢包加值",
    "wallet_adjust": "錢包調整",
    "wallet_refund": "錢包退款",
    "wallet_refund_order": "訂單退款至錢包",

    # rewards / customer
    "customer_points": "會員資料",
    "adjust_points": "調整點數",
    "add_purchase": "補登消費",
    "import_purchases": "批量補登消費",
    "set_customer_rewards": "修正會員資料",
    "notes": "備註查詢",
    "add_note": "新增備註",
    "remove_note": "刪除備註",

    # stats / audit
    "today": "今日",
    "month": "本月",
    "top_customers": "消費排行",
    "check_vip_downgrades": "檢查會員降階",
    "data": "資料檢查",

    # setup
    "panel": "面板",
    "staff_panel": "客服管理面板",
    "topup_panel": "儲值面板",
    "complaint_panel": "客訴面板",
    "feedback_panel": "意見箱面板",
    "play_voice": "陪玩語音",
    "vip_voice": "貴賓語音",
    "public_voice": "公共語音",

    # VIP voice administration
    "hidden_add": "新增隱藏貴賓",
    "hidden_remove": "移除隱藏貴賓",
    "hidden_list": "隱藏貴賓名單",
    "create_voice": "建立貴賓語音",

    # lottery / sync
    "status": "查看狀態",
    "draw": "開獎",
    "sync_members": "同步人員",
}

STAFF_PATHS = {
    "order_search": "訂單查詢",
    "stored_orders": "存單查詢",
    "fix_order_amount": "修正訂單金額",
    "fix_order_customer": "修正訂單顧客",
    "resend_dispatch": "重新派單",
    "reward customer_points": "會員管理 會員資料",
    "reward adjust_points": "會員管理 調整點數",
    "reward add_purchase": "會員管理 補登消費",
    "customer notes": "顧客管理 備註查詢",
    "customer add_note": "顧客管理 新增備註",
    "customer remove_note": "顧客管理 刪除備註",
    "wallet_history": "錢包流水",
    "wallet_add": "錢包加值",
    "wallet_adjust": "錢包調整",
    "wallet_refund": "錢包退款",
    "stats today": "營運 今日",
    "stats month": "營運 本月",
    "stats top_customers": "營運 消費排行",
    "audit data": "系統 資料檢查",
}

HELP_REPLACEMENTS = {
    "/lottery panel": "/抽獎 面板",
    "/lottery status": "/抽獎 查看狀態",
    "/lottery draw": "/抽獎 開獎",
}


def _call_attr(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _keyword(call: ast.Call, name: str) -> ast.keyword | None:
    for item in call.keywords:
        if item.arg == name:
            return item
    return None


def _char_offset(lines: list[str], lineno: int, byte_col: int) -> int:
    prefix = "".join(lines[: lineno - 1])
    line = lines[lineno - 1]
    char_col = len(line.encode("utf-8")[:byte_col].decode("utf-8"))
    return len(prefix) + char_col


def rewrite_command_declarations(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    lines = text.splitlines(keepends=True)
    replacements: list[tuple[int, int, str]] = []
    implicit_english: list[str] = []

    for node in ast.walk(tree):
        # app_commands.Group(name="...")
        if isinstance(node, ast.Call) and _call_attr(node) == "Group":
            name_kw = _keyword(node, "name")
            if name_kw and isinstance(name_kw.value, ast.Constant) and isinstance(name_kw.value.value, str):
                old = name_kw.value.value
                new = COMMAND_NAMES.get(old)
                if new and new != old:
                    start = _char_offset(lines, name_kw.value.lineno, name_kw.value.col_offset)
                    end = _char_offset(lines, name_kw.value.end_lineno, name_kw.value.end_col_offset)
                    replacements.append((start, end, repr(new)))

        # @something.command(name="...")
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or _call_attr(decorator) != "command":
                continue
            name_kw = _keyword(decorator, "name")
            if name_kw and isinstance(name_kw.value, ast.Constant) and isinstance(name_kw.value.value, str):
                old = name_kw.value.value
                new = COMMAND_NAMES.get(old)
                if new and new != old:
                    start = _char_offset(lines, name_kw.value.lineno, name_kw.value.col_offset)
                    end = _char_offset(lines, name_kw.value.end_lineno, name_kw.value.end_col_offset)
                    replacements.append((start, end, repr(new)))
            else:
                # An implicit command name would still register the Python function
                # name. Fail loudly instead of silently leaving an English command.
                if re.search(r"[A-Za-z_]", node.name):
                    implicit_english.append(f"{path.relative_to(ROOT)}:{node.lineno} {node.name}")

    if implicit_english:
        raise RuntimeError(
            "Slash command decorators without an explicit native Chinese name:\n"
            + "\n".join(implicit_english)
        )

    for start, end, replacement in sorted(replacements, reverse=True):
        text = text[:start] + replacement + text[end:]

    if replacements:
        path.write_text(text, encoding="utf-8")
    return len(replacements)


def rewrite_exact_string_literals(path: Path, mapping: dict[str, str]) -> int:
    text = path.read_text(encoding="utf-8")
    out = []
    changed = 0
    reader = StringIO(text).readline
    for token in tokenize.generate_tokens(reader):
        if token.type == tokenize.STRING:
            try:
                value = ast.literal_eval(token.string)
            except Exception:
                value = None
            if isinstance(value, str) and value in mapping:
                token = tokenize.TokenInfo(
                    token.type,
                    repr(mapping[value]),
                    token.start,
                    token.end,
                    token.line,
                )
                changed += 1
        out.append(token)
    if changed:
        path.write_text(tokenize.untokenize(out), encoding="utf-8")
    return changed


def update_staff_panel_paths() -> int:
    changed = 0
    staff_file = ROOT / "views" / "staff_management.py"
    changed += rewrite_exact_string_literals(staff_file, STAFF_PATHS)

    # Audit command guards resolve the same commands as the Panel.
    audit_file = ROOT / "cogs" / "audit_commands.py"
    changed += rewrite_exact_string_literals(audit_file, STAFF_PATHS)
    return changed


def update_user_facing_help() -> int:
    changed = 0
    for path in (ROOT / "cogs").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        original = text
        for old, new in HELP_REPLACEMENTS.items():
            text = text.replace(old, new)
        if text != original:
            path.write_text(text, encoding="utf-8")
            changed += 1
    return changed


def replace_runtime_registry() -> None:
    # Native source names are now authoritative. Keep only the one-time remote
    # global cleanup that removes historical English global registrations.
    registry = ROOT / "core" / "command_registry.py"
    registry.write_text(
        '''from __future__ import annotations\n\nimport discord\nfrom discord import app_commands\n\n\nasync def clear_stale_remote_global_commands(tree: app_commands.CommandTree) -> None:\n    """Delete historical remote global commands without altering the local tree.\n\n    This bot publishes Slash commands to one guild. Older deployments also wrote\n    global English commands, so a guild-only sync cannot remove them. The cleanup\n    runs at startup before the guild copy/sync and restores every local command\n    object immediately after the empty global sync.\n    """\n\n    try:\n        remote_global_commands = await tree.fetch_commands()\n    except discord.HTTPException as exc:\n        print(\n            "[commands] unable to inspect stale global commands; "\n            f"guild sync will continue: {type(exc).__name__}: {exc}",\n            flush=True,\n        )\n        return\n\n    if not remote_global_commands:\n        return\n\n    local_global_commands = list(tree.get_commands())\n    tree.clear_commands(guild=None)\n\n    try:\n        await tree.sync()\n    except discord.HTTPException as exc:\n        print(\n            "[commands] unable to clear stale global commands; "\n            f"guild sync will continue: {type(exc).__name__}: {exc}",\n            flush=True,\n        )\n    else:\n        print(\n            "[commands] cleared stale global commands: "\n            f"{len(remote_global_commands)}",\n            flush=True,\n        )\n    finally:\n        for command in local_global_commands:\n            tree.add_command(command)\n''',
        encoding="utf-8",
    )

    (ROOT / "cogs" / "__init__.py").write_text("# cogs package\n", encoding="utf-8")

    bot_path = ROOT / "bot.py"
    text = bot_path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?m)^(?P<indent>[ \t]*)bot\.tree\.copy_global_to\(guild=discord\.Object\(id=GUILD_ID\)\)$"
    )

    def repl(match: re.Match[str]) -> str:
        indent = match.group("indent")
        return (
            f"{indent}from core.command_registry import clear_stale_remote_global_commands\n"
            f"{indent}await clear_stale_remote_global_commands(bot.tree)\n"
            f"{indent}bot.tree.copy_global_to(guild=discord.Object(id=GUILD_ID))"
        )

    text, count = pattern.subn(repl, text, count=1)
    if count != 1:
        raise RuntimeError("Could not locate bot.tree.copy_global_to startup sync marker")
    bot_path.write_text(text, encoding="utf-8")


def write_native_registry_tests() -> None:
    test_path = ROOT / "tests" / "test_command_registry.py"
    test_path.write_text(
        '''from __future__ import annotations\n\nimport ast\nimport asyncio\nimport re\nfrom pathlib import Path\n\nimport discord\nfrom discord import app_commands\n\nimport core.command_registry as command_registry\nfrom views.staff_management import REQUIRED_COMMAND_PATHS, resolve_command\n\n\nROOT = Path(__file__).resolve().parents[1]\nASCII_COMMAND_CHARS = re.compile(r"[A-Za-z_]")\n\n\ndef _call_attr(call: ast.Call) -> str | None:\n    func = call.func\n    if isinstance(func, ast.Attribute):\n        return func.attr\n    if isinstance(func, ast.Name):\n        return func.id\n    return None\n\n\ndef _literal_name(call: ast.Call) -> str | None:\n    for keyword in call.keywords:\n        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):\n            return keyword.value.value\n    return None\n\n\ndef _iter_registered_command_names() -> list[tuple[Path, int, str]]:\n    paths = [ROOT / "bot.py"]\n    paths.extend(sorted((ROOT / "cogs").rglob("*.py")))\n    found: list[tuple[Path, int, str]] = []\n\n    for path in paths:\n        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))\n        for node in ast.walk(tree):\n            if isinstance(node, ast.Call) and _call_attr(node) == "Group":\n                name = _literal_name(node)\n                if name is not None:\n                    found.append((path, node.lineno, name))\n\n            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):\n                continue\n            for decorator in node.decorator_list:\n                if not isinstance(decorator, ast.Call) or _call_attr(decorator) != "command":\n                    continue\n                name = _literal_name(decorator)\n                # No explicit name means Discord uses the Python function name.\n                found.append((path, decorator.lineno, name if name is not None else node.name))\n\n    return found\n\n\ndef _dummy_command(name: str) -> app_commands.Command:\n    async def callback(interaction: discord.Interaction):\n        return None\n    return app_commands.Command(name=name, description="test", callback=callback)\n\n\ndef _build_staff_panel_tree() -> tuple[discord.Client, app_commands.CommandTree]:\n    client = discord.Client(intents=discord.Intents.none())\n    tree = app_commands.CommandTree(client)\n    groups: dict[str, app_commands.Group] = {}\n\n    for path in REQUIRED_COMMAND_PATHS:\n        parts = path.split()\n        if len(parts) == 1:\n            if tree.get_command(parts[0]) is None:\n                tree.add_command(_dummy_command(parts[0]))\n            continue\n\n        group_name, command_name = parts\n        group = groups.get(group_name)\n        if group is None:\n            group = app_commands.Group(name=group_name, description="test")\n            groups[group_name] = group\n            tree.add_command(group)\n        if group.get_command(command_name) is None:\n            group.add_command(_dummy_command(command_name))\n\n    return client, tree\n\n\ndef test_every_registered_slash_command_is_natively_chinese():\n    invalid: list[str] = []\n    for path, line, name in _iter_registered_command_names():\n        if ASCII_COMMAND_CHARS.search(name):\n            invalid.append(f"{path.relative_to(ROOT)}:{line} {name!r}")\n        if not (1 <= len(name) <= 32):\n            invalid.append(f"{path.relative_to(ROOT)}:{line} invalid length {name!r}")\n    assert not invalid, "Non-Chinese native Slash command names:\\n" + "\\n".join(invalid)\n\n\ndef test_staff_management_paths_are_native_chinese_and_resolve():\n    _client, tree = _build_staff_panel_tree()\n    missing: list[str] = []\n    english: list[str] = []\n    for path in REQUIRED_COMMAND_PATHS:\n        if ASCII_COMMAND_CHARS.search(path):\n            english.append(path)\n        if resolve_command(tree, path) is None:\n            missing.append(path)\n    assert not english, "Staff management still uses English command paths: " + ", ".join(english)\n    assert not missing, "Staff management command paths do not resolve: " + ", ".join(missing)\n\n\ndef test_stale_global_cleanup_clears_remote_but_restores_local_tree(monkeypatch):\n    first = object()\n    second = object()\n\n    class FakeTree:\n        def __init__(self):\n            self.local = [first, second]\n            self.remote = [object(), object()]\n\n        async def fetch_commands(self):\n            return list(self.remote)\n\n        def get_commands(self):\n            return list(self.local)\n\n        def clear_commands(self, *, guild=None):\n            assert guild is None\n            self.local.clear()\n\n        def add_command(self, command):\n            self.local.append(command)\n\n        async def sync(self):\n            assert self.local == []\n            return []\n\n    tree = FakeTree()\n    asyncio.run(command_registry.clear_stale_remote_global_commands(tree))\n    assert tree.local == [first, second]\n''',
        encoding="utf-8",
    )


def main() -> None:
    declaration_changes = 0
    paths = [ROOT / "bot.py"]
    paths.extend(sorted((ROOT / "cogs").rglob("*.py")))
    for path in paths:
        declaration_changes += rewrite_command_declarations(path)

    if declaration_changes == 0:
        raise RuntimeError("Migration did not find any English Slash command declarations")

    path_changes = update_staff_panel_paths()
    replace_runtime_registry()
    help_files = update_user_facing_help()
    write_native_registry_tests()

    print(f"native command declarations changed: {declaration_changes}")
    print(f"staff command path literals changed: {path_changes}")
    print(f"help files changed: {help_files}")


if __name__ == "__main__":
    main()
