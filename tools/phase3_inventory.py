from __future__ import annotations

import ast
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"
STATIC = ROOT / "web" / "app" / "static"

STYLE_RE = re.compile(r"<style(?:\s[^>]*)?>(.*?)</style>", re.I | re.S)
SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>", re.I | re.S)
CSS_REF_RE = re.compile(r'''href\s*=\s*["'](/static/[^"'?#]+\.css)(?:[?#][^"']*)?["']''', re.I)
JS_REF_RE = re.compile(r'''src\s*=\s*["'](/static/[^"'?#]+\.js)(?:[?#][^"']*)?["']''', re.I)


def block_kind(body: str) -> str:
    dynamic = "{{" in body or "{%" in body or "{#" in body
    return "dynamic" if dynamic else "static"


print("== INLINE DEBT BY TEMPLATE ==")
for path in sorted(TEMPLATES.glob("*.html")):
    text = path.read_text(encoding="utf-8-sig")
    styles = STYLE_RE.findall(text)
    scripts = SCRIPT_RE.findall(text)
    if styles or scripts:
        print(f"{path.name}: style={len(styles)} script={len(scripts)} bytes={path.stat().st_size}")
        for index, body in enumerate(styles, start=1):
            print(f"  STYLE#{index}: {block_kind(body)} bytes={len(body.encode('utf-8'))}")
        for index, body in enumerate(scripts, start=1):
            print(f"  SCRIPT#{index}: {block_kind(body)} bytes={len(body.encode('utf-8'))}")

print("\n== STATIC CSS BY SIZE ==")
for path in sorted((STATIC / "css").glob("*.css"), key=lambda p: p.stat().st_size, reverse=True):
    print(f"{path.relative_to(STATIC)}: {path.stat().st_size}")

print("\n== STATIC JS BY SIZE ==")
for path in sorted((STATIC / "js").glob("*.js"), key=lambda p: p.stat().st_size, reverse=True):
    print(f"{path.relative_to(STATIC)}: {path.stat().st_size}")

print("\n== TEMPLATE STATIC REFERENCES ==")
css_refs: dict[str, list[str]] = {}
js_refs: dict[str, list[str]] = {}
for path in sorted(TEMPLATES.glob("*.html")):
    text = path.read_text(encoding="utf-8-sig")
    for ref in CSS_REF_RE.findall(text):
        css_refs.setdefault(ref, []).append(path.name)
    for ref in JS_REF_RE.findall(text):
        js_refs.setdefault(ref, []).append(path.name)
for ref, pages in sorted(css_refs.items()):
    print(f"CSS {ref}: {','.join(pages)}")
for ref, pages in sorted(js_refs.items()):
    print(f"JS {ref}: {','.join(pages)}")

print("\n== LARGE PYTHON MODULE STRUCTURE ==")
for rel in [
    "bot.py",
    "services/order_runtime.py",
    "services/self_service_runtime.py",
    "views/review.py",
    "web/app/routers/admin_order_workspace.py",
]:
    path = ROOT / rel
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    print(f"\n{rel}: bytes={path.stat().st_size} lines={len(source.splitlines())}")
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end = getattr(node, "end_lineno", node.lineno)
            span = end - node.lineno + 1
            if span >= 30:
                nodes.append((span, node.lineno, end, type(node).__name__, node.name))
    for span, start, end, kind, name in sorted(nodes, reverse=True)[:30]:
        print(f"  {kind} {name}: {start}-{end} ({span} lines)")
