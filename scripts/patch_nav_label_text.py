from pathlib import Path

path = Path("web/app/templates/layout.html")
text = path.read_text(encoding="utf-8")

text = text.replace(
    '<span class="nav-label">打手</span>',
    '<span class="nav-label">打手 / 陪玩</span>',
    1,
)

path.write_text(text, encoding="utf-8")
print("updated nav label to 打手 / 陪玩")
