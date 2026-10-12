from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

security_path = ROOT / "web/app/services/http_security.py"
security = security_path.read_text(encoding="utf-8")
old_policy = '''# Legacy templates still contain inline style/script. Keep unsafe-inline until
# the audited debt reaches zero, while locking down the other high-risk sources.
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: https:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "upgrade-insecure-requests",
    )
)
'''
new_policy = '''def build_content_security_policy(nonce: str) -> str:
    nonce_value = str(nonce or "").strip()
    script_src = "script-src 'self'"
    if nonce_value:
        script_src += f" 'nonce-{nonce_value}'"

    return "; ".join(
        (
            "default-src 'self'",
            "base-uri 'self'",
            "object-src 'none'",
            "frame-ancestors 'none'",
            "form-action 'self'",
            script_src,
            "script-src-attr 'none'",
            "style-src 'self'",
            "style-src-elem 'self'",
            # A small number of legacy/dynamic style attributes still exist.
            # Keep this scoped to attributes instead of allowing inline <style>.
            "style-src-attr 'unsafe-inline'",
            "img-src 'self' data: https:",
            "font-src 'self' data:",
            "connect-src 'self'",
            "upgrade-insecure-requests",
        )
    )
'''
if old_policy not in security:
    raise RuntimeError("expected CSP policy block not found")
security_path.write_text(security.replace(old_policy, new_policy), encoding="utf-8")

main_path = ROOT / "web/app/main.py"
main = main_path.read_text(encoding="utf-8")
if "import secrets\n" not in main:
    main = main.replace("from pathlib import Path\n", "from pathlib import Path\nimport secrets\n", 1)
main = main.replace(
    "    CONTENT_SECURITY_POLICY,\n",
    "    build_content_security_policy,\n",
    1,
)
needle = '''async def security_and_refresh_access(request: Request, call_next):
    allowed, retry_after = rate_limit_allowed(request)
'''
replacement = '''async def security_and_refresh_access(request: Request, call_next):
    csp_nonce = secrets.token_urlsafe(24)
    request.state.csp_nonce = csp_nonce

    allowed, retry_after = rate_limit_allowed(request)
'''
if needle not in main:
    raise RuntimeError("security middleware start not found")
main = main.replace(needle, replacement, 1)
old_header = '    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)\n'
new_header = '    response.headers.setdefault("Content-Security-Policy", build_content_security_policy(csp_nonce))\n'
if old_header not in main:
    raise RuntimeError("CSP response header line not found")
main = main.replace(old_header, new_header, 1)
main_path.write_text(main, encoding="utf-8")

templates = ROOT / "web/app/templates"
inline_tag = re.compile(r"<script(?![^>]*\bsrc\s*=)(?P<attrs>[^>]*)>", re.I)
updated_scripts = 0
for path in sorted(templates.glob("*.html")):
    text = path.read_text(encoding="utf-8")

    def add_nonce(match: re.Match[str]) -> str:
        global updated_scripts
        attrs = match.group("attrs") or ""
        if re.search(r"\bnonce\s*=", attrs, re.I):
            return match.group(0)
        updated_scripts += 1
        return '<script nonce="{{ request.state.csp_nonce }}"' + attrs + '>'

    text = inline_tag.sub(add_nonce, text)
    path.write_text(text, encoding="utf-8")

if updated_scripts != 7:
    raise RuntimeError(f"expected to nonce 7 dynamic scripts, got {updated_scripts}")

audit_path = ROOT / "tools/audit_templates.py"
audit = audit_path.read_text(encoding="utf-8")
audit = audit.replace("MAX_INLINE_STYLE_BLOCKS = 26", "MAX_INLINE_STYLE_BLOCKS = 0")
audit = audit.replace("MAX_INLINE_SCRIPT_BLOCKS = 19", "MAX_INLINE_SCRIPT_BLOCKS = 7")
marker = '''    if inline_script_count > MAX_INLINE_SCRIPT_BLOCKS:
        errors.append(
            "inline script debt increased: "
            f"{inline_script_count} > {MAX_INLINE_SCRIPT_BLOCKS}"
        )
'''
addition = marker + '''
    inline_script_tag_re = re.compile(
        r"<script(?![^>]*\\bsrc\\s*=)(?P<attrs>[^>]*)>",
        re.IGNORECASE,
    )
    missing_nonce = []
    for template_path in template_files:
        source = template_path.read_text(encoding="utf-8-sig")
        for match in inline_script_tag_re.finditer(source):
            if not re.search(r"\\bnonce\\s*=", match.group("attrs") or "", re.IGNORECASE):
                missing_nonce.append(template_path.name)
    if missing_nonce:
        errors.append(
            "inline executable scripts missing CSP nonce: "
            + ", ".join(sorted(set(missing_nonce)))
        )
'''
if marker not in audit:
    raise RuntimeError("audit CSP marker not found")
audit_path.write_text(audit.replace(marker, addition, 1), encoding="utf-8")

test_path = ROOT / "tests/test_http_security.py"
test = test_path.read_text(encoding="utf-8")
test = test.replace(
    "from web.app.services.http_security import (\n",
    "from web.app.services.http_security import (\n    build_content_security_policy,\n",
    1,
)
if "def test_csp_nonce_policy_rejects_unsafe_inline_scripts" not in test:
    test += '''\n\ndef test_csp_nonce_policy_rejects_unsafe_inline_scripts():\n    policy = build_content_security_policy("abc123")\n\n    assert "script-src 'self' 'nonce-abc123'" in policy\n    assert "script-src-attr 'none'" in policy\n    assert "style-src-elem 'self'" in policy\n    assert "style-src-attr 'unsafe-inline'" in policy\n    assert "script-src 'self' 'unsafe-inline'" not in policy\n    assert "style-src 'self' 'unsafe-inline'" not in policy\n'''
test_path.write_text(test, encoding="utf-8")

print(f"nonced inline dynamic scripts: {updated_scripts}")
