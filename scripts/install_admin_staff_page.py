from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "web" / "app" / "main.py"
LAYOUT_PATH = ROOT / "web" / "app" / "templates" / "layout.html"


def patch_main() -> None:
    text = MAIN_PATH.read_text(encoding="utf-8")

    import_line = "from web.app.routers.admin_staff import router as admin_staff_router\n"
    if import_line not in text:
        marker = "from web.app.routers.admin import router as admin_router\n"
        if marker not in text:
            raise RuntimeError("找不到 admin_router import，無法安裝人員名單頁。")
        text = text.replace(marker, marker + import_line)

    include_line = "app.include_router(admin_staff_router)\n"
    if include_line not in text:
        marker = "app.include_router(admin_router)\n"
        if marker not in text:
            raise RuntimeError("找不到 admin_router include，無法安裝人員名單頁。")
        text = text.replace(marker, marker + include_line)

    MAIN_PATH.write_text(text, encoding="utf-8")
    print("patched web/app/main.py")


def patch_layout() -> None:
    if not LAYOUT_PATH.exists():
        print("layout.html not found, skipped")
        return

    text = LAYOUT_PATH.read_text(encoding="utf-8")
    if "/admin/staff" in text:
        print("layout already has staff link")
        return

    candidates = [
        '<a class="nav-link" href="/admin/audit">操作紀錄</a>',
        '<a class="nav-link" href="/admin/payouts/summary">人員總表</a>',
        '<a class="nav-link" href="/admin/payouts">分潤明細</a>',
        '<a class="nav-link" href="/admin">總控</a>',
    ]

    for marker in candidates:
        if marker in text:
            text = text.replace(marker, marker + '\n                    <a class="nav-link" href="/admin/staff">人員名單</a>', 1)
            LAYOUT_PATH.write_text(text, encoding="utf-8")
            print("patched layout.html")
            return

    print("找不到導覽列插入點，main.py 已安裝路由，但導覽列未新增。")


def main() -> None:
    patch_main()
    patch_layout()


if __name__ == "__main__":
    main()
