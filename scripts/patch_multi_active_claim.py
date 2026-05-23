from pathlib import Path
import re

path = Path("web/app/services/order_service.py")
text = path.read_text(encoding="utf-8")

# 移除「一人只能接一張 active 單」的後端限制。
# 這段用保守規則：刪除 raise ValueError 裡含 active / 已有 / 不能再接 / 只能 的檢查區塊。
patterns = [
    r"\n\s*active_order_count\s*=\s*get_worker_active_order_count\([^\n]*\)\s*\n\s*if\s+active_order_count\s*>\s*0:\s*\n\s*raise\s+ValueError\([^\n]*(?:active|已有|不能再接|只能)[^\n]*\)\s*",
    r"\n\s*if\s+get_worker_active_order_count\([^\n]*\)\s*>\s*0:\s*\n\s*raise\s+ValueError\([^\n]*(?:active|已有|不能再接|只能)[^\n]*\)\s*",
    r"\n\s*if\s+.+active.+:\s*\n\s*raise\s+ValueError\([^\n]*(?:已有|不能再接|只能)[^\n]*\)\s*",
]

old = text
for pattern in patterns:
    text = re.sub(pattern, "\n", text, flags=re.IGNORECASE)

if text == old:
    print("warning: 沒找到明確的一人一單限制；請人工檢查 claim_order_for_worker。")
else:
    path.write_text(text, encoding="utf-8")
    print("patched order_service.py: removed single-active-order limit")
