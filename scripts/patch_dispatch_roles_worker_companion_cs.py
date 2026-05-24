from pathlib import Path
import re

layout_path = Path("web/app/templates/layout.html")
dispatch_path = Path("web/app/routers/dispatch.py")

layout = layout_path.read_text(encoding="utf-8")
dispatch = dispatch_path.read_text(encoding="utf-8")

# ===== 1. layout：派單區導航給 打手 / 陪玩 / 客服 / 總控 看 =====

nav_flags = r'''
{% set nav_roles = user.roles if user and user.roles is defined else [] %}
{% set can_use_dispatch =
    user
    and (
        user.is_admin
        or user.is_worker
        or user.is_companion
        or user.is_customer_service
        or ('admin' in nav_roles)
        or ('worker' in nav_roles)
        or ('companion' in nav_roles)
        or ('customer_service' in nav_roles)
        or ('打手' in nav_roles)
        or ('陪玩' in nav_roles)
        or ('客服' in nav_roles)
    )
%}
'''

if "can_use_dispatch" not in layout:
    layout = layout.replace("{% if user %}", "{% if user %}\n" + nav_flags, 1)

layout = layout.replace(
    "{% if user.is_worker or user.is_companion %}",
    "{% if can_use_dispatch %}",
)

layout = layout.replace(
    "{% if user.is_worker %}",
    "{% if can_use_dispatch %}",
    1,
)

layout = layout.replace(
    '<span class="nav-label">打手</span>',
    '<span class="nav-label">打手 / 陪玩 / 客服</span>',
    1,
)

layout = layout.replace(
    '<span class="nav-label">打手 / 陪玩</span>',
    '<span class="nav-label">打手 / 陪玩 / 客服</span>',
    1,
)

layout_path.write_text(layout, encoding="utf-8")


# ===== 2. dispatch.py：後端也允許 打手 / 陪玩 / 客服 / 總控 操作 =====

helper = r'''

def can_use_dispatch_page(user: dict | None) -> bool:
    """打手 / 陪玩 / 客服 / 總控 都可以使用派單頁。"""
    if not user:
        return False

    roles = user.get("roles") or []

    return bool(
        user.get("is_admin")
        or user.get("is_worker")
        or user.get("is_companion")
        or user.get("is_customer_service")
        or "admin" in roles
        or "worker" in roles
        or "companion" in roles
        or "customer_service" in roles
        or "打手" in roles
        or "陪玩" in roles
        or "客服" in roles
    )


def get_dispatch_claim_role(user: dict | None) -> str:
    """決定網站接單時的身份。陪玩優先記陪玩；其他可操作人員預設記打手。"""
    if not user:
        return "worker"

    roles = user.get("roles") or []

    if user.get("is_companion") or "companion" in roles or "陪玩" in roles:
        return "companion"

    return "worker"
'''

if "def can_use_dispatch_page(" not in dispatch:
    # 放在 get_current_user / require_user 後面附近；找不到就放 APIRouter 後面
    marker = "router = APIRouter"
    pos = dispatch.find(marker)

    if pos == -1:
        raise RuntimeError("找不到 router = APIRouter")

    line_end = dispatch.find("\n", pos)
    dispatch = dispatch[:line_end + 1] + helper + "\n" + dispatch[line_end + 1:]


# 把常見權限判斷改成 can_use_dispatch_page(user)
dispatch = re.sub(
    r"if\s+not\s+user\s+or\s+not\s+user\.get\([\"']is_worker[\"']\)\s*:",
    "if not can_use_dispatch_page(user):",
    dispatch,
)

dispatch = re.sub(
    r"if\s+not\s+user\.get\([\"']is_worker[\"']\)\s*:",
    "if not can_use_dispatch_page(user):",
    dispatch,
)

dispatch = re.sub(
    r"if\s+not\s+\(user\.get\([\"']is_worker[\"']\).*?\)\s*:",
    "if not can_use_dispatch_page(user):",
    dispatch,
    flags=re.DOTALL,
)

# 若有 HTTPException 403/Redirect 限制，前面的 if 會被替換掉
# 把 claim role 硬編 worker 的常見寫法改成依使用者身份
dispatch = dispatch.replace(
    'role_type="worker"',
    'role_type=get_dispatch_claim_role(user)',
)

dispatch = dispatch.replace(
    'role_type = "worker"',
    'role_type = get_dispatch_claim_role(user)',
)

dispatch = dispatch.replace(
    '"role_type": "worker"',
    '"role_type": get_dispatch_claim_role(user)',
)

dispatch_path.write_text(dispatch, encoding="utf-8")

print("patched dispatch nav and permissions for worker/companion/customer service")
