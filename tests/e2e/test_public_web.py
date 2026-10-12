from __future__ import annotations

import base64
import json
import os
import uuid

import pytest
from itsdangerous import TimestampSigner
from playwright.sync_api import Page, expect


BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


@pytest.fixture(autouse=True)
def _fail_on_uncaught_page_errors(page: Page):
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield
    assert errors == [], "Uncaught browser errors: " + " | ".join(errors)


def add_customer_session(page: Page, *, suffix: str = "01") -> str:
    """Install a real Starlette signed session without adding a test login route."""
    secret = os.environ["WEB_SECRET_KEY"]
    csrf_token = "e2e-csrf-" + uuid.uuid4().hex
    customer_id = "99999999999999" + suffix[-4:].zfill(4)
    session = {
        "user": {
            "id": customer_id,
            "username": "E2E Customer",
            "display_name": "E2E Customer",
            "global_name": "E2E Customer",
            "avatar": None,
            "is_admin": False,
            "is_manager": False,
            "is_customer_service": False,
            "is_employee": False,
            "is_worker": False,
            "is_companion": False,
            "role_ids": [],
        },
        "csrf_token": csrf_token,
    }
    raw = base64.b64encode(
        json.dumps(session, separators=(",", ":")).encode("utf-8")
    )
    signed = TimestampSigner(str(secret)).sign(raw).decode("utf-8")
    page.context.add_cookies(
        [
            {
                "name": "session",
                "value": signed,
                "domain": "127.0.0.1",
                "path": "/",
                "httpOnly": True,
                "secure": False,
                "sameSite": "Lax",
            }
        ]
    )
    return customer_id


def open_order_catalog(page: Page):
    response = page.goto(f"{BASE_URL}/order", wait_until="domcontentloaded")
    assert response is not None and response.ok
    expect(page.locator(".order3-store")).to_be_visible()
    return response


def open_order_dialog(page: Page, *, group_key: str | None = None) -> None:
    if group_key:
        button = page.locator(f'.order3-open[data-order-group="{group_key}"]')
        expect(button).to_have_count(1)
    else:
        buttons = page.locator(".order3-open")
        if buttons.count() == 0:
            pytest.skip("No public order groups are available in this fixture")
        button = buttons.first

    button.click()
    expect(page.locator("#mw-order-dialog")).to_be_visible()
    rule_key = page.locator("#mw-rule-key")
    expect(rule_key).not_to_have_text("")
    expect(rule_key).not_to_have_text("—")


def test_home_and_order_catalog_render(page: Page) -> None:
    home = page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    assert home is not None and home.ok
    expect(page.locator("body")).to_be_visible()

    open_order_catalog(page)
    expect(page.locator("body")).to_be_visible()


def test_order_dialog_can_open_and_close(page: Page) -> None:
    open_order_catalog(page)
    open_order_dialog(page)

    dialog = page.locator("#mw-order-dialog")
    expect(page.locator("#mw-dialog-title")).not_to_have_text("")
    page.locator("#mw-dialog-close").click()
    expect(dialog).not_to_be_visible()


def test_authenticated_quote_checkout_and_formal_order(page: Page) -> None:
    add_customer_session(page, suffix="101")
    open_order_catalog(page)

    # tech_play/basic_tech_secret_single is a stable auto-priced product. Do
    # not make this regression depend on whichever marketing group happens to
    # sort first or on a manual-quote product being first.
    open_order_dialog(page, group_key="tech_play")
    expect(page.locator("#mw-rule-key")).to_have_text("basic_tech_secret_single")

    price_button = page.locator("#mw-next-step")
    expect(price_button).to_be_visible()
    price_button.click()

    server_result = page.locator("#mw-server-result")
    expect(server_result).to_be_visible(timeout=10_000)
    expect(page.locator("#mw-server-total")).not_to_have_text("—")

    checkout_button = page.locator("#mw-open-checkout")
    expect(checkout_button).to_be_visible()
    checkout_button.click()

    checkout_panel = page.locator("#mw-checkout-panel")
    checkout_summary = page.locator("#mw-checkout-summary")
    expect(checkout_panel).to_be_visible(timeout=10_000)
    expect(checkout_summary).to_be_visible(timeout=10_000)

    # The real checkout controls must load even if this fixture has no points,
    # loyalty coupon, wallet balance, or eligible specified staff.
    expect(page.locator("#mw-checkout-point")).to_be_attached()
    expect(page.locator("#mw-checkout-benefit")).to_be_attached()
    expect(page.locator("#mw-co-total")).not_to_have_text("—")

    extra = page.locator("#mw-extra-requirements")
    extra.fill("E2E 正式下單流程測試")

    terms = page.locator("#mw-checkout-terms")
    terms.check()

    final_button = page.locator("#mw-checkout-final")
    expect(final_button).to_be_enabled()
    final_button.click()

    success = page.locator("#mw-checkout-success")
    expect(success).to_be_visible(timeout=10_000)
    expect(success).to_contain_text("訂單已建立")
    expect(final_button).to_have_text("正式訂單已建立")


def test_order_catalog_has_no_mobile_horizontal_overflow(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    open_order_catalog(page)

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
