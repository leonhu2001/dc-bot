"""Employee salary dashboard pagination: real client JS in Chromium.

This test uses synthetic salary data and never accesses real employee payroll.
"""
from __future__ import annotations

import json
import os

from playwright.sync_api import Page, expect

BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def test_salary_pagination_keeps_totals_and_filters_without_long_page(page: Page):
    # A valid local origin lets the real client-side fetch use /employee/salary-data.
    page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    page.set_viewport_size({"width": 1200, "height": 800})
    page.set_content("""
    <html><body>
      <div class="employee-workspace-hero" data-employee-user-id="pagination-test"></div>
      <div id="salaryPending"></div><div id="salaryPendingSub"></div>
      <div id="salaryMonthPaid"></div><div id="salaryMonthPaidSub"></div>
      <div id="salaryLifetime"></div><div id="salaryLifetimeSub"></div>
      <button class="salary-tab" data-filter="all"><span data-count="all"></span></button>
      <button class="salary-tab" data-filter="service"><span data-count="service"></span></button>
      <button class="salary-tab" data-filter="tip"><span data-count="tip"></span></button>
      <button class="salary-tab" data-filter="internal_transfer"><span data-count="internal_transfer"></span></button>
      <div class="salary-list"><div id="salaryRows"></div></div>
      <nav id="salaryPagination" hidden>
        <span id="salaryPageInfo"></span>
        <button id="salaryPagePrevious">上一頁</button>
        <div id="salaryPageNumbers"></div>
        <button id="salaryPageNext">下一頁</button>
      </nav>
    </body></html>
    """)
    items = [
        {
            "closed_date": "2026-11-11",
            "order_no": f"MO-{n:03d}",
            "category_key": "tip" if n % 3 == 0 else "service",
            "category_label": "🍗 雞腿" if n % 3 == 0 else "服務薪資",
            "service_label": f"測試薪資 {n}",
            "payout_status": "unpaid",
            "financial_state": "unpaid",
            "status_label": "待發放",
            "amount": 10,
        }
        for n in range(1, 34)
    ]
    tips = sum(row["category_key"] == "tip" for row in items)
    data = {
        "summary": {
            "pending": 330, "pending_count": 33, "locked_count": 0,
            "current_month_paid": 0, "current_month_label": "2026年11月",
            "lifetime": 330, "paid_total": 0, "all_count": 33,
        },
        "categories": {
            "all": {"count": 33, "total": 330},
            "service": {"count": 33 - tips, "total": (33 - tips) * 10},
            "tip": {"count": tips, "total": tips * 10},
            "internal_transfer": {"count": 0, "total": 0},
        },
        "items": items,
    }

    page.route(
        "**/employee/salary-data",
        lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"ok": True, "data": data}, ensure_ascii=False),
        ),
    )
    # Load the served static asset as a same-origin external script: the
    # production CSP intentionally rejects Playwright's injected inline text.
    page.add_script_tag(
        url=f"{BASE_URL}/static/js/pages/employee_center.js"
    )

    expect(page.locator("#salaryRows .salary-row")).to_have_count(12)
    expect(page.locator("#salaryRows .salary-order").first).to_have_text("MO-001")
    expect(page.locator("#salaryPageInfo")).to_contain_text("共 33 筆")
    expect(page.locator("#salaryPageInfo")).to_contain_text("第 1／3 頁")
    expect(page.locator("#salaryPending")).to_have_text("330T")
    expect(page.locator("#salaryLifetime")).to_have_text("330T")
    expect(page.locator("[data-count='tip']")).to_have_text(str(tips))

    page.locator("#salaryPageNext").click()
    expect(page.locator("#salaryRows .salary-row")).to_have_count(12)
    expect(page.locator("#salaryRows .salary-order").first).to_have_text("MO-013")
    expect(page.locator("#salaryPageInfo")).to_contain_text("第 2／3 頁")

    page.locator("#salaryPageNext").click()
    expect(page.locator("#salaryRows .salary-row")).to_have_count(9)
    expect(page.locator("#salaryRows .salary-order").first).to_have_text("MO-025")
    expect(page.locator("#salaryPageNext")).to_be_disabled()
    expect(page.locator("#salaryPending")).to_have_text("330T")

    # Switching category resets the page and uses only that category's records.
    page.locator(".salary-tab[data-filter='tip']").click()
    expect(page.locator("#salaryRows .salary-row")).to_have_count(tips)
    expect(page.locator("#salaryPagination")).to_be_hidden()
    expect(page.locator("#salaryRows .salary-order").first).to_have_text("MO-003")
    expect(page.locator("#salaryLifetime")).to_have_text("330T")

    page.locator(".salary-tab[data-filter='internal_transfer']").click()
    expect(page.locator(".salary-empty")).to_contain_text("沒有薪資紀錄")
    expect(page.locator("#salaryPagination")).to_be_hidden()

    page.locator(".salary-tab[data-filter='all']").click()
    expect(page.locator("#salaryRows .salary-row")).to_have_count(12)
    expect(page.locator("#salaryRows .salary-order").first).to_have_text("MO-001")
    expect(page.locator("#salaryPageInfo")).to_contain_text("第 1／3 頁")
