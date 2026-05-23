from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "web" / "app" / "main.py"

IMPORT_LINE = "from web.app.routers import admin_payouts_grouped"
INCLUDE_LINE = "app.include_router(admin_payouts_grouped.router)"


def main() -> None:
    text = MAIN_PATH.read_text(encoding="utf-8")

    if IMPORT_LINE not in text:
        marker = "from web.app.routers"
        lines = text.splitlines()
        insert_at = 0

        for index, line in enumerate(lines):
            if line.startswith(marker):
                insert_at = index + 1

        lines.insert(insert_at, IMPORT_LINE)
        text = "\n".join(lines) + "\n"

    if INCLUDE_LINE not in text:
        lines = text.splitlines()
        insert_at = len(lines)

        for index, line in enumerate(lines):
            if "include_router" in line:
                insert_at = index + 1

        lines.insert(insert_at, INCLUDE_LINE)
        text = "\n".join(lines) + "\n"

    MAIN_PATH.write_text(text, encoding="utf-8")
    print("installed grouped payouts page")


if __name__ == "__main__":
    main()
