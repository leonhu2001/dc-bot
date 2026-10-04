from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, inspect as sa_inspect

from services import order_credentials
from web.app.routers.auth import _safe_return_path
from web.app.services.customer_portal import get_customer_order
from web.app.services.web_security import (
    csrf_token_from_request_parts,
    csrf_tokens_match,
    ensure_csrf_token,
    has_recent_auth,
    is_sensitive_path,
    mark_authenticated_now,
    rotate_csrf_token,
    should_no_store,
)


def test_csrf_token_lifecycle_and_constant_time_match():
    session = {}

    first = ensure_csrf_token(session)
    assert len(first) >= 32
    assert csrf_tokens_match(first, first)
    assert not csrf_tokens_match(first, "wrong-token")
    assert not csrf_tokens_match(first, None)

    second = rotate_csrf_token(session)
    assert second != first
    assert csrf_tokens_match(second, session["csrf_token"])


def test_csrf_token_extracts_urlencoded_multipart_and_header():
    token = "abc123-secure-token"

    assert csrf_token_from_request_parts(
        header_token=token,
        body=b"",
        content_type="application/x-www-form-urlencoded",
    ) == token

    assert csrf_token_from_request_parts(
        header_token=None,
        body=b"amount=500&csrf_token=abc123-secure-token",
        content_type="application/x-www-form-urlencoded",
    ) == token

    multipart = (
        b"--boundary\r\n"
        b'Content-Disposition: form-data; name="csrf_token"\r\n'
        b"\r\n"
        b"abc123-secure-token\r\n"
        b"--boundary--\r\n"
    )

    assert csrf_token_from_request_parts(
        header_token=None,
        body=multipart,
        content_type="multipart/form-data; boundary=boundary",
    ) == token


def test_recent_auth_window_and_sensitive_path_detection():
    session = {}
    mark_authenticated_now(session, now=1000.0)

    assert has_recent_auth(
        session,
        max_age_seconds=1800,
        now=2799.0,
    )
    assert not has_recent_auth(
        session,
        max_age_seconds=1800,
        now=2801.0,
    )

    assert is_sensitive_path("/admin/wallets/123")
    assert is_sensitive_path("/admin/payment-reviews/1/approve")
    assert is_sensitive_path("/admin/accounting-reconciliation/repair")
    assert not is_sensitive_path("/admin/search")
    assert not is_sensitive_path("/me/orders")


def test_authenticated_sensitive_pages_are_never_cacheable():
    assert should_no_store("/admin/wallets/123", authenticated=True)
    assert should_no_store("/me/orders", authenticated=True)
    assert should_no_store("/dispatch", authenticated=True)
    assert not should_no_store("/", authenticated=True)
    assert not should_no_store("/admin", authenticated=False)


def test_order_workspace_template_injects_csrf_for_all_post_forms():
    template = Path("web/app/templates/admin_order_detail.html").read_text(
        encoding="utf-8"
    )

    meta = 'name="csrf-token"'
    script = 'src="/static/js/csrf.js?v=1"'

    assert meta in template
    assert script in template
    assert template.index(meta) < template.index(script)

    assert (
        '/admin/order-workspace/{{ order.id }}/acceptance/'
        '{{ claim.staff_discord_id }}/remove'
    ) in template


def test_all_unsafe_html_forms_include_explicit_csrf_token():
    form_pattern = re.compile(
        r"<form\b[^>]*\bmethod\s*=\s*[\"']?"
        r"(?:post|put|patch|delete)[\"']?[^>]*>",
        re.IGNORECASE,
    )
    csrf_pattern = re.compile(
        r"name\s*=\s*[\"']csrf_token[\"']",
        re.IGNORECASE,
    )

    template_dir = Path("web/app/templates")
    missing = []

    for template_path in sorted(template_dir.glob("*.html")):
        content = template_path.read_text(encoding="utf-8")

        for match in form_pattern.finditer(content):
            end = content.find("</form>", match.end())
            block = content[
                match.start():
                end + len("</form>") if end >= 0 else match.end() + 6000
            ]

            if not csrf_pattern.search(block):
                missing.append(
                    f"{template_path.name}: {match.group(0)[:120]}"
                )

    assert missing == []


def test_shared_layouts_load_csrf_bootstrap_before_page_scripts():
    for template_name in ("layout.html", "site_layout.html"):
        template = Path(
            "web/app/templates",
            template_name,
        ).read_text(encoding="utf-8")

        meta = 'name="csrf-token"'
        script = 'src="/static/js/csrf.js?v=1"'

        assert meta in template
        assert script in template
        assert template.index(meta) < template.index(script)


def test_staff_sync_get_route_cannot_write():
    source = Path("web/app/routers/admin_staff.py").read_text(
        encoding="utf-8"
    )
    start = source.index('@router.get("/admin/staff/sync")')
    end = source.find("\n@router.", start + 1)
    body = source[start:end if end >= 0 else None]

    assert "run_admin_staff_sync(request)" not in body
    assert "status_code=405" in body


def test_oauth_return_path_rejects_open_redirects():
    assert _safe_return_path("/me/orders") == "/me/orders"
    assert _safe_return_path("/admin?x=1") == "/admin?x=1"

    for unsafe in (
        "https://evil.example/",
        "//evil.example/",
        r"\\evil.example\share",
        "javascript:alert(1)",
        "",
    ):
        assert _safe_return_path(unsafe) == "/"


