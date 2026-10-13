from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"
STATIC_JS = ROOT / "web" / "app" / "static" / "js"

STYLE_ATTR_RE = re.compile(r"\bstyle\s*=\s*([\"'])(.*?)\1", re.I | re.S)
JS_STYLE_RE = re.compile(r"(?:\.style\.|setAttribute\(\s*[\"']style[\"'])")


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def compact(value: str) -> str:
    return " ".join(value.split())[:220]


def main() -> None:
    static_attrs = []
    dynamic_attrs = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        for match in STYLE_ATTR_RE.finditer(text):
            item = (
                str(path.relative_to(ROOT)),
                line_number(text, match.start()),
                compact(match.group(2)),
            )
            if "{{" in match.group(2) or "{%" in match.group(2):
                dynamic_attrs.append(item)
            else:
                static_attrs.append(item)

    js_style_ops = []
    for path in sorted(STATIC_JS.rglob("*.js")):
        text = path.read_text(encoding="utf-8")
        for match in JS_STYLE_RE.finditer(text):
            line = line_number(text, match.start())
            snippet = compact(text[max(0, match.start()-60):match.start()+160])
            js_style_ops.append((str(path.relative_to(ROOT)), line, snippet))

    print(f"STATIC_STYLE_ATTRS={len(static_attrs)}")
    for path, line, value in static_attrs:
        print(f"STATIC|{path}:{line}|{value}")
    print(f"DYNAMIC_STYLE_ATTRS={len(dynamic_attrs)}")
    for path, line, value in dynamic_attrs:
        print(f"DYNAMIC|{path}:{line}|{value}")
    print(f"JS_STYLE_OPERATIONS={len(js_style_ops)}")
    for path, line, value in js_style_ops:
        print(f"JS|{path}:{line}|{value}")


if __name__ == "__main__":
    main()
