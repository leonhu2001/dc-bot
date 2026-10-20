from services.web_sync.cs_presentation import admin_order_workspace_url


def test_admin_order_link_is_https():
    assert admin_order_workspace_url(1).startswith("https://")
