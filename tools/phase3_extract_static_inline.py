from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"
STATIC = ROOT / "web" / "app" / "static"

STYLE_RE = re.compile(r"<style(?P<attrs>[^>]*)>(?P<body>.*?)</style>", re.I | re.S)
SCRIPT_RE = re.compile(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.I | re.S)


def is_dynamic(body: str) -> bool:
    return "{{" in body or "{%" in body or "{#" in body


def write_asset(relative: str, body: str) -> None:
    target = STATIC / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    normalized = body.strip("\n") + "\n"
    target.write_text(normalized, encoding="utf-8")


style_total = 0
script_total = 0

for template in sorted(TEMPLATES.glob("*.html")):
    text = template.read_text(encoding="utf-8-sig")
    stem = template.stem
    style_index = 0
    script_index = 0

    def replace_style(match: re.Match[str]) -> str:
        nonlocal_style = None
        del nonlocal_style
        global style_total
        attrs = match.group("attrs") or ""
        body = match.group("body")
        if is_dynamic(body):
            return match.group(0)
        meaningful_attrs = re.sub(r"\s+", " ", attrs).strip()
        if meaningful_attrs and not re.fullmatch(r'''type\s*=\s*["']text/css["']''', meaningful_attrs, re.I):
            raise RuntimeError(f"unsupported <style> attrs in {template.name}: {attrs!r}")
        replace_style.index += 1
        style_total += 1
        relative = f"css/pages/{stem}_inline_{replace_style.index}.css"
        write_asset(relative, body)
        return f'<link rel="stylesheet" href="/static/{relative}?v=20261013">'

    replace_style.index = 0
    text = STYLE_RE.sub(replace_style, text)

    def replace_script(match: re.Match[str]) -> str:
        global script_total
        attrs = match.group("attrs") or ""
        body = match.group("body")
        if re.search(r"\bsrc\s*=", attrs, re.I) or is_dynamic(body):
            return match.group(0)
        replace_script.index += 1
        script_total += 1
        relative = f"js/pages/{stem}_inline_{replace_script.index}.js"
        write_asset(relative, body)
        clean_attrs = attrs.rstrip()
        return f'<script{clean_attrs} src="/static/{relative}?v=20261013"></script>'

    replace_script.index = 0
    text = SCRIPT_RE.sub(replace_script, text)
    template.write_text(text, encoding="utf-8")

print(f"extracted static inline styles: {style_total}")
print(f"extracted static inline scripts: {script_total}")
