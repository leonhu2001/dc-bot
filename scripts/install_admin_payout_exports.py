from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN_PATH = ROOT / "web" / "app" / "main.py"
TEMPLATE_PATH = ROOT / "web" / "app" / "templates" / "admin_payouts.html"


def patch_main() -> None:
    text = MAIN_PATH.read_text(encoding="utf-8")

    import_line = "from web.app.routers.admin_payout_exports import router as admin_payout_exports_router\n"
    include_line = "app.include_router(admin_payout_exports_router)\n"

    if import_line not in text:
        marker = "from web.app.routers.admin_payouts import router as admin_payouts_router\n"
        if marker in text:
            text = text.replace(marker, marker + import_line)
        else:
            text = text.replace("from web.app.routers.admin import router as admin_router\n", "from web.app.routers.admin import router as admin_router\n" + import_line)

    if include_line not in text:
        marker = "app.include_router(admin_payouts_router)\n"
        if marker in text:
            text = text.replace(marker, marker + include_line)
        else:
            text = text.replace("app.include_router(admin_router)\n", "app.include_router(admin_router)\n" + include_line)

    MAIN_PATH.write_text(text, encoding="utf-8")
    print("patched web/app/main.py")


def patch_template() -> None:
    if not TEMPLATE_PATH.exists():
        print("admin_payouts.html not found, skipped template patch")
        return

    text = TEMPLATE_PATH.read_text(encoding="utf-8")

    if "/admin/payouts/export.csv" in text:
        print("admin_payouts.html already has export link")
        return

    export_block = '''
    <div class="panel compact-panel">
        <h2>匯出分潤 CSV</h2>
        <p class="muted-text">會依目前網址上的 month / status / role 參數匯出。沒有篩選時就是全部。</p>
        <div class="actions compact-actions">
            <a class="button" href="/admin/payouts/export.csv?month={{ month or '' }}&status={{ status or '' }}&role={{ role or 'all' }}">匯出目前篩選</a>
            <a class="button secondary" href="/admin/payouts/export.csv?role=worker">只匯出打手</a>
            <a class="button secondary" href="/admin/payouts/export.csv?role=customer_service">只匯出客服</a>
        </div>
    </div>
'''

    if "{% block content %}" in text:
        text = text.replace("{% block content %}\n", "{% block content %}\n" + export_block, 1)
    else:
        text = export_block + text

    TEMPLATE_PATH.write_text(text, encoding="utf-8")
    print("patched admin_payouts.html")


def main() -> None:
    patch_main()
    patch_template()


if __name__ == "__main__":
    main()
