from __future__ import annotations

import os

from playwright.sync_api import Page, expect


BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def test_mobile_home_experience_cards_stay_in_two_equal_columns(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    response = page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    assert response is not None and response.ok

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
