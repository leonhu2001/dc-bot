from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "web" / "app" / "main.py"

IMPORT_LINE = "from web.app.routers.admin_payout_summary import router as admin_payout_summary_router"
INCLUDE_LINE = "app.include_router(admin_payout_summary_router)"


def main() -> None:
    text = MAIN_PATH.read_text(encoding="utf-8")

    if IMPORT_LINE not in text:
        marker = "from web.app.routers.admin_payouts import router as admin_payouts_router"
        if marker in text:
            text = text.replace(marker, marker + "\n" + IMPORT_LINE)
        else:
            marker = "from web.app.routers.admin import router as admin_router"
            text = text.replace(marker, marker + "\n" + IMPORT_LINE)

    if INCLUDE_LINE not in text:
        marker = "app.include_router(admin_payouts_router)"
        if marker in text:
            text = text.replace(marker, marker + "\n" + INCLUDE_LINE)
        else:
            marker = "app.include_router(admin_router)"
            text = text.replace(marker, marker + "\n" + INCLUDE_LINE)

    MAIN_PATH.write_text(text, encoding="utf-8")
    print("installed admin payout summary page")


if __name__ == "__main__":
    main()
