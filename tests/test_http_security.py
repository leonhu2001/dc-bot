from __future__ import annotations

from types import SimpleNamespace

from web.app.services.http_security import (
    csrf_source_allowed,
    is_admin_path,
    is_manager_only_admin_path,
    origin_from_referer,
    revoke_staff_access,
    safe_csv_cell,
)


def _request(method: str, **headers):
    return SimpleNamespace(
        method=method,
        headers=headers,
    )


def test_csrf_source_allows_safe_methods_and_same_origin_writes():
    allowed = ["https://mowan.example"]

    assert csrf_source_allowed(
        _request("GET"),
        allowed_origins=allowed,
    )
    assert csrf_source_allowed(
        _request("POST", origin="https://mowan.example"),
        allowed_origins=allowed,
    )
    assert csrf_source_allowed(
        _request("POST", referer="https://mowan.example/order?id=1"),
        allowed_origins=allowed,
    )


def test_csrf_source_rejects_cross_site_or_unidentified_writes():
    allowed = ["https://mowan.example"]

    assert not csrf_source_allowed(
        _request(
            "POST",
            origin="https://evil.example",
            **{"sec-fetch-site": "cross-site"},
        ),
        allowed_origins=allowed,
    )
    assert not csrf_source_allowed(
        _request("POST"),
        allowed_origins=allowed,
    )


def test_http_security_path_policies_remain_explicit():
    assert is_admin_path("/admin")
    assert is_admin_path("/admin/orders/1")
    assert not is_admin_path("/me")

    assert is_manager_only_admin_path("/admin/wallets/123")
    assert is_manager_only_admin_path("/admin/order-rules")
    assert not is_manager_only_admin_path("/admin/search")


def test_referer_origin_normalization_is_fail_closed():
    assert origin_from_referer("https://mowan.example/path?q=1") == "https://mowan.example"
    assert origin_from_referer("javascript:alert(1)") == ""
    assert origin_from_referer("") == ""


def test_csv_cells_that_can_execute_in_spreadsheets_are_neutralized():
    assert safe_csv_cell("normal") == "normal"
    assert safe_csv_cell("=1+1") == "'=1+1"
    assert safe_csv_cell("  +SUM(A1:A2)") == "'  +SUM(A1:A2)"
    assert safe_csv_cell("\t=1+1") == "'\t=1+1"


def test_revoke_staff_access_clears_all_operational_privileges():
    user = {
        "role_ids": ["1"],
        "is_manager": True,
        "is_admin": True,
        "is_customer_service": True,
        "is_worker": True,
        "is_companion": True,
        "is_employee": True,
        "id": "123",
    }

    result = revoke_staff_access(user)

    assert result["id"] == "123"
    assert result["role_ids"] == []
    for key in (
        "is_manager",
        "is_admin",
        "is_customer_service",
        "is_worker",
        "is_companion",
        "is_employee",
    ):
        assert result[key] is False
