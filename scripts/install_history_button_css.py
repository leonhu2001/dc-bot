from pathlib import Path

CSS_PATH = Path("web/app/static/css/app.css")
MARKER = "/* history button ui override */"
CSS = r'''
/* history button ui override */
.history-page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    margin-bottom: 12px;
}

.history-page-header h2 {
    margin: 0 0 4px;
    font-size: 22px;
}

.history-filter-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    margin: 0 0 14px;
}

.history-back-button,
.history-filter-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 34px;
    padding: 0 14px;
    border-radius: 10px;
    font-size: 14px;
    font-weight: 700;
    text-decoration: none;
    border: 1px solid rgba(148, 163, 184, 0.24);
    transition: transform 0.12s ease, border-color 0.12s ease, background 0.12s ease;
}

.history-back-button {
    color: #e5edff;
    background: rgba(51, 65, 85, 0.9);
}

.history-back-button:hover {
    background: rgba(71, 85, 105, 0.95);
    border-color: rgba(148, 163, 184, 0.42);
    transform: translateY(-1px);
}

.history-filter-button {
    color: #cbd5e1;
    background: rgba(15, 23, 42, 0.72);
}

.history-filter-button:hover {
    color: #ffffff;
    background: rgba(30, 41, 59, 0.92);
    border-color: rgba(129, 140, 248, 0.5);
    transform: translateY(-1px);
}

.history-filter-button.is-active {
    color: #ffffff;
    background: linear-gradient(135deg, #5865f2, #7c3aed);
    border-color: rgba(199, 210, 254, 0.55);
    box-shadow: 0 8px 18px rgba(88, 101, 242, 0.24);
}

.compact-panel {
    padding: 14px;
}

.history-order-list {
    display: grid;
    gap: 10px;
}

.history-order-card {
    padding: 14px;
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 14px;
    background: rgba(15, 23, 42, 0.54);
}

.history-order-main {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    align-items: flex-start;
    margin-bottom: 10px;
}

.history-order-main h3 {
    margin: 2px 0 0;
    font-size: 16px;
}

.history-order-meta {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px;
}

.history-order-meta > div {
    padding: 9px 10px;
    border-radius: 10px;
    background: rgba(2, 6, 23, 0.42);
    border: 1px solid rgba(148, 163, 184, 0.16);
}

.history-order-meta span {
    display: block;
    color: #94a3b8;
    font-size: 12px;
    margin-bottom: 3px;
}

.history-order-meta strong {
    color: #ffffff;
    font-size: 14px;
}

.status-stored {
    background: rgba(250, 204, 21, 0.14);
    color: #fde68a;
}

.status-closed {
    background: rgba(34, 197, 94, 0.14);
    color: #86efac;
}

.status-cancelled {
    background: rgba(248, 113, 113, 0.14);
    color: #fca5a5;
}

@media (max-width: 900px) {
    .history-order-meta {
        grid-template-columns: repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 560px) {
    .history-order-meta {
        grid-template-columns: 1fr;
    }
}
'''


def main() -> None:
    text = CSS_PATH.read_text(encoding="utf-8") if CSS_PATH.exists() else ""

    if MARKER in text:
        text = text.split(MARKER, 1)[0].rstrip() + "\n" + CSS.strip() + "\n"
    else:
        text = text.rstrip() + "\n\n" + CSS.strip() + "\n"

    CSS_PATH.write_text(text, encoding="utf-8")
    print("patched history button css")


if __name__ == "__main__":
    main()
