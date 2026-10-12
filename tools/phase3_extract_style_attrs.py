from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"
STATIC = ROOT / "web" / "app" / "static"
UTILITY_CSS = STATIC / "css" / "template_utilities.css"
VERSION = "20261013"

TAG_RE = re.compile(r"<(?P<tag>[a-zA-Z][^<>]*?)>", re.S)
STYLE_ATTR_RE = re.compile(r"\sstyle\s*=\s*([\"'])(.*?)\1", re.I | re.S)
CLASS_ATTR_RE = re.compile(r"\bclass\s*=\s*([\"'])(.*?)\1", re.I | re.S)


def normalize_style(style: str) -> str:
    return ";".join(part.strip() for part in style.strip().strip(";").split(";") if part.strip())


def add_class(tag_text: str, class_name: str) -> str:
    match = CLASS_ATTR_RE.search(tag_text)
    if match:
        quote = match.group(1)
        classes = match.group(2)
        replacement = f'class={quote}{classes} {class_name}{quote}'
        return tag_text[: match.start()] + replacement + tag_text[match.end() :]

    insert_at = len(tag_text) - 1
    if tag_text.endswith("/>"):
        insert_at -= 1
    return tag_text[:insert_at] + f' class="{class_name}"' + tag_text[insert_at:]


def replace_dynamic_progress(source: str) -> str:
    source = source.replace(
        '<div class="benefit-bar"><i style="width:{{ progress.percent }}%"></i></div>',
        '<progress class="mw-native-progress mw-benefit-progress" max="100" value="{{ progress.percent }}">{{ progress.percent }}%</progress>',
    )
    source = source.replace(
        '<div class="mc-progress"><i style="width: {{ member.vip_progress.percent }}%"></i></div>',
        '<progress class="mw-native-progress mw-member-progress" max="100" value="{{ member.vip_progress.percent }}">{{ member.vip_progress.percent }}%</progress>',
    )

    source = re.sub(
        r'<div class="ops-share-track"><div class="ops-share-fill" style="--share:\{\{\s*([^}]+?)\s*\}\}%"></div></div>',
        lambda match: (
            '<progress class="mw-native-progress mw-share-progress" max="100" '
            f'value="{{{{ {match.group(1).strip()} }}}}">{{{{ {match.group(1).strip()} }}}}%</progress>'
        ),
        source,
    )
    source = re.sub(
        r'<div class="ops-share-track" style="margin-top:14px"><div class="ops-share-fill" style="--share:\{\{\s*([^}]+?)\s*\}\}%"></div></div>',
        lambda match: (
            '<progress class="mw-native-progress mw-share-progress mw-share-progress-spaced" max="100" '
            f'value="{{{{ {match.group(1).strip()} }}}}">{{{{ {match.group(1).strip()} }}}}%</progress>'
        ),
        source,
    )
    return source


def extract_static_style_attributes(source: str, rules: dict[str, str]) -> str:
    def replace_tag(match: re.Match[str]) -> str:
        tag_text = match.group(0)
        style_matches = list(STYLE_ATTR_RE.finditer(tag_text))
        if not style_matches:
            return tag_text

        result = tag_text
        for style_match in reversed(style_matches):
            raw_style = style_match.group(2)
            if "{{" in raw_style or "{%" in raw_style or "{#" in raw_style:
                continue
            normalized = normalize_style(raw_style)
            if not normalized:
                result = result[: style_match.start()] + result[style_match.end() :]
                continue
            digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
            class_name = f"mw-inline-{digest}"
            rules[class_name] = normalized
            result = result[: style_match.start()] + result[style_match.end() :]
            result = add_class(result, class_name)
        return result

    return TAG_RE.sub(replace_tag, source)


