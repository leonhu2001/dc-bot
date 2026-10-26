from __future__ import annotations

import pytest
from playwright.sync_api import Page


@pytest.fixture(autouse=True)
def _select_server_render_path(request: pytest.FixtureRequest, page: Page) -> None:
    """Mobile-named browser tests must exercise the server mobile render tree.

    A narrow desktop viewport is not a mobile request once templates are split at
    render time, so mark those requests explicitly. Normal tests remain desktop.
    """
    if "mobile" in request.node.name:
        page.set_extra_http_headers({"Sec-CH-UA-Mobile": "?1"})
