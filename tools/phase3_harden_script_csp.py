from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"
STATIC = ROOT / "web" / "app" / "static"
VERSION = "20261013"

INLINE_SCRIPT_OPEN_RE = re.compile(
    r"<script(?![^>]*\bsrc\s*=)(?![^>]*\bnonce\s*=)(?P<attrs>[^>]*)>",
    re.I,
)
CONFIRM_HANDLER_RE = re.compile(
    r'''\s+onsubmit="return\s+confirm\('(.*?)'\);"''',
    re.I | re.S,
)


def harden_template(path: Path) -> bool:
    source = path.read_text(encoding="utf-8-sig")
    before = source

    # Keep dynamic text as data; executable behavior lives in csp_handlers.js.
    source = CONFIRM_HANDLER_RE.sub(
        lambda match: f' data-confirm-message="{match.group(1)}"',
        source,
    )

    source = source.replace(
        " onerror=\"this.onerror=null;this.src='/static/img/server_logo.gif';\"",
        ' data-fallback-src="/static/img/server_logo.gif"',
    )
    source = source.replace(
        " onerror=\"this.onerror=null;this.src='/static/img/server_logo.gif';this.classList.add('avatar-fallback');\"",
        ' data-fallback-src="/static/img/server_logo.gif" data-fallback-class="avatar-fallback"',
    )
    source = source.replace(
        " onerror='this.parentElement.remove();'",
        ' data-remove-parent-on-error="true"',
    )
    source = source.replace(
        ' onerror="this.parentElement.remove();"',
        ' data-remove-parent-on-error="true"',
    )

    # Nonces are only needed for the seven remaining dynamic/data inline scripts.
    source = INLINE_SCRIPT_OPEN_RE.sub(
        lambda match: '<script nonce="{{ request.state.csp_nonce }}"' + match.group("attrs") + '>',
        source,
    )

    if source != before:
        path.write_text(source, encoding="utf-8")
        return True
    return False


def ensure_handler_asset() -> None:
    target = STATIC / "js" / "csp_handlers.js"
    target.write_text(
        """(() => {
    "use strict";

    document.addEventListener("submit", (event) => {
        const form = event.target instanceof HTMLFormElement
            ? event.target
            : null;
        if (!form) return;
        const message = String(form.dataset.confirmMessage || "").trim();
        if (message && !window.confirm(message)) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }
    }, true);

    document.addEventListener("error", (event) => {
        const image = event.target instanceof HTMLImageElement
            ? event.target
            : null;
        if (!image) return;

        if (image.dataset.removeParentOnError === "true") {
            image.parentElement?.remove();
            return;
        }

        const fallbackSrc = String(image.dataset.fallbackSrc || "").trim();
        if (!fallbackSrc || image.dataset.fallbackApplied === "true") return;
        image.dataset.fallbackApplied = "true";
        const fallbackClass = String(image.dataset.fallbackClass || "").trim();
        if (fallbackClass) image.classList.add(fallbackClass);
        image.src = fallbackSrc;
    }, true);
})();
""",
        encoding="utf-8",
    )


def ensure_base_loader(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    marker = f'/static/js/csp_handlers.js?v={VERSION}'
    if marker in source:
        return
    tag = f'    <script src="{marker}"></script>\n'
    if "</head>" not in source:
        raise RuntimeError(f"missing </head> in {path}")
    source = source.replace("</head>", tag + "</head>", 1)
    path.write_text(source, encoding="utf-8")


def harden_http_security() -> None:
    path = ROOT / "web" / "app" / "services" / "http_security.py"
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        "import csv\nimport io\n",
        "import base64\nimport csv\nimport io\nimport secrets\n",
        1,
    )
    old = '''# Legacy templates still contain inline style/script. Keep unsafe-inline until\n# the audited debt reaches zero, while locking down the other high-risk sources.\nCONTENT_SECURITY_POLICY = "; ".join(\n    (\n        "default-src 'self'",\n        "base-uri 'self'",\n        "object-src 'none'",\n        "frame-ancestors 'none'",\n        "form-action 'self'",\n        "script-src 'self' 'unsafe-inline'",\n        "style-src 'self' 'unsafe-inline'",\n        "img-src 'self' data: https:",\n        "font-src 'self' data:",\n        "connect-src 'self'",\n        "upgrade-insecure-requests",\n    )\n)\n'''
    new = '''def new_csp_nonce() -> str:\n    return base64.b64encode(secrets.token_bytes(18)).decode("ascii")\n\n\ndef build_content_security_policy(nonce: str) -> str:\n    safe_nonce = str(nonce or "").strip()\n    if not safe_nonce:\n        raise ValueError("CSP nonce is required")\n\n    # Executable inline JavaScript is nonce-bound. style-src keeps unsafe-inline\n    # temporarily only for audited legacy style attributes; <style> blocks are gone.\n    return "; ".join(\n        (\n            "default-src 'self'",\n            "base-uri 'self'",\n            "object-src 'none'",\n            "frame-ancestors 'none'",\n            "form-action 'self'",\n            f"script-src 'self' 'nonce-{safe_nonce}'",\n            "style-src 'self' 'unsafe-inline'",\n            "img-src 'self' data: https:",\n            "font-src 'self' data:",\n            "connect-src 'self'",\n            "upgrade-insecure-requests",\n        )\n    )\n'''
    if old not in source:
        raise RuntimeError("http_security CSP block changed unexpectedly")
    source = source.replace(old, new, 1)
    path.write_text(source, encoding="utf-8")


