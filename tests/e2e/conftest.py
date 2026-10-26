from __future__ import annotations

import pytest
from playwright.sync_api import Page


@pytest.fixture(autouse=True)
def _select_render_surface(request: pytest.FixtureRequest, page: Page) -> None:
    """Make the browser fixture exercise the same server-side surface split as production."""
    mobile = "mobile" in request.node.name.lower()
    page.context.set_extra_http_headers(
        {"Sec-CH-UA-Mobile": "?1" if mobile else "?0"}
    )
