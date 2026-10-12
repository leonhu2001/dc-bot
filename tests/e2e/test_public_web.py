from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page, expect


BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


@pytest.fixture(autouse=True)
def _fail_on_uncaught_page_errors(page: Page):
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield
    assert errors == [], "Uncaught browser errors: " + " | ".join(errors)


def test_home_and_order_catalog_render(page: Page) -> None:
    home = page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    assert home is not None and home.ok
    expect(page.locator("body")).to_be_visible()

    order = page.goto(f"{BASE_URL}/order", wait_until="networkidle")
    assert order is not None and order.ok
    expect(page.locator("body")).to_be_visible()
    expect(page.locator(".order3-store")).to_be_visible()


def test_order_dialog_can_open_and_close(page: Page) -> None:
    response = page.goto(f"{BASE_URL}/order", wait_until="networkidle")
    assert response is not None and response.ok

    open_buttons = page.locator(".order3-open")
    if open_buttons.count() == 0:
        pytest.skip("No public order groups are available in this fixture")

    open_buttons.first.click()
    dialog = page.locator("#mw-order-dialog")
    expect(dialog).to_be_visible()
    expect(page.locator("#mw-dialog-title")).not_to_have_text("")

    page.locator("#mw-dialog-close").click()
    expect(dialog).not_to_be_visible()


def test_order_catalog_has_no_mobile_horizontal_overflow(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    response = page.goto(f"{BASE_URL}/order", wait_until="networkidle")
    assert response is not None and response.ok

    widths = page.evaluate(
        """() => ({
            inner: window.innerWidth,
            body: document.body.scrollWidth,
            root: document.documentElement.scrollWidth,
        })"""
    )
    assert widths["body"] <= widths["inner"] + 2
    assert widths["root"] <= widths["inner"] + 2


def test_health_endpoint_stays_public(page: Page) -> None:
    response = page.goto(f"{BASE_URL}/health", wait_until="domcontentloaded")
    assert response is not None and response.ok
