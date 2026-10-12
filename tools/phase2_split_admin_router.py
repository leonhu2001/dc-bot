from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / "web" / "app" / "routers" / "admin.py"
ROUTERS = ADMIN.parent

COMMON_IMPORTS = '''from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse
'''

COMMON_BODY = r'''

def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def redirect_to_admin(**params) -> RedirectResponse:
    query = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }

    if query:
        return RedirectResponse(
            url=f"/admin?{urlencode(query)}",
            status_code=303,
        )

    return RedirectResponse(url="/admin", status_code=303)


def require_admin_user(request: Request) -> dict | None:
    user = get_current_user(request)

    if not user or not user.get("is_admin"):
        return None

    return user


def dedupe_admin_worker_members(members):
    """Return active worker/companion choices once per Discord member."""
    result = {}
    for member in members or []:
        if isinstance(member, dict):
            discord_id = str(member.get("discord_id") or "").strip()
            is_worker = bool(member.get("is_worker"))
            is_companion = bool(member.get("is_companion"))
        else:
            discord_id = str(getattr(member, "discord_id", "") or "").strip()
            is_worker = bool(getattr(member, "is_worker", False))
            is_companion = bool(getattr(member, "is_companion", False))

        if not discord_id or not (is_worker or is_companion):
            continue
        result[discord_id] = member

    def member_name(member):
        if isinstance(member, dict):
            return str(
                member.get("display_name")
                or member.get("username")
                or member.get("discord_id")
                or ""
            )
        return str(
            getattr(member, "display_name", "")
            or getattr(member, "username", "")
            or getattr(member, "discord_id", "")
        )

    return sorted(result.values(), key=member_name)


def list_admin_worker_dropdown_members() -> list[dict]:
    """Load active worker/companion choices for admin order assignment UI."""
    db_path = Path(__file__).resolve().parents[3] / "web_dashboard.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT
                discord_id,
                username,
                display_name,
                global_name,
                is_worker,
                is_companion,
                is_customer_service,
                is_active
            FROM web_staff_members
            WHERE COALESCE(is_active, 1) = 1
              AND (
                    COALESCE(is_worker, 0) = 1
                 OR COALESCE(is_companion, 0) = 1
              )
            ORDER BY
                COALESCE(display_name, ''),
                COALESCE(global_name, ''),
                COALESCE(username, ''),
                discord_id
            """
        ).fetchall()

        members = []
        seen = set()
        for row in rows:
            discord_id = str(row["discord_id"] or "").strip()
            if not discord_id or discord_id in seen:
                continue
            seen.add(discord_id)
            members.append(
                {
                    "discord_id": discord_id,
                    "username": row["username"],
                    "display_name": row["display_name"],
                    "global_name": row["global_name"],
                    "is_worker": bool(row["is_worker"]),
                    "is_companion": bool(row["is_companion"]),
                    "is_customer_service": bool(row["is_customer_service"]),
                    "is_active": bool(row["is_active"]),
                }
            )
        return members
    finally:
        conn.close()
'''

COMMON_IMPORT_LINE = '''from web.app.routers.admin_common import (
    dedupe_admin_worker_members,
    get_current_user,
    list_admin_worker_dropdown_members,
    redirect_to_admin,
    require_admin_user,
)
'''


def decorated_start(node: ast.AST) -> int:
    decorators = getattr(node, "decorator_list", []) or []
    if decorators:
        return min(int(item.lineno) for item in decorators)
    return int(node.lineno)


def node_by_name(tree: ast.Module, name: str):
    for node in tree.body:
        if getattr(node, "name", None) == name:
            return node
    raise RuntimeError(f"top-level node not found: {name}")


def router_prelude(source: str) -> str:
    marker = 'router = APIRouter(tags=["admin"])'
    index = source.find(marker)
    if index < 0:
        raise RuntimeError("admin router prelude marker not found")
    imports = source[:index].rstrip() + "\n\n"
    return (
        imports
        + COMMON_IMPORT_LINE
        + '\nrouter = APIRouter(tags=["admin"])\n\n'
        + 'TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"\n'
        + 'templates = Jinja2Templates(directory=str(TEMPLATES_DIR))\n\n'
    )


def main() -> None:
    source = ADMIN.read_text(encoding="utf-8-sig")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)

    dashboard = node_by_name(tree, "admin_dashboard")
    cancel_order = node_by_name(tree, "admin_cancel_order")
    workspace_first = node_by_name(tree, "_mw4a2r6_table_exists")

    dashboard_start = decorated_start(dashboard)
    dashboard_end = int(dashboard.end_lineno)
    actions_start = decorated_start(cancel_order)
    workspace_start = int(workspace_first.lineno)

    prelude = router_prelude(source)
    dashboard_source = "".join(lines[dashboard_start - 1 : dashboard_end]).rstrip() + "\n"
    actions_source = "".join(lines[actions_start - 1 : workspace_start - 1]).strip() + "\n"
    workspace_source = "".join(lines[workspace_start - 1 :]).lstrip()

    common_path = ROUTERS / "admin_common.py"
    dashboard_path = ROUTERS / "admin_dashboard.py"
    workspace_path = ROUTERS / "admin_order_workspace.py"

    common_path.write_text(COMMON_IMPORTS + COMMON_BODY.lstrip(), encoding="utf-8")
    dashboard_path.write_text(prelude + dashboard_source, encoding="utf-8")
    workspace_path.write_text(prelude + workspace_source, encoding="utf-8")

    slim_admin = (
        prelude
        + actions_source
        + "\n\n# Keep route registration stable for web.app.main while implementation lives by responsibility.\n"
        + "from web.app.routers.admin_dashboard import router as admin_dashboard_router\n"
        + "from web.app.routers.admin_order_workspace import router as admin_order_workspace_router\n\n"
        + "router.include_router(admin_dashboard_router)\n"
        + "router.include_router(admin_order_workspace_router)\n"
    )
    ADMIN.write_text(slim_admin, encoding="utf-8")

    for path in (ADMIN, common_path, dashboard_path, workspace_path):
        parsed = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if not parsed.body:
            raise RuntimeError(f"generated empty module: {path}")
        print(
            f"ADMIN_SPLIT {path.relative_to(ROOT)} "
            f"bytes={path.stat().st_size}"
        )


if __name__ == "__main__":
    main()
