from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BOT_FILE = PROJECT_ROOT / "bot.py"
BACKUP_FILE = PROJECT_ROOT / "bot.py.bak.staff_sync"
EXTENSION_LINE = '                "cogs.staff_sync",\n'
ANCHOR_LINE = '                "cogs.audit_commands",\n'


def main() -> None:
    if not BOT_FILE.exists():
        raise FileNotFoundError(f"找不到 {BOT_FILE}")

    text = BOT_FILE.read_text(encoding="utf-8")

    if '"cogs.staff_sync"' in text or "'cogs.staff_sync'" in text:
        print("bot.py already includes cogs.staff_sync")
        return

    if ANCHOR_LINE not in text:
        raise RuntimeError("找不到 cogs.audit_commands 位置，沒有修改 bot.py")

    if not BACKUP_FILE.exists():
        BACKUP_FILE.write_text(text, encoding="utf-8")
        print(f"backup created: {BACKUP_FILE}")

    text = text.replace(ANCHOR_LINE, ANCHOR_LINE + EXTENSION_LINE, 1)
    BOT_FILE.write_text(text, encoding="utf-8")
    print("bot.py updated: added cogs.staff_sync")


if __name__ == "__main__":
    main()
