from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ORDER_SERVICE = ROOT / "web" / "app" / "services" / "order_service.py"
CSS_FILE = ROOT / "web" / "app" / "static" / "css" / "app.css"


def patch_order_service() -> None:
    text = ORDER_SERVICE.read_text(encoding="utf-8")

    create_demo_pattern = re.compile(
        r"def create_demo_orders_if_empty\(db: Session\) -> None:\n.*?\n\ndef list_active_orders",
        re.DOTALL,
    )
    create_demo_replacement = (
        "def create_demo_orders_if_empty(db: Session) -> None:\n"
        "    # 正式環境不再自動建立 DEMO 測試訂單。\n"
        "    return\n\n\n"
        "def list_active_orders"
    )
    text, demo_count = create_demo_pattern.subn(create_demo_replacement, text, count=1)

    list_admin_pattern = re.compile(
        r"def list_admin_orders\(db: Session\) -> list\[WebOrder\]:\n.*?\n\ndef get_worker_active_assignments",
        re.DOTALL,
    )
    list_admin_replacement = (
        "def list_admin_orders(db: Session, status_filter: str | None = \"active\") -> list[WebOrder]:\n"
        "    statement = (\n"
        "        select(WebOrder)\n"
        "        .options(selectinload(WebOrder.assignments))\n"
        "        .options(selectinload(WebOrder.payouts))\n"
        "        .order_by(WebOrder.created_at.desc())\n"
        "    )\n\n"
        "    if status_filter and status_filter != \"all\":\n"
        "        statement = statement.where(WebOrder.status == str(status_filter))\n\n"
        "    return list(db.scalars(statement).all())\n\n\n"
        "def get_worker_active_assignments"
    )
    text, admin_count = list_admin_pattern.subn(list_admin_replacement, text, count=1)

    if admin_count != 1:
        raise RuntimeError("找不到 list_admin_orders，沒有套用後台 active 過濾。")

    ORDER_SERVICE.write_text(text, encoding="utf-8")
    print(f"patched order_service.py demo_noop={demo_count} admin_filter={admin_count}")


def patch_css() -> None:
    css = CSS_FILE.read_text(encoding="utf-8") if CSS_FILE.exists() else ""
    marker_start = "/* === compact admin layout override start === */"
    marker_end = "/* === compact admin layout override end === */"
    compact_css = f"""
{marker_start}
.page {{
    align-items: start;
    padding: 14px;
}}

.card.wide {{
    max-width: 1320px;
    padding: 18px;
    border-radius: 14px;
}}

.topbar {{
    margin-bottom: 14px;
}}

h1 {{
    font-size: 26px;
}}

h2 {{
    font-size: 17px;
    margin-bottom: 8px;
}}

h3 {{
    font-size: 17px;
}}

h4 {{
    font-size: 15px;
    margin-bottom: 8px;
}}

p {{
    line-height: 1.45;
    margin-top: 6px;
    margin-bottom: 6px;
}}

.grid {{
    gap: 10px;
    margin-bottom: 12px;
}}

.panel {{
    padding: 12px;
    margin-bottom: 10px;
    border-radius: 12px;
}}

.big-number {{
    font-size: 24px;
    margin: 4px 0;
}}

.admin-order-list,
.order-list {{
    gap: 10px;
    margin-top: 10px;
}}

.admin-order-card,
.order-card {{
    padding: 12px;
    border-radius: 12px;
}}

.order-card-header {{
    margin-bottom: 10px;
}}

.order-meta {{
    gap: 8px;
    margin-bottom: 10px;
}}

.order-meta div {{
    padding: 9px;
    border-radius: 10px;
}}

.admin-section,
.assignment-box {{
    margin-top: 10px;
    padding: 10px;
    border-radius: 10px;
}}

.admin-worker-card {{
    padding: 10px;
    border-radius: 10px;
}}

.admin-actions,
.actions {{
    gap: 8px;
    margin-top: 10px;
}}

.button {{
    padding: 9px 12px;
    border-radius: 10px;
    font-size: 13px;
}}

.input {{
    padding: 9px 10px;
    border-radius: 9px;
}}

.worker-payout-line {{
    gap: 7px;
    margin-top: 7px;
}}

.worker-payout-line span,
.worker-payout-line strong {{
    padding: 6px 9px;
    font-size: 13px;
}}

.muted-text,
.order-meta span {{
    font-size: 12px;
}}
{marker_end}
"""
    pattern = re.compile(re.escape(marker_start) + r".*?" + re.escape(marker_end), re.DOTALL)
    if marker_start in css:
        css = pattern.sub(compact_css.strip(), css)
    else:
        css = css.rstrip() + "\n\n" + compact_css.strip() + "\n"
    CSS_FILE.write_text(css, encoding="utf-8")
    print("patched app.css compact override")


def main() -> None:
    patch_order_service()
    patch_css()


if __name__ == "__main__":
    main()
