from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "web" / "app" / "templates"
LITERAL_DOCUMENT_NEWLINE = re.compile(
    r"\\n(?=[ \t\r\n]*</(?:head|body|html)>)",
    re.IGNORECASE,
)


def test_templates_do_not_render_literal_newline_escape_artifacts():
    bad: dict[str, int] = {}
    for path in sorted(TEMPLATES.rglob("*.html")):
        source = path.read_text(encoding="utf-8-sig")
        count = len(LITERAL_DOCUMENT_NEWLINE.findall(source))
        if count:
            bad[str(path.relative_to(ROOT))] = count

    assert not bad, (
        "literal \\n escape token found next to document closing tag: "
        + ", ".join(f"{path} x{count}" for path, count in bad.items())
    )
