from __future__ import annotations

import os
from pathlib import Path
import re

from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("DC_BOT_ROOT", str(DEFAULT_ROOT))).resolve()
TEMPLATES = ROOT / "web" / "app" / "templates"
STATIC = ROOT / "web" / "app" / "static"

# CSP debt is shrink-only. Style blocks and style attributes are fully retired;
# the remaining inline scripts must carry a per-request nonce.
MAX_INLINE_STYLE_BLOCKS = 0
MAX_INLINE_SCRIPT_BLOCKS = 7

# Patch-style frontend assets are fully retired. Keep this set empty so a new
# *_fix.js / *_fix.css fails the static audit instead of becoming permanent debt.
ALLOWED_LEGACY_PATCH_ASSETS: set[str] = set()

STATIC_REF_RE = re.compile(
    r'''(?:src|href)\s*=\s*["'](/static/[^"'?#]+)(?:[?#][^"']*)?["']''',
    re.IGNORECASE,
)
INLINE_STYLE_RE = re.compile(r"<style(?:\s|>)", re.IGNORECASE)
STYLE_ATTR_RE = re.compile(r"\bstyle\s*=", re.IGNORECASE)
INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc\s*=)[^>]*>", re.IGNORECASE)
PATCH_ASSET_RE = re.compile(r"(?:^|/)[^/]*_fix\.(?:js|css)$", re.IGNORECASE)


def title(text: str) -> None:
    print("\n" + "=" * 100)
    print(text)
    print("=" * 100)


def static_path_from_url(url: str) -> Path:
    relative = url.removeprefix("/static/")
    return STATIC / relative


def _print_debt_files(label: str, counts: dict[str, int]) -> None:
    print(f"{label}_FILES:")
    if not counts:
        print("  NONE")
        return
    for rel, count in sorted(counts.items()):
        print(f"  {rel}: {count}")


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
    inline_style_attr_count = 0
    inline_script_count = 0
    inline_style_files: dict[str, int] = {}
    inline_style_attr_files: dict[str, int] = {}
    inline_script_files: dict[str, int] = {}
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

        style_blocks = len(INLINE_STYLE_RE.findall(source))
        style_attrs = len(STYLE_ATTR_RE.findall(source))
        script_blocks = len(INLINE_SCRIPT_RE.findall(source))

        inline_style_count += style_blocks
        inline_style_attr_count += style_attrs
        inline_script_count += script_blocks

        if style_blocks:
            inline_style_files[rel] = style_blocks
        if style_attrs:
            inline_style_attr_files[rel] = style_attrs
        if script_blocks:
            inline_script_files[rel] = script_blocks

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
    print("INLINE_STYLE_ATTRIBUTES:", inline_style_attr_count)
    print("INLINE_SCRIPT_BLOCKS:", inline_script_count)
    print("MAX_INLINE_STYLE_BLOCKS:", MAX_INLINE_STYLE_BLOCKS)
    print("MAX_INLINE_SCRIPT_BLOCKS:", MAX_INLINE_SCRIPT_BLOCKS)
    _print_debt_files("INLINE_STYLE", inline_style_files)
    _print_debt_files("INLINE_STYLE_ATTRIBUTE", inline_style_attr_files)
    _print_debt_files("INLINE_SCRIPT", inline_script_files)

    if inline_style_attr_count:
        errors.append(
            f"inline style attributes are forbidden: {inline_style_attr_count}"
        )
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

    inline_script_tag_re = re.compile(
        r"<script(?![^>]*\bsrc\s*=)(?P<attrs>[^>]*)>",
        re.IGNORECASE,
    )
    missing_nonce = []
    for template_path in template_files:
        source = template_path.read_text(encoding="utf-8-sig")
        for match in inline_script_tag_re.finditer(source):
            if not re.search(r"\bnonce\s*=", match.group("attrs") or "", re.IGNORECASE):
                missing_nonce.append(template_path.name)
    if missing_nonce:
        errors.append(
            "inline executable scripts missing CSP nonce: "
            + ", ".join(sorted(set(missing_nonce)))
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
