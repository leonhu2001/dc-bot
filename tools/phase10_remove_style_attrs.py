from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"
STATIC_CSS = ROOT / "web" / "app" / "static" / "css"
STATIC_JS = ROOT / "web" / "app" / "static" / "js"
HTTP_SECURITY = ROOT / "web" / "app" / "services" / "http_security.py"
AUDIT = ROOT / "tools" / "audit_templates.py"
TEST = ROOT / "tests" / "test_csp_style_attr_lockdown.py"

TAG_RE = re.compile(r"<(?!/|!|\?)(?P<body>[A-Za-z][^<>]*?)>", re.S)
STYLE_RE = re.compile(r"\s+style\s*=\s*([\"'])(?P<value>.*?)\1", re.I | re.S)
CLASS_RE = re.compile(r"\bclass\s*=\s*([\"'])(?P<value>.*?)\1", re.I | re.S)
JINJA_RE = re.compile(r"{{|{%")
WIDTH_DYNAMIC_RE = re.compile(r"^width\s*:\s*{{\s*(?P<expr>.*?)\s*}}\s*%\s*;?$", re.S)
SHARE_DYNAMIC_RE = re.compile(r"^--share\s*:\s*{{\s*(?P<expr>.*?)\s*}}\s*%\s*;?$", re.S)


def css_class_for(declaration: str) -> str:
    digest = hashlib.sha1(declaration.encode("utf-8")).hexdigest()[:10]
    return f"csp-sa-{digest}"


def add_class(tag: str, class_name: str) -> str:
    match = CLASS_RE.search(tag)
    if match:
        current = match.group("value")
        if class_name in current.split():
            return tag
        replacement = f'class="{current} {class_name}"'
        return tag[: match.start()] + replacement + tag[match.end() :]

    name_match = re.match(r"<([A-Za-z][\w:-]*)", tag)
    if not name_match:
        raise RuntimeError(f"unable to add class to tag: {tag[:100]}")
    insert_at = name_match.end()
    return tag[:insert_at] + f' class="{class_name}"' + tag[insert_at:]


def migrate_tag(tag: str, styles: dict[str, str]) -> str:
    while True:
        match = STYLE_RE.search(tag)
        if not match:
            return tag

        raw = match.group("value").strip()
        if JINJA_RE.search(raw):
            width = WIDTH_DYNAMIC_RE.fullmatch(raw)
            share = SHARE_DYNAMIC_RE.fullmatch(raw)
            if width:
                replacement = f' data-csp-width-percent="{{{{ {width.group("expr").strip()} }}}}"'
                tag = tag[: match.start()] + replacement + tag[match.end() :]
                continue
            if share:
                replacement = f' data-csp-share-percent="{{{{ {share.group("expr").strip()} }}}}"'
                tag = tag[: match.start()] + replacement + tag[match.end() :]
                continue
            raise RuntimeError(f"unsupported dynamic style attribute: {raw}")

        declaration = raw
        if declaration and not declaration.endswith(";"):
            declaration += ";"
        class_name = css_class_for(declaration)
        styles[class_name] = declaration
        tag = tag[: match.start()] + tag[match.end() :]
        tag = add_class(tag, class_name)


def migrate_templates() -> dict[str, str]:
    styles: dict[str, str] = {}
    for path in sorted(TEMPLATES.rglob("*.html")):
        source = path.read_text(encoding="utf-8")
        migrated = TAG_RE.sub(lambda match: migrate_tag(match.group(0), styles), source)
        path.write_text(migrated, encoding="utf-8")
    return styles


def write_css(styles: dict[str, str]) -> None:
    lines = [
        "/* Generated from retired template style attributes. Keep class-based so CSP can disallow style attributes. */",
    ]
    for class_name, declaration in sorted(styles.items()):
        lines.append(f".{class_name}{{{declaration}}}")
    lines.append("")
    (STATIC_CSS / "csp_style_attrs.css").write_text("\n".join(lines), encoding="utf-8")


def write_dynamic_js() -> None:
    (STATIC_JS / "csp_dynamic_styles.js").write_text(
        '''(() => {
    "use strict";

    const percent = (value) => {
        const number = Number(value);
        if (!Number.isFinite(number)) return 0;
        return Math.max(0, Math.min(100, number));
    };

    document.querySelectorAll("[data-csp-width-percent]").forEach((element) => {
        element.style.width = `${percent(element.dataset.cspWidthPercent)}%`;
    });

    document.querySelectorAll("[data-csp-share-percent]").forEach((element) => {
        element.style.setProperty("--share", `${percent(element.dataset.cspSharePercent)}%`);
    });
})();
''',
        encoding="utf-8",
    )


