from __future__ import annotations

import os

from playwright.sync_api import Page, expect


BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def test_mobile_home_experience_cards_stay_in_two_equal_columns(page: Page) -> None:
    # The server chooses a UI surface from device hints, not viewport width alone.
    # This keeps a narrow desktop window on the desktop pathway.
    page.context.set_extra_http_headers({"Sec-CH-UA-Mobile": "?1"})
    page.set_viewport_size({"width": 390, "height": 844})
    response = page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    assert response is not None and response.ok

    assert page.locator("body").get_attribute("data-ui-surface") == "mobile"
    expect(page.locator(".customer-app-topbar")).to_be_visible()

    grid = page.locator(".experience-grid")
    expect(grid).to_be_visible()
    cards = grid.locator(".experience-card")
    assert cards.count() == 5

    geometry = grid.evaluate(
        """el => {
            const style = getComputedStyle(el);
            const cards = [...el.querySelectorAll('.experience-card')];
            return {
                autoFlow: style.gridAutoFlow,
                clientWidth: el.clientWidth,
                scrollWidth: el.scrollWidth,
                cardWidths: cards.map(card => card.getBoundingClientRect().width),
                gridLeft: el.getBoundingClientRect().left,
            };
        }"""
    )

    assert geometry["autoFlow"] == "row"
    assert geometry["scrollWidth"] <= geometry["clientWidth"] + 2
    assert max(geometry["cardWidths"]) - min(geometry["cardWidths"]) <= 2
    assert min(geometry["cardWidths"]) >= 150

    heading = page.locator(".experience-section .section-heading")
    expect(heading).to_be_visible()
    heading_box = heading.bounding_box()
    grid_box = grid.bounding_box()
    assert heading_box is not None and grid_box is not None
    assert abs(heading_box["x"] - grid_box["x"]) <= 2

    page_widths = page.evaluate(
        """() => ({
            inner: window.innerWidth,
            body: document.body.scrollWidth,
            root: document.documentElement.scrollWidth,
        })"""
    )
    assert page_widths["body"] <= page_widths["inner"] + 2
    assert page_widths["root"] <= page_widths["inner"] + 2


def test_narrow_desktop_viewport_never_enters_mobile_surface(page: Page) -> None:
    page.context.set_extra_http_headers({"Sec-CH-UA-Mobile": "?0"})
    page.set_viewport_size({"width": 390, "height": 844})
    response = page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    assert response is not None and response.ok

    assert page.locator("body").get_attribute("data-ui-surface") == "desktop"
    expect(page.locator(".site-header")).to_be_visible()
    expect(page.locator(".customer-app-topbar")).to_have_count(0)
    expect(page.locator(".customer-app-bottom-nav")).to_have_count(0)

    stylesheets = page.eval_on_selector_all(
        'link[rel="stylesheet"]',
        "els => els.map(el => el.getAttribute('href') || '')",
    )
    assert not any("mobile_app_rebuild" in href for href in stylesheets)
    assert not any("mobile_surface_sizing" in href for href in stylesheets)
    assert not any("customer_mobile_app" in href for href in stylesheets)
