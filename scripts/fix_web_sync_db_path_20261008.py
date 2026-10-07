from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "services" / "web_sync" / "runtime.py"
text = path.read_text(encoding="utf-8")
old = 'return str(Path(__file__).with_name("web_dashboard.db"))'
new = 'return str(Path(__file__).resolve().parents[2] / "web_dashboard.db")'
if old not in text:
    raise SystemExit("target not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
