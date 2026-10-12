from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"
STATIC = ROOT / "web" / "app" / "static"
CSS_DIR = STATIC / "css" / "extracted"
JS_DIR = STATIC / "js" / "extracted"
VERSION = "20261013"

STYLE_BLOCK_RE = re.compile(r"<style(?P<attrs>[^>]*)>(?P<body>.*?)</style>", re.I | re.S)
SCRIPT_BLOCK_RE = re.compile(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", re.I | re.S)
INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc\s*=)[^>]*>", re.I)
INLINE_STYLE_RE = re.compile(r"<style(?:\s|>)", re.I)


def has_jinja(text: str) -> bool:
    return "{{" in text or "{%" in text or "{#" in text


def safe_name(path: Path) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", path.stem.lower()).strip("_") or "template"


def extract_styles(path: Path, source: str) -> tuple[str, list[Path]]:
    created: list[Path] = []
    counter = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal counter
        attrs = match.group("attrs") or ""
        body = match.group("body")
        if has_jinja(attrs) or has_jinja(body):
            return match.group(0)
        counter += 1
        suffix = "" if counter == 1 else f"_{counter}"
        out = CSS_DIR / f"{safe_name(path)}{suffix}.css"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body.strip() + "\n", encoding="utf-8")
        created.append(out)
        rel = out.relative_to(STATIC).as_posix()
        return f'<link rel="stylesheet" href="/static/{rel}?v={VERSION}">'

    return STYLE_BLOCK_RE.sub(replace, source), created


def extract_scripts(
    path: Path,
    source: str,
    shared_by_digest: dict[str, Path],
) -> tuple[str, list[Path]]:
    created: list[Path] = []
    counter = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal counter
        attrs = match.group("attrs") or ""
        body = match.group("body")
        if re.search(r"\bsrc\s*=", attrs, re.I):
            return match.group(0)
        if not body.strip() or has_jinja(attrs) or has_jinja(body):
            return match.group(0)
        # JSON/data script blocks are not executable JS and must keep their DOM identity.
        if re.search(r"\btype\s*=\s*['\"](?:application/(?:ld\+)?json|application/json)['\"]", attrs, re.I):
            return match.group(0)
        counter += 1
        normalized = body.strip() + "\n"
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        out = shared_by_digest.get(digest)
        if out is None:
            suffix = "" if counter == 1 else f"_{counter}"
            out = JS_DIR / f"{safe_name(path)}{suffix}.js"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(normalized, encoding="utf-8")
            shared_by_digest[digest] = out
            created.append(out)
        rel = out.relative_to(STATIC).as_posix()
        return f'<script src="/static/{rel}?v={VERSION}"></script>'

    return SCRIPT_BLOCK_RE.sub(replace, source), created


def update_debt_budget() -> tuple[int, int]:
    style_count = 0
    script_count = 0
    for path in TEMPLATES.rglob("*.html"):
        source = path.read_text(encoding="utf-8-sig")
        style_count += len(INLINE_STYLE_RE.findall(source))
        script_count += len(INLINE_SCRIPT_RE.findall(source))

    audit = ROOT / "tools" / "audit_templates.py"
    text = audit.read_text(encoding="utf-8")
    text = re.sub(
        r"MAX_INLINE_STYLE_BLOCKS\s*=\s*\d+",
        f"MAX_INLINE_STYLE_BLOCKS = {style_count}",
        text,
        count=1,
    )
    text = re.sub(
        r"MAX_INLINE_SCRIPT_BLOCKS\s*=\s*\d+",
        f"MAX_INLINE_SCRIPT_BLOCKS = {script_count}",
        text,
        count=1,
    )
    text = text.replace(
        "# Debt budget after the 2026-10-13 public-layout extraction. The project still\n"
        "# needs CSP unsafe-inline on legacy pages, but new changes may only reduce these\n"
        "# counts, never increase them.\n",
        "# CSP debt budget. Static inline blocks have been extracted to canonical assets;\n"
        "# remaining inline blocks are dynamic bootstrap/data blocks and may only decrease.\n",
    )
    audit.write_text(text, encoding="utf-8")
    return style_count, script_count


def main() -> None:
    CSS_DIR.mkdir(parents=True, exist_ok=True)
    JS_DIR.mkdir(parents=True, exist_ok=True)
    shared_by_digest: dict[str, Path] = {}
    style_files = 0
    script_files = 0
    touched = 0

    for path in sorted(TEMPLATES.rglob("*.html")):
        before = path.read_text(encoding="utf-8-sig")
        after, styles = extract_styles(path, before)
        after, scripts = extract_scripts(path, after, shared_by_digest)
        if after != before:
            path.write_text(after, encoding="utf-8")
            touched += 1
        style_files += len(styles)
        script_files += len(scripts)

    style_count, script_count = update_debt_budget()
    print(f"templates_touched={touched}")
    print(f"css_files_created={style_files}")
    print(f"js_files_created={script_files}")
    print(f"remaining_inline_styles={style_count}")
    print(f"remaining_inline_scripts={script_count}")
    if style_count != 0:
        raise SystemExit(f"expected all static style blocks extracted, got {style_count}")


if __name__ == "__main__":
    main()