def add_assets_to_layout(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "/static/css/csp_style_attrs.css" not in text:
        marker = "{% block head %}{% endblock %}" if path.name == "site_layout.html" else "<!-- MAWAN_PORTAL_UNIFIED_20260903_V1 -->"
        assets = '''<link rel="stylesheet" href="/static/css/csp_style_attrs.css?v=20261013">
<script src="/static/js/csp_dynamic_styles.js?v=20261013" defer></script>

'''
        if marker not in text:
            raise RuntimeError(f"layout insertion marker missing: {path}")
        text = text.replace(marker, assets + marker, 1)
        path.write_text(text, encoding="utf-8")


def lock_csp() -> None:
    text = HTTP_SECURITY.read_text(encoding="utf-8")
    old = '''            # A small number of legacy/dynamic style attributes still exist.
            # Keep this scoped to attributes instead of allowing inline <style>.
            "style-src-attr 'unsafe-inline'",
'''
    new = '''            "style-src-attr 'none'",
'''
    if old not in text:
        raise RuntimeError("style-src-attr legacy CSP marker missing")
    HTTP_SECURITY.write_text(text.replace(old, new, 1), encoding="utf-8")


def strengthen_audit() -> None:
    text = AUDIT.read_text(encoding="utf-8")
    text = text.replace(
        "# Debt budget after the 2026-10-13 public-layout extraction. The project still\n# needs CSP unsafe-inline on legacy pages, but new changes may only reduce these\n# counts, never increase them.\n",
        "# CSP debt is shrink-only. Style blocks and style attributes are fully retired;\n# the remaining inline scripts must carry a per-request nonce.\n",
        1,
    )
    if "STYLE_ATTR_RE =" not in text:
        text = text.replace(
            'INLINE_STYLE_RE = re.compile(r"<style(?:\\s|>)", re.IGNORECASE)\n',
            'INLINE_STYLE_RE = re.compile(r"<style(?:\\s|>)", re.IGNORECASE)\nSTYLE_ATTR_RE = re.compile(r"\\bstyle\\s*=", re.IGNORECASE)\n',
            1,
        )
        text = text.replace(
            "    inline_style_count = 0\n    inline_script_count = 0\n",
            "    inline_style_count = 0\n    inline_style_attr_count = 0\n    inline_script_count = 0\n",
            1,
        )
        text = text.replace(
            "        inline_style_count += len(INLINE_STYLE_RE.findall(source))\n        inline_script_count += len(INLINE_SCRIPT_RE.findall(source))\n",
            "        inline_style_count += len(INLINE_STYLE_RE.findall(source))\n        inline_style_attr_count += len(STYLE_ATTR_RE.findall(source))\n        inline_script_count += len(INLINE_SCRIPT_RE.findall(source))\n",
            1,
        )
        text = text.replace(
            '    print("INLINE_STYLE_BLOCKS:", inline_style_count)\n',
            '    print("INLINE_STYLE_BLOCKS:", inline_style_count)\n    print("INLINE_STYLE_ATTRIBUTES:", inline_style_attr_count)\n',
            1,
        )
        text = text.replace(
            "    if inline_style_count > MAX_INLINE_STYLE_BLOCKS:\n",
            "    if inline_style_attr_count:\n        errors.append(\n            f\"inline style attributes are forbidden: {inline_style_attr_count}\"\n        )\n    if inline_style_count > MAX_INLINE_STYLE_BLOCKS:\n",
            1,
        )
    AUDIT.write_text(text, encoding="utf-8")


def write_test() -> None:
    TEST.write_text(
        '''from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"


def test_templates_do_not_use_style_attributes():
    offenders = []
    pattern = re.compile(r"\\bstyle\\s*=", re.IGNORECASE)
    for path in TEMPLATES.rglob("*.html"):
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_csp_disallows_style_attributes_and_assets_are_external():
    security = (ROOT / "web/app/services/http_security.py").read_text(encoding="utf-8")
    assert "style-src-attr 'none'" in security
    assert "style-src-attr 'unsafe-inline'" not in security

    for layout_name in ("layout.html", "site_layout.html"):
        layout = (TEMPLATES / layout_name).read_text(encoding="utf-8")
        assert "/static/css/csp_style_attrs.css" in layout
        assert "/static/js/csp_dynamic_styles.js" in layout


def test_dynamic_style_bridge_uses_csp_safe_property_updates():
    source = (ROOT / "web/app/static/js/csp_dynamic_styles.js").read_text(encoding="utf-8")
    assert ".style.width" in source
    assert '.style.setProperty("--share"' in source
    assert "style.cssText" not in source
    assert 'setAttribute("style"' not in source
''',
        encoding="utf-8",
    )


def cleanup_scaffolding() -> None:
    for relative in (
        "tools/phase10_style_attr_inventory.py",
        "tools/phase10_remove_style_attrs.py",
        ".github/workflows/phase10-style-attr-inventory.yml",
        ".github/workflows/phase10-style-attrs.yml",
    ):
        (ROOT / relative).unlink(missing_ok=True)


def main() -> None:
    styles = migrate_templates()
    write_css(styles)
    write_dynamic_js()
    add_assets_to_layout(TEMPLATES / "layout.html")
    add_assets_to_layout(TEMPLATES / "site_layout.html")
    lock_csp()
    strengthen_audit()
    write_test()
    cleanup_scaffolding()

    remaining = []
    for path in TEMPLATES.rglob("*.html"):
        if re.search(r"\bstyle\s*=", path.read_text(encoding="utf-8"), re.I):
            remaining.append(str(path.relative_to(ROOT)))
    if remaining:
        raise RuntimeError(f"style attributes remain: {remaining}")
    print(f"generated_static_style_classes={len(styles)}")


if __name__ == "__main__":
    main()
