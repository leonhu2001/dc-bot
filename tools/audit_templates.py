from __future__ import annotations

import os
from pathlib import Path
import re

from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("DC_BOT_ROOT", str(DEFAULT_ROOT))).resolve()
TEMPLATES = ROOT / "web" / "app" / "templates"
STATIC = ROOT / "web" / "app" / "static"

# CSP debt budget. Static inline blocks have been extracted to canonical assets;
# remaining inline blocks are dynamic bootstrap/data blocks and may only decrease.
MAX_INLINE_STYLE_BLOCKS = 0
MAX_INLINE_SCRIPT_BLOCKS = 7
MAX_INLINE_STYLE_ATTRIBUTES = 107
MAX_INLINE_EVENT_ATTRIBUTES = 0

# Patch-style frontend assets are fully retired. Keep this set empty so a new
# *_fix.js / *_fix.css fails the static audit instead of becoming permanent debt.
ALLOWED_LEGACY_PATCH_ASSETS: set[str] = set()

STATIC_REF_RE = re.compile(
    r'''(?:src|href)\s*=\s*["'](/static/[^"'?#]+)(?:[?#][^"']*)?["']''',
    re.IGNORECASE,
)
INLINE_STYLE_RE = re.compile(r"<style(?:\s|>)", re.IGNORECASE)
INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc\s*=)[^>]*>", re.IGNORECASE)
INLINE_SCRIPT_WITHOUT_NONCE_RE = re.compile(
    r"<script(?![^>]*\bsrc\s*=)(?![^>]*\bnonce\s*=)[^>]*>",
    re.IGNORECASE,
)
INLINE_STYLE_ATTRIBUTE_RE = re.compile(r"\sstyle\s*=", re.IGNORECASE)
INLINE_EVENT_ATTRIBUTE_RE = re.compile(r"\son[a-z0-9_-]+\s*=", re.IGNORECASE)
PATCH_ASSET_RE = re.compile(r"(?:^|/)[^/]*_fix\.(?:js|css)$", re.IGNORECASE)


def title(text: str) -> None:
    print("\n" + "=" * 100)
    print(text)
    print("=" * 100)


def static_path_from_url(url: str) -> Path:
    relative = url.removeprefix("/static/")
    return STATIC / relative


def main() -> None:
    title("TEMPLATE_AUDIT")

    if not TEMPLATES.exists():
        raise SystemExit(f"templates folder not found: {TEMPLATES}")

    env = Environment(loader=FileSystemLoader(str(TEMPLATES)))
    template_files = sorted(
        path
        for path in TEMPLATES.rglob("*")
        if path.suffix.lower() in {".html", ".jinja", ".jinja2"}
    )

    print("ROOT:", ROOT)
    print("TEMPLATES:", TEMPLATES)
    print("TEMPLATE_COUNT:", len(template_files))

    errors: list[str] = []
    inline_style_count = 0
    inline_script_count = 0
    inline_script_without_nonce_count = 0
    inline_style_attribute_count = 0
    inline_event_attribute_count = 0
    static_references: set[str] = set()

    for path in template_files:
        rel = path.relative_to(TEMPLATES).as_posix()
        source = path.read_text(encoding="utf-8-sig")

        try:
            env.get_template(rel)
            print("OK:", rel)
        except TemplateSyntaxError as exc:
            message = f"{rel}: line {exc.lineno}: {exc.message}"
            print("ERROR:", message)
            errors.append(message)
        except Exception as exc:
            message = f"{rel}: {type(exc).__name__}: {exc}"
            print("ERROR:", message)
            errors.append(message)

        inline_style_count += len(INLINE_STYLE_RE.findall(source))
        inline_script_count += len(INLINE_SCRIPT_RE.findall(source))
        inline_script_without_nonce_count += len(INLINE_SCRIPT_WITHOUT_NONCE_RE.findall(source))
        inline_style_attribute_count += len(INLINE_STYLE_ATTRIBUTE_RE.findall(source))
        inline_event_attribute_count += len(INLINE_EVENT_ATTRIBUTE_RE.findall(source))
        static_references.update(STATIC_REF_RE.findall(source))

    title("STATIC_REFERENCES")
    missing_static: list[str] = []
    for reference in sorted(static_references):
        target = static_path_from_url(reference)
        if not target.is_file():
            missing_static.append(reference)
            print("MISSING:", reference)

    if not missing_static:
        print("ALL_REFERENCED_STATIC_FILES_EXIST")

    title("PATCH_ASSET_DEBT")
    patch_assets = sorted(
        path.relative_to(STATIC).as_posix()
        for path in STATIC.rglob("*")
        if path.is_file()
        and PATCH_ASSET_RE.search(path.relative_to(STATIC).as_posix())
    )
    unexpected_patch_assets = sorted(
        set(patch_assets) - ALLOWED_LEGACY_PATCH_ASSETS
    )
    print("PATCH_ASSETS:", patch_assets)
    print("ALLOWED_LEGACY_PATCH_ASSETS:", sorted(ALLOWED_LEGACY_PATCH_ASSETS))
    if unexpected_patch_assets:
        errors.append(
            "patch-style frontend assets are forbidden: "
            + ", ".join(unexpected_patch_assets)
        )

    title("CSP_DEBT")
    print("INLINE_STYLE_BLOCKS:", inline_style_count)
    print("INLINE_SCRIPT_BLOCKS:", inline_script_count)
    print("MAX_INLINE_STYLE_BLOCKS:", MAX_INLINE_STYLE_BLOCKS)
    print("MAX_INLINE_SCRIPT_BLOCKS:", MAX_INLINE_SCRIPT_BLOCKS)
    print("INLINE_SCRIPT_WITHOUT_NONCE:", inline_script_without_nonce_count)
    print("INLINE_STYLE_ATTRIBUTES:", inline_style_attribute_count)
    print("MAX_INLINE_STYLE_ATTRIBUTES:", MAX_INLINE_STYLE_ATTRIBUTES)
    print("INLINE_EVENT_ATTRIBUTES:", inline_event_attribute_count)
    print("MAX_INLINE_EVENT_ATTRIBUTES:", MAX_INLINE_EVENT_ATTRIBUTES)

    if inline_style_count > MAX_INLINE_STYLE_BLOCKS:
        errors.append(
            "inline style debt increased: "
            f"{inline_style_count} > {MAX_INLINE_STYLE_BLOCKS}"
        )
    if inline_script_count > MAX_INLINE_SCRIPT_BLOCKS:
        errors.append(
            "inline script debt increased: "
            f"{inline_script_count} > {MAX_INLINE_SCRIPT_BLOCKS}"
        )
    if inline_script_without_nonce_count:
        errors.append(
            f"inline script without CSP nonce: {inline_script_without_nonce_count}"
        )
    if inline_style_attribute_count > MAX_INLINE_STYLE_ATTRIBUTES:
        errors.append(
            "inline style attribute debt increased: "
            f"{inline_style_attribute_count} > {MAX_INLINE_STYLE_ATTRIBUTES}"
        )
    if inline_event_attribute_count > MAX_INLINE_EVENT_ATTRIBUTES:
        errors.append(
            "inline event handler debt increased: "
            f"{inline_event_attribute_count} > {MAX_INLINE_EVENT_ATTRIBUTES}"
        )

    title("ERRORS")
    if missing_static:
        errors.append(
            "missing static references: " + ", ".join(missing_static)
        )

    if errors:
        for error in errors:
            print("ERROR:", error)
        raise SystemExit(1)

    print("NONE")
    title("REPORT_DONE")
    print("TEMPLATE_AUDIT_PASS")


if __name__ == "__main__":
    main()
