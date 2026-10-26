from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"


def test_admin_pages_use_canonical_admin_layout() -> None:
    offenders: list[str] = []
    for path in sorted(TEMPLATES.glob("admin_*.html")):
        if path.name == "admin_layout.html":
            continue
        source = path.read_text(encoding="utf-8")
        if "<!doctype html" in source.lower() or '{% include "_admin_sidebar.html" %}' in source:
            offenders.append(path.name)
            continue
        if '{% extends "admin_layout.html" %}' not in source and '{% extends "layout.html" %}' not in source:
            offenders.append(path.name)

    assert offenders == [], "admin templates bypassing canonical shell: " + ", ".join(offenders)


def test_admin_sidebar_is_rendered_only_by_admin_layout() -> None:
    owners: list[str] = []
    for path in sorted(TEMPLATES.glob("*.html")):
        source = path.read_text(encoding="utf-8")
        if '{% include "_admin_sidebar.html" %}' in source:
            owners.append(path.name)
    assert owners == ["admin_layout.html"]
