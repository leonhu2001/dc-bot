from pathlib import Path
import re

path = Path("web/app/templates/admin_staff.html")
text = path.read_text(encoding="utf-8")

text = re.sub(
    r'\s*<p[^>]*>\s*分類完全依照 Discord 身分組：[\s\S]*?</p>',
    '',
    text,
    count=1,
)

text = text.replace(
    "分類完全依照 Discord 身分組：打手 1503701170504339458，陪玩 1503706721883783218。同一個人同時有兩個身分組時，打手和陪玩都會計入。",
    "",
)

path.write_text(text, encoding="utf-8")
print("removed staff description")
