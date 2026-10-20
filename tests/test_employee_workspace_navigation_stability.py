from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_public_and_backoffice_layouts_share_global_scrollbar_lane():
    site_layout = _read("web/app/templates/site_layout.html")
    backoffice_layout = _read("web/app/templates/layout.html")
    css = _read("web/app/static/css/mw_global_scrollbar.css")

    stylesheet = "/static/css/mw_global_scrollbar.css?v=20261020-1"
    assert stylesheet in site_layout
    assert stylesheet in backoffice_layout
    assert "overflow-y: scroll" in css
    assert "scrollbar-gutter: stable" in css
    assert "html::-webkit-scrollbar-thumb" in css
    assert "#9b3842" in css


def test_store_binding_get_does_not_wait_for_live_discord_roles():
    router = _read("web/app/routers/store_bindings.py")

    assert "def _can_manage_session" in router
    page_block = router.split('@router.get("/employee/store-bindings")', 1)[1].split(
        '@router.post("/employee/store-bindings/grant")', 1
    )[0]
    assert "_can_manage_session(user)" in page_block
    assert "_can_manage(user)" not in page_block

    mutation_block = router.split('@router.post("/employee/store-bindings/grant")', 1)[1]
    assert "_can_manage(user)" in mutation_block


def test_internal_transfer_get_uses_session_but_mutations_revalidate_live_roles():
    router = _read("web/app/routers/internal_transfers.py")

    assert "def _session_employee_user" in router
    get_block = router.split('@router.get("/employee/internal-transfers")', 1)[1].split(
        '@router.post("/employee/internal-transfers")', 1
    )[0]
    assert "_session_employee_user(request)" in get_block
    assert "await _refresh_employee_user(request)" not in get_block

    post_block = router.split('@router.post("/employee/internal-transfers")', 1)[1]
    assert "await _refresh_employee_user(request)" in post_block