def _setup_customer_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                bot_order_no TEXT,
                ticket_channel_id TEXT,
                customer_discord_id TEXT,
                category TEXT,
                item TEXT,
                quantity INTEGER,
                amount INTEGER,
                customer_pay_amount INTEGER,
                payment_method TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            INSERT INTO web_orders (
                id,
                bot_order_no,
                ticket_channel_id,
                customer_discord_id,
                category,
                item,
                quantity,
                amount,
                customer_pay_amount,
                payment_method,
                status,
                created_at,
                updated_at
            )
            VALUES
                (
                    1,
                    'MO-OWNER-A',
                    '111',
                    'A',
                    '三角洲',
                    '護航',
                    1,
                    500,
                    500,
                    'wallet',
                    'active',
                    '2026-10-02 01:00:00',
                    '2026-10-02 01:00:00'
                ),
                (
                    2,
                    'MO-OWNER-B',
                    '222',
                    'B',
                    '英雄聯盟',
                    '陪玩',
                    1,
                    600,
                    600,
                    'wallet',
                    'active',
                    '2026-10-02 01:00:00',
                    '2026-10-02 01:00:00'
                );
            """
        )
        conn.commit()


def test_customer_order_idor_is_denied_even_when_order_id_is_known(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    _setup_customer_db(db_path)

    assert get_customer_order(
        "A",
        1,
        db_file=db_path,
    ) is not None

    assert get_customer_order(
        "A",
        2,
        db_file=db_path,
    ) is None

    assert get_customer_order(
        "B",
        1,
        db_file=db_path,
    ) is None


def test_order_credentials_store_access_metadata_but_never_secret_fields(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "credentials.db"
    test_engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )

    monkeypatch.setattr(
        order_credentials,
        "engine",
        test_engine,
    )

    order_credentials.ensure_order_credential_tables()

    columns = {
        column["name"]
        for column in sa_inspect(test_engine).get_columns(
            "order_credential_deliveries"
        )
    }

    forbidden = {
        "account",
        "username",
        "password",
        "login_password",
        "login_note",
        "credential",
        "credentials",
        "secret",
        "token",
    }

    assert not (columns & forbidden)
    assert "submitted_by_discord_id" in columns
    assert "recipient_discord_id" in columns
    assert "dm_message_id" in columns

    delivery_id = order_credentials.record_delivery(
        order_id=123,
        submitted_by_discord_id="CUSTOMER",
        recipient_discord_id="WORKER",
        recipient_type="worker",
        recipient_display_name="陪玩A",
        dm_channel_id="10",
        dm_message_id="20",
    )

    history = order_credentials.list_delivery_history(123)

    assert delivery_id > 0
    assert len(history) == 1
    assert history[0]["submitted_by_discord_id"] == "CUSTOMER"
    assert history[0]["recipient_discord_id"] == "WORKER"

    stored_text = " ".join(
        str(value or "")
        for value in history[0].values()
    ).lower()

    assert "my-password" not in stored_text
    assert "my-account" not in stored_text

def test_rate_limit_ip_supports_old_and_new_trusted_proxy_rollout():
    from web.app.main import _client_ip

    # Old Nginx config: X-Real-IP is Cloudflare's socket peer. In that case,
    # and only that case, the app may trust CF-Connecting-IP.
    old_proxy_request = SimpleNamespace(
        headers={
            "x-real-ip": "173.245.48.10",
            "cf-connecting-ip": "203.0.113.20",
        },
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert _client_ip(old_proxy_request) == "203.0.113.20"

    # Direct-origin request with a forged CF header must keep the socket peer.
    direct_request = SimpleNamespace(
        headers={
            "x-real-ip": "198.51.100.25",
            "cf-connecting-ip": "203.0.113.99",
        },
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert _client_ip(direct_request) == "198.51.100.25"

    # New Nginx config has already normalized X-Real-IP to the visitor.
    new_proxy_request = SimpleNamespace(
        headers={
            "x-real-ip": "203.0.113.30",
            "cf-connecting-ip": "203.0.113.30",
        },
        client=SimpleNamespace(host="127.0.0.1"),
    )
    assert _client_ip(new_proxy_request) == "203.0.113.30"


def test_nginx_validates_cloudflare_before_setting_real_ip():
    nginx = Path("nginx_dc_bot_dashboard.conf").read_text(encoding="utf-8")

    assert "real_ip_header CF-Connecting-IP;" in nginx
    assert "real_ip_recursive on;" in nginx
    assert "set_real_ip_from 173.245.48.0/20;" in nginx
    assert "set_real_ip_from 104.16.0.0/13;" in nginx
    assert "set_real_ip_from 2606:4700::/32;" in nginx

    # Forwarded identity sent to FastAPI is fully replaced after Nginx
    # validation; it must not append an untrusted client-supplied XFF chain.
    assert "proxy_set_header X-Real-IP $remote_addr;" in nginx
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in nginx
    assert "$proxy_add_x_forwarded_for" not in nginx

def test_order_catalog_terms_link_is_not_nested_or_duplicated():
    template = Path("web/app/templates/order_catalog.html").read_text(
        encoding="utf-8"
    )

    assert template.count('class="mw-order-notice-link"') == 1
    assert '<a class="mw-order-notice-link" href="/service-rules">' not in template
    assert (
        'aria-hidden="true" data-web-payment-hidden="1" '
        'style="display:none !important;" aria-hidden="true"'
    ) not in template

