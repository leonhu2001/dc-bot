import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SEMANTIC_ASSETS = {
    "web/app/static/js/pages/admin_order_detail_operations.js": "f4f6b62d9ee0437a49a706d092eb8a36182723f0",
    "web/app/static/js/pages/admin_order_detail_finance.js": "ba3efec638dc2c8d60a0e1fc074db9a362525d38",
    "web/app/static/js/pages/admin_order_rules.js": "903e15b49c96011440ede296fbfaffdc421ad26e",
    "web/app/static/css/pages/admin_order_rules.css": "d5da5bc39c354c2cbfbcd57eb633185222014fc4",
    "web/app/static/js/pages/admin_dashboard.js": "9e001f4200aeaf542dbd0ac2086238aac632b2a9",
}

LEGACY_ASSETS = (
    "web/app/static/js/pages/admin_order_detail_inline_1.js",
    "web/app/static/js/pages/admin_order_detail_inline_2.js",
    "web/app/static/js/pages/admin_order_rules_inline_1.js",
    "web/app/static/css/pages/admin_order_rules_inline_1.css",
    "web/app/static/js/pages/admin_inline_1.js",
)


def _git_blob_sha(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data).hexdigest()


def test_semantic_assets_preserve_exact_legacy_blob_contents():
    for relative_path, expected_sha in SEMANTIC_ASSETS.items():
        data = (ROOT / relative_path).read_bytes()
        assert _git_blob_sha(data) == expected_sha, relative_path


def test_legacy_inline_named_assets_are_fully_retired():
    for relative_path in LEGACY_ASSETS:
        assert not (ROOT / relative_path).exists(), relative_path


def test_templates_reference_only_semantic_asset_names():
    order_detail = (ROOT / "web/app/templates/admin_order_detail.html").read_text(encoding="utf-8")
    order_rules = (ROOT / "web/app/templates/admin_order_rules.html").read_text(encoding="utf-8")
    admin = (ROOT / "web/app/templates/admin.html").read_text(encoding="utf-8")

    assert "admin_order_detail_operations.js" in order_detail
    assert "admin_order_detail_finance.js" in order_detail
    assert "admin_order_rules.css" in order_rules
    assert "admin_order_rules.js" in order_rules
    assert "admin_dashboard.js" in admin

    combined = "\n".join((order_detail, order_rules, admin))
    for legacy_path in LEGACY_ASSETS:
        assert Path(legacy_path).name not in combined


def test_inline_named_page_asset_allowance_is_zero():
    audit = (ROOT / "tools/audit_templates.py").read_text(encoding="utf-8")
    assert "MAX_INLINE_NAMED_PAGE_ASSETS = 0" in audit
