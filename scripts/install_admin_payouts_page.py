from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "web" / "app" / "main.py"
CSS_PATH = ROOT / "web" / "app" / "static" / "css" / "app.css"

IMPORT_LINE = "from web.app.routers.admin_payouts import router as admin_payouts_router"
INCLUDE_LINE = "app.include_router(admin_payouts_router)"

CSS_APPEND = r'''

/* Compact payout pages */
.compact-panel {
    padding: 14px;
    margin-bottom: 12px;
}

.compact-grid {
    gap: 10px;
    margin-bottom: 12px;
}

.compact-number {
    font-size: 26px;
    margin: 4px 0;
}

.page-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}

.payout-table-wrap {
    overflow-x: auto;
}

.payout-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
}

.payout-table th,
.payout-table td {
    border-bottom: 1px solid #374151;
    padding: 10px 8px;
    text-align: left;
    white-space: nowrap;
}

.payout-table th {
    color: #93c5fd;
    font-size: 13px;
}

.small-button {
    padding: 8px 10px;
    border-radius: 9px;
    font-size: 13px;
}
'''


def patch_main() -> None:
    text = MAIN_PATH.read_text(encoding="utf-8")

    if IMPORT_LINE not in text:
        marker = "from web.app.routers.admin import router as admin_router\n"
        if marker not in text:
            raise RuntimeError("找不到 admin_router import，請手動檢查 main.py。")
        text = text.replace(marker, marker + IMPORT_LINE + "\n")

    if INCLUDE_LINE not in text:
        marker = "app.include_router(admin_router)\n"
        if marker not in text:
            raise RuntimeError("找不到 app.include_router(admin_router)，請手動檢查 main.py。")
        text = text.replace(marker, marker + INCLUDE_LINE + "\n")

    MAIN_PATH.write_text(text, encoding="utf-8")


def patch_css() -> None:
    text = CSS_PATH.read_text(encoding="utf-8")

    if "/* Compact payout pages */" not in text:
        text = text.rstrip() + CSS_APPEND + "\n"

    CSS_PATH.write_text(text, encoding="utf-8")


def main() -> None:
    patch_main()
    patch_css()
    print("installed admin payouts page")


if __name__ == "__main__":
    main()
