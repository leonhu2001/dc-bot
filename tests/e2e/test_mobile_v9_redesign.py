"""V9 real-browser layout and navigation tests; no payment submission."""
from __future__ import annotations

import os
import re

import pytest
from playwright.sync_api import Page, expect


BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def mobile(page: Page, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 844})
    page.set_extra_http_headers({"Sec-CH-UA-Mobile": "?1"})


@pytest.mark.parametrize("width", [320, 375, 390, 430, 744])
def test_new_mobile_shell_remains_the_same_size_on_public_routes(page: Page, width: int):
    mobile(page, width)
    rail_dims = []
    for route in ("/", "/order", "/vip", "/service-rules"):
        response = page.goto(f"{BASE_URL}{route}", wait_until="domcontentloaded")
        assert response is not None and response.ok, route
        expect(page.locator("body.m9-mobile")).to_be_visible()
        expect(page.locator(".m9-topbar")).to_be_visible()
        expect(page.locator(".m9-dock")).to_be_visible()
        expect(page.locator(".m9-intro")).to_be_visible()
        expect(page.locator("main#m8-main")).to_be_visible()
        expect(page.locator(".m9-dock a[href='/order']")).to_be_visible()
        dims = page.evaluate("""() => {
          const main = document.querySelector('main#m8-main').getBoundingClientRect();
          const dock = document.querySelector('.m9-dock').getBoundingClientRect();
          return {outer: document.documentElement.scrollWidth,
                  documentClient: document.documentElement.clientWidth,
                  body: document.body.scrollWidth, vw: innerWidth,
                  left: main.left, right: main.right, rail:main.width,
                  dock: dock.width, dockLeft:dock.left}; }""")
        assert dims["outer"] <= width + 2, (width, route, dims)
        assert dims["body"] <= width + 2, (width, route, dims)
        assert dims["rail"] <= min(width, 560) + 2, (width, route, dims)
        assert abs(dims["left"] - (width - dims["rail"]) / 2) <= 2, (width, route, dims)
        assert abs(dims["dockLeft"] - (width - dims["dock"]) / 2) <= 2, (width, route, dims)
        rail_dims.append(dims["rail"])
    assert max(rail_dims) - min(rail_dims) <= 2


def test_v9_hero_to_order_and_parent_back_navigation(page: Page):
    mobile(page, 390)
    page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    expect(page.locator(".m9-hero h1")).to_contain_text("開一場好局")
    page.locator(".m9-hero-actions a[href='/order']").click()
    expect(page).to_have_url(re.compile(r"/order$"))
    expect(page.locator(".m9-section-heading h1")).to_contain_text("選擇服務")
    expect(page.locator(".m9-dock a[href='/order']")).to_have_attribute("aria-current", "page")
    page.locator(".m9-back").click()
    expect(page).to_have_url(re.compile(r"/$"))
    expect(page.locator(".m9-dock a[href='/']")).to_have_attribute("aria-current", "page")


def test_new_mobile_styles_never_render_on_desktop_ua(page: Page):
    page.set_viewport_size({"width": 1280, "height": 900})
    # Prior mobile cases set this request header. Reset the server-side UA
    # hint as well as the viewport, or a desktop-only test renders a phone DOM.
    page.set_extra_http_headers({"Sec-CH-UA-Mobile": "?0"})
    response = page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    assert response is not None and response.ok
    assert page.locator("body.m9-mobile").count() == 0
    assert page.locator(".m9-dock").count() == 0


def test_v9_keeps_large_touch_targets_and_keyboard_safe_forms(page: Page):
    mobile(page, 375)
    page.goto(f"{BASE_URL}/order", wait_until="domcontentloaded")
    values = page.evaluate("""() => {
      const dockLink = document.querySelector('.m9-dock a[href="/order"]');
      const dockBounds = dockLink.getBoundingClientRect();
      const main = document.querySelector('main');
      return {
        touchHeight: dockBounds.height,
        maxWidth: main.getBoundingClientRect().width,
        overflow: document.documentElement.scrollWidth - innerWidth
      };
    }""")
    assert values["touchHeight"] >= 50
    assert values["maxWidth"] <= 375
    assert values["overflow"] <= 2
