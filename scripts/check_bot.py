#!/usr/bin/env python3
from __future__ import annotations

import argparse
import py_compile
import sqlite3
from pathlib import Path

DEFAULT_EXPECTED_COMMANDS = 37
COMMAND_PATTERNS = ("@bot.tree.command", "@app_commands.command")
EXCLUDE_DIRS = {"venv", ".venv", "__pycache__", ".git", "backups"}
SYNTAX_DIRS = ("core", "services", "views", "cogs", "scripts")
COMMAND_DIRS = ("core", "services", "views", "cogs")
REQUIRED_TABLES = {"orders", "claims", "customers", "order_counters"}


def project_root() -> Path:
    this_file = Path(__file__).resolve()
    if this_file.parent.name == "scripts":
        return this_file.parent.parent
    return Path.cwd().resolve()


def iter_python_files(root: Path, include_scripts: bool = True) -> list[Path]:
    files: list[Path] = []

    bot_file = root / "bot.py"
    if bot_file.exists():
        files.append(bot_file)

    dirs = SYNTAX_DIRS if include_scripts else COMMAND_DIRS

    for dirname in dirs:
        folder = root / dirname
        if not folder.exists():
            continue

        for path in folder.rglob("*.py"):
            if any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            files.append(path)

    unique_files = []
    seen = set()

    for path in files:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_files.append(path)

    return unique_files


def check_syntax(root: Path) -> bool:
    print("Checking Python syntax...")
    ok = True

    files = iter_python_files(root, include_scripts=True)

    if not files:
        print("ERROR: 找不到任何 Python 檔案。")
        return False

    for path in files:
        rel = path.relative_to(root)
        try:
            py_compile.compile(str(path), doraise=True)
            print(f"OK syntax: {rel}")
        except py_compile.PyCompileError as exc:
            print(f"ERROR syntax: {rel}")
            print(exc)
            ok = False

    return ok


def count_command_decorators(root: Path) -> int:
    count = 0

    files = iter_python_files(root, include_scripts=False)

    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="ignore")

        for pattern in COMMAND_PATTERNS:
            count += text.count(pattern)

    return count


def check_database(root: Path) -> bool:
    db_path = root / "bot.db"

    if not db_path.exists():
        print("bot.db not found, skip database table check.")
        return True

    print("Checking SQLite database tables...")

    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
    except sqlite3.Error as exc:
        print(f"ERROR: bot.db 讀取失敗：{exc}")
        return False

    existing_tables = {row[0] for row in rows}
    missing_tables = REQUIRED_TABLES - existing_tables

    if missing_tables:
        print(f"ERROR: bot.db 缺少資料表：{', '.join(sorted(missing_tables))}")
        return False

    print("OK database tables exist.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--expected-commands",
        type=int,
        default=DEFAULT_EXPECTED_COMMANDS,
    )
    args = parser.parse_args()

    root = project_root()
    print(f"Project root: {root}")

    ok = True

    if not check_syntax(root):
        ok = False

    command_count = count_command_decorators(root)
    print(f"Slash/app command decorators: {command_count}")
    print(f"Expected command decorators: {args.expected_commands}")

    if command_count != args.expected_commands:
        print("ERROR 指令數量不正確，請先不要 commit / push。")
        ok = False
    else:
        print("OK 指令數量正確。")

    if not check_database(root):
        ok = False

    if ok:
        print("CHECK PASSED")
        return 0

    print("CHECK FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
