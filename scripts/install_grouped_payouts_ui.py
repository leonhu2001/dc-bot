from pathlib import Path

APP_CSS = Path("web/app/static/css/app.css")

CSS_BLOCK = r'''

/* grouped monthly payouts ui */
.payout-hero {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 18px;
    padding: 18px 20px;
}

.payout-hero-main h2 {
    margin: 4px 0 6px;
}

.payout-hero-actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

.payout-filter-panel {
    padding: 14px 16px;
}

.payout-filter-form {
    display: grid;
    grid-template-columns: repeat(3, minmax(180px, 1fr)) auto;
    gap: 12px;
    align-items: end;
}

.payout-filter-form label {
    display: grid;
    gap: 6px;
    color: #9fb2cf;
    font-size: 13px;
}

.payout-stat-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(160px, 1fr));
    gap: 12px;
    margin: 14px 0;
}

.payout-stat-card {
    border: 1px solid rgba(148, 163, 184, 0.22);
    border-radius: 16px;
    background: linear-gradient(180deg, rgba(30, 41, 59, 0.86), rgba(15, 23, 42, 0.9));
    padding: 16px;
}

.payout-stat-card span {
    display: block;
    color: #93a4bd;
    font-size: 13px;
    margin-bottom: 8px;
}

.payout-stat-card strong {
    font-size: 24px;
    letter-spacing: -0.02em;
}

.highlight-unpaid strong,
.text-unpaid {
    color: #5eead4;
}

.highlight-paid strong,
.text-paid {
    color: #93c5fd;
}

.section-title-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 12px;
}

.section-title-row h2 {
    margin: 0 0 4px;
}

.payout-person-list {
    display: grid;
    gap: 12px;
}

.payout-person-card {
    border: 1px solid rgba(148, 163, 184, 0.24);
    border-radius: 18px;
    background: rgba(15, 23, 42, 0.62);
    overflow: hidden;
}

.payout-person-card[open] {
    box-shadow: 0 18px 42px rgba(2, 6, 23, 0.22);
}

.payout-person-summary {
    display: grid;
    grid-template-columns: minmax(260px, 1fr) minmax(360px, 0.9fr);
    gap: 18px;
    align-items: center;
    padding: 16px 18px;
    cursor: pointer;
    list-style: none;
}

.payout-person-summary::-webkit-details-marker {
    display: none;
}

.person-left {
    display: flex;
    align-items: center;
    gap: 14px;
    min-width: 0;
}

.person-avatar {
    width: 44px;
    height: 44px;
    display: grid;
    place-items: center;
    border-radius: 14px;
    background: linear-gradient(135deg, #6366f1, #14b8a6);
    color: #fff;
    font-weight: 800;
    font-size: 20px;
    flex: 0 0 auto;
}

.person-role {
    color: #60a5fa;
    font-size: 13px;
    font-weight: 700;
    margin-bottom: 3px;
}

.person-left h3 {
    margin: 0;
    font-size: 18px;
}

.person-left p {
    margin: 4px 0 0;
    color: #94a3b8;
    font-size: 12px;
    word-break: break-all;
}

.person-totals {
    display: grid;
    grid-template-columns: repeat(4, minmax(74px, 1fr));
    gap: 8px;
}

.person-totals div {
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 12px;
    padding: 10px;
    background: rgba(2, 6, 23, 0.28);
}

.person-totals span {
    display: block;
    color: #93a4bd;
    font-size: 12px;
    margin-bottom: 4px;
}

.person-totals strong {
    font-size: 16px;
}

.person-total-main {
    background: rgba(99, 102, 241, 0.16) !important;
    border-color: rgba(129, 140, 248, 0.4) !important;
}

.payout-person-body {
    border-top: 1px solid rgba(148, 163, 184, 0.18);
    padding: 14px 18px 18px;
}

.payout-bulk-actions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-bottom: 12px;
}

.payout-order-list {
    border: 1px solid rgba(148, 163, 184, 0.18);
    border-radius: 14px;
    overflow: hidden;
}

.payout-order-header,
.payout-order-row {
    display: grid;
    grid-template-columns: 1.1fr 2.1fr 0.7fr 0.7fr 0.8fr 0.9fr;
    gap: 10px;
    align-items: center;
    padding: 11px 12px;
}

.payout-order-header {
    background: rgba(30, 41, 59, 0.72);
    color: #93c5fd;
    font-size: 12px;
    font-weight: 800;
}

.payout-order-row {
    border-top: 1px solid rgba(148, 163, 184, 0.14);
    color: #e5edf7;
    font-size: 14px;
}

.order-no-cell {
    color: #bfdbfe;
    font-weight: 700;
}

.amount-cell {
    font-weight: 800;
    color: #fff;
}

.status-chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 62px;
    border-radius: 999px;
    padding: 5px 9px;
    font-size: 12px;
    font-weight: 800;
}

.status-chip.is-paid {
    background: rgba(59, 130, 246, 0.18);
    color: #bfdbfe;
}

.status-chip.is-unpaid {
    background: rgba(20, 184, 166, 0.18);
    color: #99f6e4;
}

@media (max-width: 900px) {
    .payout-hero,
    .payout-person-summary {
        grid-template-columns: 1fr;
        display: grid;
    }

    .payout-filter-form,
    .payout-stat-grid {
        grid-template-columns: 1fr;
    }

    .person-totals {
        grid-template-columns: repeat(2, 1fr);
    }

    .payout-order-header {
        display: none;
    }

    .payout-order-row {
        grid-template-columns: 1fr 1fr;
    }
}
'''


def main() -> None:
    if not APP_CSS.exists():
        raise FileNotFoundError(APP_CSS)

    text = APP_CSS.read_text(encoding="utf-8")

    marker = "/* grouped monthly payouts ui */"
    if marker in text:
        before = text.split(marker, 1)[0].rstrip()
        APP_CSS.write_text(before + "\n" + CSS_BLOCK.lstrip(), encoding="utf-8")
        print("updated grouped payouts ui css")
    else:
        APP_CSS.write_text(text.rstrip() + "\n\n" + CSS_BLOCK.lstrip(), encoding="utf-8")
        print("added grouped payouts ui css")


if __name__ == "__main__":
    main()