def write_utility_css(rules: dict[str, str]) -> None:
    lines = [
        "/* Canonicalized from historical template style attributes. */",
        "/* Keep this file loaded after page styles so extracted local declarations preserve intent. */",
    ]
    for class_name, declarations in sorted(rules.items()):
        lines.append(f".{class_name}{{{declarations}}}")

    lines.extend(
        [
            ".mw-native-progress{display:block;width:100%;padding:0;border:0;overflow:hidden;appearance:none;-webkit-appearance:none}",
            ".mw-native-progress::-webkit-progress-bar{background:rgba(255,255,255,.07)}",
            ".mw-native-progress::-webkit-progress-value{background:var(--r5-gold,var(--site-gold,#d6b05a))}",
            ".mw-native-progress::-moz-progress-bar{background:var(--r5-gold,var(--site-gold,#d6b05a))}",
            ".mw-benefit-progress{height:7px;margin-top:9px;border-radius:999px;background:rgba(255,255,255,.07)}",
            ".mw-member-progress{height:8px;margin-top:14px;border-radius:999px;background:rgba(255,255,255,.08)}",
            ".mw-share-progress{height:7px;margin-top:6px;border-radius:999px;background:rgba(255,255,255,.065)}",
            ".mw-share-progress-spaced{margin-top:14px}",
        ]
    )
    UTILITY_CSS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_loader(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    marker = f'/static/css/template_utilities.css?v={VERSION}'
    if marker in source:
        return
    tag = f'    <link rel="stylesheet" href="{marker}">\n'
    if "</head>" not in source:
        raise RuntimeError(f"missing </head> in {path}")
    source = source.replace("</head>", tag + "</head>", 1)
    path.write_text(source, encoding="utf-8")


def tighten_csp() -> None:
    security_path = ROOT / "web" / "app" / "services" / "http_security.py"
    source = security_path.read_text(encoding="utf-8")
    source = source.replace(
        "    # Executable inline JavaScript is nonce-bound. style-src keeps unsafe-inline\n"
        "    # temporarily only for audited legacy style attributes; <style> blocks are gone.\n",
        "    # Inline JavaScript is nonce-bound and template style attributes are eliminated.\n"
        "    # Both executable code and styles therefore load only from trusted self-hosted assets.\n",
        1,
    )
    source = source.replace(
        '            "style-src \'self\' \'unsafe-inline\'",\n',
        '            "style-src \'self\'",\n',
        1,
    )
    security_path.write_text(source, encoding="utf-8")

    test_path = ROOT / "tests" / "test_http_security.py"
    tests = test_path.read_text(encoding="utf-8")
    tests = tests.replace(
        '    assert "style-src \'self\' \'unsafe-inline\'" in policy\n',
        '    style_directive = next(\n'
        '        part.strip() for part in policy.split(";")\n'
        '        if part.strip().startswith("style-src ")\n'
        '    )\n'
        '    assert style_directive == "style-src \'self\'"\n'
        '    assert "\'unsafe-inline\'" not in style_directive\n',
        1,
    )
    test_path.write_text(tests, encoding="utf-8")


def update_audit_budget() -> None:
    path = ROOT / "tools" / "audit_templates.py"
    source = path.read_text(encoding="utf-8")
    source = source.replace("MAX_INLINE_STYLE_ATTRIBUTES = 107", "MAX_INLINE_STYLE_ATTRIBUTES = 0", 1)
    path.write_text(source, encoding="utf-8")


def main() -> None:
    rules: dict[str, str] = {}
    touched = 0
    for path in sorted(TEMPLATES.rglob("*.html")):
        before = path.read_text(encoding="utf-8-sig")
        after = replace_dynamic_progress(before)
        after = extract_static_style_attributes(after, rules)
        if after != before:
            path.write_text(after, encoding="utf-8")
            touched += 1

    write_utility_css(rules)
    ensure_loader(TEMPLATES / "layout.html")
    ensure_loader(TEMPLATES / "site_layout.html")
    tighten_csp()
    update_audit_budget()

    remaining = []
    for path in TEMPLATES.rglob("*.html"):
        source = path.read_text(encoding="utf-8")
        if STYLE_ATTR_RE.search(source):
            remaining.append(path.relative_to(ROOT).as_posix())
    print(f"templates_touched={touched}")
    print(f"utility_rules={len(rules)}")
    print(f"remaining_style_attribute_files={remaining}")
    if remaining:
        raise SystemExit("inline style attributes remain")


if __name__ == "__main__":
    main()
