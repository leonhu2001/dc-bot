from pathlib import Path
import re

path = Path("web/app/templates/layout.html")
text = path.read_text(encoding="utf-8")

script = '<script src="/static/js/ui_tweaks.js?v=1"></script>'

text = re.sub(r'<script[^>\n]*ui_tweaks\.js[^>\n]*></script>\n?', '', text)

if "</body>" in text:
    text = text.replace("</body>", script + "\n</body>", 1)
else:
    text = text.rstrip() + "\n" + script + "\n"

path.write_text(text, encoding="utf-8")
print("ui tweaks installed")
