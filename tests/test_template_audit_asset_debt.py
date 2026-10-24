from __future__ import annotations

from pathlib import Path

from tools.audit_templates import _duplicate_page_asset_groups


def test_duplicate_page_asset_groups_only_reports_identical_content(tmp_path: Path) -> None:
    js_dir = tmp_path / "js" / "pages"
    css_dir = tmp_path / "css" / "pages"
    js_dir.mkdir(parents=True)
    css_dir.mkdir(parents=True)

    first = js_dir / "first.js"
    second = css_dir / "second.css"
    unique = js_dir / "unique.js"

    first.write_text("same-content\n", encoding="utf-8")
    second.write_text("same-content\n", encoding="utf-8")
    unique.write_text("different-content\n", encoding="utf-8")

    assert _duplicate_page_asset_groups(
        [first, second, unique],
        static_root=tmp_path,
    ) == [["css/pages/second.css", "js/pages/first.js"]]
