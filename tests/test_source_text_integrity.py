from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (
    ROOT / "bot.py",
    ROOT / "cogs",
    ROOT / "core",
    ROOT / "services",
    ROOT / "shared",
    ROOT / "views",
    ROOT / "web" / "app",
)
TEXT_SUFFIXES = {".py", ".html", ".js", ".yml", ".yaml"}


def _source_paths():
    for root in SOURCE_ROOTS:
        paths = [root] if root.is_file() else root.rglob("*")
        for path in paths:
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                yield path


def test_source_has_no_replacement_characters_or_corrupted_question_marks():
    problems: list[str] = []

    for path in _source_paths():
        text = path.read_text(encoding="utf-8-sig", errors="strict")
        relative = path.relative_to(ROOT)

        if "�" in text:
            problems.append(f"Unicode replacement character: {relative}")

        # SQLite GLOB uses ? as a one-character wildcard. This exact YYYY-MM
        # pattern is intentional and must not be treated as mojibake.
        checked = text.replace("GLOB '????-??'", "")
        if "???" in checked:
            problems.append(f"suspicious question-mark corruption: {relative}")

    assert not problems, "\n".join(problems)
