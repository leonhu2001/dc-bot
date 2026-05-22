from pathlib import Path

APP_CSS = Path("web/app/static/css/app.css")
MARKER = "/* Compact navigation polish */"


def main() -> None:
    if not APP_CSS.exists():
        raise RuntimeError(f"找不到 {APP_CSS}")

    css = APP_CSS.read_text(encoding="utf-8")

    if MARKER in css:
        print("navigation css already installed")
        return

    append_path = Path("app_css_navigation_append.txt")

    if append_path.exists():
        append_css = append_path.read_text(encoding="utf-8")
    else:
        append_css = '''

/* Compact navigation polish */
.topbar { align-items: center; }
.nav { max-width: 720px; }
.nav-link { padding: 8px 11px; font-size: 13px; line-height: 1.2; }
.card.wide { max-width: 1280px; }
.panel { padding: 14px; margin-bottom: 12px; }
.order-card, .admin-order-card { padding: 14px; }
.admin-section { padding: 12px; margin-top: 12px; }
.order-meta { gap: 8px; margin-bottom: 12px; }
.order-meta div { padding: 9px; }
.admin-actions { gap: 8px; }
.button { padding: 9px 12px; border-radius: 10px; font-size: 13px; }
.input { padding: 9px 10px; }
'''

    APP_CSS.write_text(css.rstrip() + append_css + "\n", encoding="utf-8")
    print("navigation css installed")


if __name__ == "__main__":
    main()