def harden_main() -> None:
    path = ROOT / "web" / "app" / "main.py"
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        "    CONTENT_SECURITY_POLICY,\n    apply_live_access,\n",
        "    apply_live_access,\n    build_content_security_policy,\n",
        1,
    )
    source = source.replace(
        "    is_manager_only_admin_path,\n    revoke_staff_access,\n",
        "    is_manager_only_admin_path,\n    new_csp_nonce,\n    revoke_staff_access,\n",
        1,
    )
    anchor = '''async def security_and_refresh_access(request: Request, call_next):\n    allowed, retry_after = rate_limit_allowed(request)\n'''
    replacement = '''async def security_and_refresh_access(request: Request, call_next):\n    csp_nonce = new_csp_nonce()\n    request.state.csp_nonce = csp_nonce\n\n    allowed, retry_after = rate_limit_allowed(request)\n'''
    if anchor not in source:
        raise RuntimeError("security middleware anchor changed unexpectedly")
    source = source.replace(anchor, replacement, 1)
    source = source.replace(
        'response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)',
        'response.headers.setdefault(\n        "Content-Security-Policy",\n        build_content_security_policy(csp_nonce),\n    )',
        1,
    )
    path.write_text(source, encoding="utf-8")


def update_http_security_tests() -> None:
    path = ROOT / "tests" / "test_http_security.py"
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        "from web.app.services.http_security import (\n    csrf_source_allowed,\n",
        "from web.app.services.http_security import (\n    build_content_security_policy,\n    csrf_source_allowed,\n",
        1,
    )
    if "test_csp_uses_nonce_without_script_unsafe_inline" not in source:
        source += '''\n\ndef test_csp_uses_nonce_without_script_unsafe_inline():\n    policy = build_content_security_policy("abc123")\n    script_directive = next(\n        part.strip() for part in policy.split(";")\n        if part.strip().startswith("script-src ")\n    )\n    assert "'nonce-abc123'" in script_directive\n    assert "'unsafe-inline'" not in script_directive\n    assert "style-src 'self' 'unsafe-inline'" in policy\n'''
    path.write_text(source, encoding="utf-8")


