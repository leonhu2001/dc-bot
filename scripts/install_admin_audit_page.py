from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "web" / "app" / "main.py"
CSS_PATH = ROOT / "web" / "app" / "static" / "css" / "app.css"

IMPORT_LINE = "from web.app.routers.admin_audit import router as admin_audit_router"
INCLUDE_LINE = "app.include_router(admin_audit_router)"

CSS_BLOCK = r'''

/* Admin audit log page */
.audit-details {
    margin-top: 12px;
    border-top: 1px solid #374151;
    padding-top: 12px;
}

.audit-details summary {
    cursor: pointer;
    color: #93c5fd;
    font-weight: 800;
}

.audit-json-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    margin-top: 12px;
}

.audit-json-grid pre {
    margin: 0;
    max-height: 240px;
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-word;
    padding: 12px;
    border-radius: 12px;
    background: #020617;
    border: 1px solid #374151;
    color: #d1d5db;
    font-size: 12px;
}

@media (max-width: 840px) {
    .audit-json-grid {
        grid-template-columns: 1fr;
    }
}
'''


def patch_main() -> None:
    text = MAIN_PATH.read_text(encoding="utf-8")

    if IMPORT_LINE not in text:
        marker = "from web.app.routers.admin import router as admin_router\n"
        if marker in text:
            text = text.replace(marker, marker + IMPORT_LINE + "\n")
        else:
            raise RuntimeError("找不到 admin_router import 位置。")

    if INCLUDE_LINE not in text:
        marker = "app.include_router(admin_router)\n"
        if marker in text:
            text = text.replace(marker, marker + INCLUDE_LINE + "\n")
        else:
            raise RuntimeError("找不到 admin_router include 位置。")

    MAIN_PATH.write_text(text, encoding="utf-8")
    print("patched main.py admin audit route")


def patch_css() -> None:
    text = CSS_PATH.read_text(encoding="utf-8") if CSS_PATH.exists() else ""

    if "/* Admin audit log page */" not in text:
        text += CSS_BLOCK
        CSS_PATH.write_text(text, encoding="utf-8")
        print("patched app.css audit styles")
    else:
        print("app.css audit styles already exists")


def main() -> None:
    patch_main()
    patch_css()


if __name__ == "__main__":
    main()
