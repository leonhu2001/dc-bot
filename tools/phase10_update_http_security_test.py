from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tests" / "test_http_security.py"

text = PATH.read_text(encoding="utf-8")
old = '    assert "style-src-attr \'unsafe-inline\'" in policy\n'
new = (
    '    assert "style-src-attr \'none\'" in policy\n'
    '    assert "style-src-attr \'unsafe-inline\'" not in policy\n'
)
if old not in text:
    raise RuntimeError("legacy style-src-attr assertion missing")
PATH.write_text(text.replace(old, new, 1), encoding="utf-8")
Path(__file__).unlink(missing_ok=True)
