from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = PROJECT_ROOT / "web" / "app" / "main.py"

IMPORT_LINE = "from web.app.routers.order_history import router as order_history_router"
INCLUDE_LINE = "app.include_router(order_history_router)"


def main() -> None:
    text = MAIN_PATH.read_text(encoding="utf-8")

    if IMPORT_LINE not in text:
        anchor = "from web.app.routers.payouts import router as payouts_router"
        if anchor in text:
            text = text.replace(anchor, anchor + "\n" + IMPORT_LINE)
        else:
            text = text.replace(
                "from web.app.routers.dispatch import router as dispatch_router",
                "from web.app.routers.dispatch import router as dispatch_router\n" + IMPORT_LINE,
            )

    if INCLUDE_LINE not in text:
        anchor = "app.include_router(payouts_router)"
        if anchor in text:
            text = text.replace(anchor, anchor + "\n" + INCLUDE_LINE)
        else:
            text = text.replace(
                "app.include_router(dispatch_router)",
                "app.include_router(dispatch_router)\n" + INCLUDE_LINE,
            )

    MAIN_PATH.write_text(text, encoding="utf-8")
    print("installed order history page")


if __name__ == "__main__":
    main()
