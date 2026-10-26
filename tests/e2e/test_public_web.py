from __future__ import annotations

import os
import re

import pytest
from playwright.sync_api import Page, expect


BASE_URL = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
PRICE_TEXT_RE = re.compile(r"\d[\d,]*T")


@pytest.fixture(autouse=True)
def _fail_on_uncaught_page_errors(page: Page):
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield
    assert errors == [], "Uncaught browser errors: " + " | ".join(errors)


def open_order_catalog(page: Page):
    response = page.goto(f"{BASE_URL}/order", wait_until="domcontentloaded")
    assert response is not None and response.ok
    expect(page.locator(".order3-store")).to_be_visible()
    return response


def open_first_order_dialog(page: Page):
    open_order_catalog(page)
    open_buttons = page.locator(".order3-open")
    if open_buttons.count() == 0:
        pytest.skip("No public order groups are available in this fixture")

    open_buttons.first.click()
    dialog = page.locator("#mw-order-dialog")
    expect(dialog).to_be_visible()
    return dialog


def _visible_heights(page: Page, selector: str) -> list[float]:
    return page.locator(selector).evaluate_all(
        """els => els
            .filter(el => {
                const s = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0;
            })
            .map(el => el.getBoundingClientRect().height)"""
    )


def test_home_and_order_catalog_render(page: Page) -> None:
    home = page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    assert home is not None and home.ok
    expect(page.locator("body")).to_be_visible()

    open_order_catalog(page)
    expect(page.locator("body")).to_be_visible()


def test_order_dialog_can_open_and_close(page: Page) -> None:
    dialog = open_first_order_dialog(page)
    expect(page.locator("#mw-dialog-title")).not_to_have_text("")

    page.locator("#mw-dialog-close").click()
    expect(dialog).not_to_be_visible()


def test_order_dialog_escape_uses_canonical_close_behavior(page: Page) -> None:
    dialog = open_first_order_dialog(page)
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()


def test_order_dialog_populates_variant_and_local_quote(page: Page) -> None:
    open_first_order_dialog(page)

    variant = page.locator("#mw-variant")
    expect(variant).to_be_visible()
    assert variant.locator("option").count() >= 1
    # The public DOM no longer needs to expose an internal rule-key attribute.
    # The selected option value is the canonical UI selection used by the quote flow.
    expect(variant).not_to_have_value("")

    expect(page.locator("#mw-dialog-title")).not_to_have_text("")
    expect(page.locator("#mw-rule-key")).to_have_count(0)
    expect(page.locator("#mw-total")).to_have_text(PRICE_TEXT_RE)
    expect(page.locator("#mw-total-detail")).not_to_have_text("選擇方案後即時計算")


def test_public_order_hides_internal_staffing_metadata(page: Page) -> None:
    open_first_order_dialog(page)

    expect(page.locator(".order3-info")).to_have_count(0)
    expect(page.locator("#mw-rule-key")).to_have_count(0)
    expect(page.locator("#mw-next-notice")).to_have_count(0)

    descriptions = "\n".join(page.locator(".order3-card > p").all_inner_texts())
    dialog_description_locator = page.locator("#mw-dialog-description")
    dialog_description = (
        dialog_description_locator.inner_text()
        if dialog_description_locator.count()
        else ""
    )
    public_copy = f"{descriptions}\n{dialog_description}"
    for internal_term in ("身分組", "智慧派單", "派單只通知", "Rule key"):
        assert internal_term not in public_copy
    assert "選擇適合你的方案。" not in descriptions


def test_visible_order_steppers_recalculate_without_page_reload(page: Page) -> None:
    open_first_order_dialog(page)

    candidates = (
        (
            page.locator("#mw-quantity-field"),
            page.locator("#mw-quantity"),
            page.locator("#mw-quantity-plus"),
        ),
        (
            page.locator("#mw-player-field"),
            page.locator("#mw-player-count"),
            page.locator("#mw-player-plus"),
        ),
    )

    for field, value, plus in candidates:
        if not field.is_visible() or not plus.is_enabled():
            continue

        before = value.inner_text()
        plus.click()
        page.wait_for_timeout(50)
        after = value.inner_text()

        if after == before:
            # Some variants can still clamp a nominally enabled control to the
            # same value. Try the next adjustable dimension before skipping.
            continue

        expect(page.locator("#mw-total")).to_have_text(PRICE_TEXT_RE)
        return

    pytest.skip("First public order group has no enabled stepper with an adjustable range")


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


