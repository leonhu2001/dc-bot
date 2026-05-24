from pathlib import Path
import re

path = Path("web/app/templates/layout.html")
text = path.read_text(encoding="utf-8")

# 移除主選單裡的分潤明細連結
text = re.sub(
    r'\s*<a\s+class="nav-link"\s+href="/admin/payouts"\s*>分潤明細</a>',
    '',
    text,
)

path.write_text(text, encoding="utf-8")
print("removed payout detail link from main nav")
