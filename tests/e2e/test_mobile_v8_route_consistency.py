"""Real mobile browser verification for page-width continuity and navigation."""
from __future__ import annotations

import os
import re

import pytest
from playwright.sync_api import Page, expect


BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


@pytest.mark.parametrize("width", [320, 375, 390, 430])
def test_mobile_v8_public_page_boundaries_do_not_change_between_routes(
    page: Page, width: int,
) -> None:
    page.set_viewport_size({"width": width, "height": 844})
    page.set_extra_http_headers({"Sec-CH-UA-Mobile": "?1"})
    widths = []
    for path in ("/", "/order", "/vip", "/service-rules"):
        response = page.goto(f"{BASE_URL}{path}", wait_until="domcontentloaded")
        assert response is not None and response.ok, path
        expect(page.locator(".customer-app-topbar")).to_be_visible()
        expect(page.locator(".customer-app-bottom-nav")).to_be_visible()
        expect(page.locator("main#m8-main")).to_be_visible()
        assert page.locator(".m8-skip-link").count() == 1
        geom = page.evaluate("""() => {
          const rail = document.querySelector('main#m8-main').getBoundingClientRect();
          const dock = document.querySelector('.customer-app-bottom-nav').getBoundingClientRect();
          return {
            viewport: window.innerWidth, body: document.body.scrollWidth,
            document: document.documentElement.scrollWidth,
            railLeft: rail.left, railWidth: rail.width,
            dockLeft: dock.left, dockWidth: dock.width
          };
        }""")
        assert geom["body"] <= width + 2, (path, width, geom)
        assert geom["document"] <= width + 2, (path, width, geom)
        assert abs(geom["railLeft"]) <= 2, (path, width, geom)
        assert geom["dockWidth"] <= width + 2, (path, width, geom)
        assert abs(geom["dockLeft"]) <= 2, (path, width, geom)
        widths.append(geom["railWidth"])
    assert max(widths) - min(widths) <= 2, (width, widths)


def test_mobile_v8_bottom_navigation_and_back_link_work_as_real_routes(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.set_extra_http_headers({"Sec-CH-UA-Mobile": "?1"})
    page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    page.locator(".customer-app-bottom-nav a[href='/order']").click()
    expect(page).to_have_url(re.compile(r"/order$"))
    expect(page.locator(".customer-app-bottom-nav a[href='/order']")).to_have_attribute(
        "aria-current", "page"
    )
    page.locator(".m8-route-back").click()
    expect(page).to_have_url(re.compile(r"/$"))
    expect(page.locator(".customer-app-bottom-nav a[href='/']")).to_have_attribute(
        "aria-current", "page"
    )


def test_mobile_v8_shell_is_visible_at_744px_without_720px_breakpoint_gap(page: Page) -> None:
    page.set_viewport_size({"width": 744, "height": 960})
    page.set_extra_http_headers({"Sec-CH-UA-Mobile": "?1"})
    for route in ("/", "/order"):
        response = page.goto(f"{BASE_URL}{route}", wait_until="domcontentloaded")
        assert response is not None and response.ok
        expect(page.locator(".customer-app-topbar")).to_be_visible()
        expect(page.locator(".customer-app-bottom-nav")).to_be_visible()
        dims = page.evaluate("""() => {
            const rail = document.querySelector('main#m8-main').getBoundingClientRect();
            const bar = document.querySelector('.customer-app-bottom-nav').getBoundingClientRect();
            return {railWidth: rail.width, railLeft: rail.left, dockWidth:bar.width,
                    dockLeft:bar.left, outer:document.documentElement.scrollWidth,
                    client:document.documentElement.clientWidth,
                    layoutWidth:document.body.getBoundingClientRect().width,
                    viewport:innerWidth};
        }""")
        assert abs(dims["railWidth"] - 560) <= 2, (route, dims)
        assert abs(dims["railLeft"] - (dims["layoutWidth"] - 560) / 2) <= 2, (route, dims)
        assert abs(dims["dockLeft"] - (dims["layoutWidth"] - dims["dockWidth"]) / 2) <= 2, (route, dims)
        assert dims["outer"] <= 746, (route, dims)