def test_order_dialog_has_no_mobile_horizontal_overflow(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    open_first_order_dialog(page)

    widths = page.evaluate(
        """() => {
            const dialog = document.querySelector("#mw-order-dialog");
            const shell = dialog?.querySelector(".order3-dialog-shell");
            return {
                inner: window.innerWidth,
                dialog: dialog?.scrollWidth || 0,
                shell: shell?.scrollWidth || 0,
            };
        }"""
    )
    assert widths["dialog"] <= widths["inner"] + 2
    assert widths["shell"] <= widths["inner"] + 2


def test_mobile_home_renders_v6_structure_and_hides_desktop_hero(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    response = page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    assert response is not None and response.ok

    expect(page.locator(".mobile-v6-home")).to_be_visible()
    expect(page.locator(".mobile-v6-home-card")).to_be_visible()
    expect(page.locator(".hero")).not_to_be_visible()
    expect(page.locator(".trust-strip")).not_to_be_visible()

    dock = page.locator(".customer-app-bottom-nav")
    expect(dock).to_be_visible()
    box = dock.bounding_box()
    assert box is not None
    assert abs((box["y"] + box["height"]) - 844) <= 2


def test_mobile_order_skips_billboard_and_puts_products_near_top(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    open_order_catalog(page)

    expect(page.locator(".mobile-v6-order")).to_be_visible()
    expect(page.locator(".mobile-v6-category-strip")).to_be_visible()
    expect(page.locator(".order3-hero")).not_to_be_visible()
    expect(page.locator(".order3-filter")).not_to_be_visible()

    cards = page.locator(".order3-card")
    if cards.count() == 0:
        pytest.skip("No public order groups are available in this fixture")
    box = cards.first.bounding_box()
    assert box is not None
    assert box["y"] < 460


def test_mobile_home_component_sizes_are_consistent(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    response = page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
    assert response is not None and response.ok

    action_heights = _visible_heights(page, ".mobile-v6-actions a")
    assert len(action_heights) == 2
    assert all(43 <= height <= 45 for height in action_heights)
    assert max(action_heights) - min(action_heights) <= 1

    quick_heights = _visible_heights(page, ".mobile-v6-quick-grid a")
    assert len(quick_heights) == 4
    assert all(69 <= height <= 71 for height in quick_heights)
    assert max(quick_heights) - min(quick_heights) <= 1

    icon_box = page.locator(".customer-app-mark").bounding_box()
    assert icon_box is not None
    assert 39 <= icon_box["width"] <= 41
    assert 39 <= icon_box["height"] <= 41


def test_mobile_order_component_sizes_are_consistent(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    open_order_catalog(page)

    category_heights = _visible_heights(page, ".mobile-v6-category-strip a")
    assert category_heights
    assert all(41 <= height <= 43 for height in category_heights)
    assert max(category_heights) - min(category_heights) <= 1

    open_heights = _visible_heights(page, ".order3-open")
    if not open_heights:
        pytest.skip("No public order groups are available in this fixture")
    assert all(43 <= height <= 45 for height in open_heights[:4])

    media_box = page.locator(".order3-media").first.bounding_box()
    assert media_box is not None
    assert 87 <= media_box["width"] <= 89
    assert 99 <= media_box["height"] <= 101


def test_mobile_staff_and_vip_cards_do_not_inherit_oversized_min_heights(page: Page) -> None:
    page.set_viewport_size({"width": 390, "height": 844})

    staff = page.goto(f"{BASE_URL}/staff", wait_until="domcontentloaded")
    if staff is not None and staff.ok:
        filter_heights = _visible_heights(page, ".crew-filters a")
        assert filter_heights
        assert all(41 <= height <= 43 for height in filter_heights)

        crew_cards = page.locator(".public-crew-card")
        if crew_cards.count():
            min_height = crew_cards.first.evaluate("el => getComputedStyle(el).minHeight")
            assert min_height in {"0px", "auto"}
            more = crew_cards.first.locator(".public-crew-more")
            if more.count() and more.is_visible():
                box = more.bounding_box()
                assert box is not None
                assert 43 <= box["height"] <= 45

    vip = page.goto(f"{BASE_URL}/vip", wait_until="domcontentloaded")
    assert vip is not None and vip.ok
    levels = page.locator(".vip-level-card")
    assert levels.count() >= 1
    min_height = levels.first.evaluate("el => getComputedStyle(el).minHeight")
    assert min_height in {"0px", "auto"}


def test_health_endpoint_stays_public(page: Page) -> None:
    response = page.goto(f"{BASE_URL}/health", wait_until="domcontentloaded")
    assert response is not None and response.ok
