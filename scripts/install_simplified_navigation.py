from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = PROJECT_ROOT / "web" / "app" / "static" / "css" / "app.css"

CSS_BLOCK = r'''

/* simplified role navigation */
.compact-topbar {
    margin-bottom: 16px;
}

.compact-user {
    margin-top: 6px;
    font-size: 13px;
}

.role-nav {
    align-items: flex-start;
    gap: 8px;
}

.nav-group {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    padding: 8px;
    border: 1px solid #374151;
    border-radius: 12px;
    background: rgba(17, 24, 39, .55);
}

.nav-label {
    color: #9ca3af;
    font-size: 12px;
    font-weight: 800;
    padding: 0 4px;
}

.role-nav .nav-link {
    padding: 8px 10px;
    border-radius: 9px;
    font-size: 13px;
}

.card.wide {
    max-width: 1040px;
}

.panel {
    padding: 14px;
    margin-bottom: 12px;
}

.order-card,
.admin-order-card {
    padding: 14px;
}

.admin-section {
    padding: 12px;
    margin-top: 12px;
}

.order-meta {
    gap: 8px;
    margin-bottom: 12px;
}

.order-meta div {
    padding: 10px;
}

.big-number {
    font-size: 26px;
}

@media (max-width: 840px) {
    .nav-group {
        width: 100%;
    }
}
'''


def main() -> None:
    text = CSS_PATH.read_text(encoding="utf-8") if CSS_PATH.exists() else ""

    marker = "/* simplified role navigation */"
    if marker not in text:
        text = text.rstrip() + CSS_BLOCK
        CSS_PATH.write_text(text + "\n", encoding="utf-8")
        print("patched app.css simplified navigation styles")
    else:
        print("app.css already has simplified navigation styles")


if __name__ == "__main__":
    main()