def update_template_audit() -> None:
    path = ROOT / "tools" / "audit_templates.py"
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        "MAX_INLINE_SCRIPT_BLOCKS = 7\n",
        "MAX_INLINE_SCRIPT_BLOCKS = 7\nMAX_INLINE_STYLE_ATTRIBUTES = 107\nMAX_INLINE_EVENT_ATTRIBUTES = 0\n",
        1,
    )
    source = source.replace(
        'INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\\bsrc\\s*=)[^>]*>", re.IGNORECASE)\n',
        'INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\\bsrc\\s*=)[^>]*>", re.IGNORECASE)\n'
        'INLINE_SCRIPT_WITHOUT_NONCE_RE = re.compile(\n'
        '    r"<script(?![^>]*\\bsrc\\s*=)(?![^>]*\\bnonce\\s*=)[^>]*>",\n'
        '    re.IGNORECASE,\n'
        ')\n'
        'INLINE_STYLE_ATTRIBUTE_RE = re.compile(r"\\sstyle\\s*=", re.IGNORECASE)\n'
        'INLINE_EVENT_ATTRIBUTE_RE = re.compile(r"\\son[a-z0-9_-]+\\s*=", re.IGNORECASE)\n',
        1,
    )
    source = source.replace(
        "    inline_script_count = 0\n    static_references: set[str] = set()\n",
        "    inline_script_count = 0\n    inline_script_without_nonce_count = 0\n    inline_style_attribute_count = 0\n    inline_event_attribute_count = 0\n    static_references: set[str] = set()\n",
        1,
    )
    source = source.replace(
        "        inline_script_count += len(INLINE_SCRIPT_RE.findall(source))\n        static_references.update(STATIC_REF_RE.findall(source))\n",
        "        inline_script_count += len(INLINE_SCRIPT_RE.findall(source))\n        inline_script_without_nonce_count += len(INLINE_SCRIPT_WITHOUT_NONCE_RE.findall(source))\n        inline_style_attribute_count += len(INLINE_STYLE_ATTRIBUTE_RE.findall(source))\n        inline_event_attribute_count += len(INLINE_EVENT_ATTRIBUTE_RE.findall(source))\n        static_references.update(STATIC_REF_RE.findall(source))\n",
        1,
    )
    source = source.replace(
        '    print("MAX_INLINE_SCRIPT_BLOCKS:", MAX_INLINE_SCRIPT_BLOCKS)\n',
        '    print("MAX_INLINE_SCRIPT_BLOCKS:", MAX_INLINE_SCRIPT_BLOCKS)\n'
        '    print("INLINE_SCRIPT_WITHOUT_NONCE:", inline_script_without_nonce_count)\n'
        '    print("INLINE_STYLE_ATTRIBUTES:", inline_style_attribute_count)\n'
        '    print("MAX_INLINE_STYLE_ATTRIBUTES:", MAX_INLINE_STYLE_ATTRIBUTES)\n'
        '    print("INLINE_EVENT_ATTRIBUTES:", inline_event_attribute_count)\n'
        '    print("MAX_INLINE_EVENT_ATTRIBUTES:", MAX_INLINE_EVENT_ATTRIBUTES)\n',
        1,
    )
    anchor = '''    if inline_script_count > MAX_INLINE_SCRIPT_BLOCKS:\n        errors.append(\n            "inline script debt increased: "\n            f"{inline_script_count} > {MAX_INLINE_SCRIPT_BLOCKS}"\n        )\n\n'''
    extra = '''    if inline_script_count > MAX_INLINE_SCRIPT_BLOCKS:\n        errors.append(\n            "inline script debt increased: "\n            f"{inline_script_count} > {MAX_INLINE_SCRIPT_BLOCKS}"\n        )\n    if inline_script_without_nonce_count:\n        errors.append(\n            f"inline script without CSP nonce: {inline_script_without_nonce_count}"\n        )\n    if inline_style_attribute_count > MAX_INLINE_STYLE_ATTRIBUTES:\n        errors.append(\n            "inline style attribute debt increased: "\n            f"{inline_style_attribute_count} > {MAX_INLINE_STYLE_ATTRIBUTES}"\n        )\n    if inline_event_attribute_count > MAX_INLINE_EVENT_ATTRIBUTES:\n        errors.append(\n            "inline event handler debt increased: "\n            f"{inline_event_attribute_count} > {MAX_INLINE_EVENT_ATTRIBUTES}"\n        )\n\n'''
    if anchor not in source:
        raise RuntimeError("template audit debt anchor changed unexpectedly")
    source = source.replace(anchor, extra, 1)
    path.write_text(source, encoding="utf-8")


def main() -> None:
    ensure_handler_asset()
    touched = 0
    for path in sorted(TEMPLATES.rglob("*.html")):
        touched += int(harden_template(path))
    ensure_base_loader(TEMPLATES / "layout.html")
    ensure_base_loader(TEMPLATES / "site_layout.html")
    harden_http_security()
    harden_main()
    update_http_security_tests()
    update_template_audit()

    remaining_events = sum(
        len(re.findall(r"\son[a-z0-9_-]+\s*=", path.read_text(encoding="utf-8"), re.I))
        for path in TEMPLATES.rglob("*.html")
    )
    print(f"templates_touched={touched}")
    print(f"remaining_event_handlers={remaining_events}")
    if remaining_events:
        raise SystemExit("inline event handlers remain")


if __name__ == "__main__":
    main()
