from pathlib import Path

ROUTER = Path("web/app/routers/admin_order_workspace.py")
source = ROUTER.read_text(encoding="utf-8")

old_import = '''from web.app.services.admin_service import (\n    add_worker_to_order,\n    can_override_stream_bonus_for_order,\n    remove_worker_from_order,\n    set_customer_service_for_order,\n    set_customer_service_payout_status,\n    set_manual_worker_payout,\n    set_worker_payout_status,\n    toggle_named_bonus_for_assignment,\n    toggle_stream_bonus_for_assignment,\n)\n'''
new_import = '''from web.app.services.admin_service import (\n    add_worker_to_order,\n    remove_worker_from_order,\n    set_customer_service_for_order,\n    set_customer_service_payout_status,\n    set_manual_worker_payout,\n    set_worker_payout_status,\n    toggle_named_bonus_for_assignment,\n)\nfrom web.app.services.admin_stream_bonus_workspace import (\n    load_stream_bonus_workspace_rows,\n    update_stream_bonus_from_workspace,\n)\n'''
if old_import not in source:
    raise SystemExit("guard failed: admin service import block changed")
source = source.replace(old_import, new_import, 1)

start_marker = "def _mw_r8_worker_rows(db, order_id: int) -> list[dict]:\n"
end_marker = "def _mw_r8_cs_payout_rows(db, order_id: int) -> list[dict]:\n"
start = source.find(start_marker)
end = source.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit("guard failed: worker row loader markers missing")
source = source[:start] + source[end:]

old_page = '''        workspace_assignments = _mw_r8_worker_rows(db, int(order_id))\n        workspace_cs_payouts = _mw_r8_cs_payout_rows(db, int(order_id))\n        stream_bonus_editable = can_override_stream_bonus_for_order(db, int(order_id))\n'''
new_page = '''        workspace_assignments, stream_bonus_editable = load_stream_bonus_workspace_rows(\n            db, int(order_id)\n        )\n        workspace_cs_payouts = _mw_r8_cs_payout_rows(db, int(order_id))\n'''
if old_page not in source:
    raise SystemExit("guard failed: workspace assignment page block changed")
source = source.replace(old_page, new_page, 1)

old_route_work = '''    db = SessionLocal()\n    try:\n        payout_snapshot = _mw_r8_snapshot_payout_status(db, int(order_id))\n        toggle_stream_bonus_for_assignment(\n            db,\n            assignment_id=assignment_id,\n            enabled=enabled == "on",\n            admin_user=user,\n        )\n        _mw_r8_restore_payout_status(db, int(order_id), payout_snapshot)\n        db.commit()\n    except ValueError as exc:\n        db.rollback()\n        return _mw4a2r6_redirect(order_id, request=request, error=str(exc))\n    finally:\n        db.close()\n\n    return _mw4a2r6_redirect(order_id, request=request, message="直播加成已更新。")\n'''
new_route_work = '''    db = SessionLocal()\n    try:\n        update_stream_bonus_from_workspace(\n            db,\n            order_id=order_id,\n            assignment_id=assignment_id,\n            enabled=enabled == "on",\n            admin_user=user,\n        )\n    except ValueError as exc:\n        db.rollback()\n        return _mw4a2r6_redirect(order_id, request=request, error=str(exc))\n    finally:\n        db.close()\n\n    return _mw4a2r6_redirect(order_id, request=request, message="直播加成已更新。")\n'''
if old_route_work not in source:
    raise SystemExit("guard failed: stream bonus route transaction block changed")
source = source.replace(old_route_work, new_route_work, 1)
ROUTER.write_text(source, encoding="utf-8")

TEST = Path("tests/test_admin_stream_bonus_override.py")
test_source = TEST.read_text(encoding="utf-8")
needle = '''    router = (ROOT / "web/app/routers/admin_order_workspace.py").read_text(encoding="utf-8")\n    template = (ROOT / "web/app/templates/admin_order_detail.html").read_text(encoding="utf-8")\n'''
replacement = '''    router = (ROOT / "web/app/routers/admin_order_workspace.py").read_text(encoding="utf-8")\n    workspace = (ROOT / "web/app/services/admin_stream_bonus_workspace.py").read_text(encoding="utf-8")\n    template = (ROOT / "web/app/templates/admin_order_detail.html").read_text(encoding="utf-8")\n'''
if needle not in test_source:
    raise SystemExit("guard failed: stream bonus regression setup changed")
test_source = test_source.replace(needle, replacement, 1)
needle2 = '''    assert "/stream-bonus" in router\n    assert "管理端修正直播（新制 +2%）" in template\n'''
replacement2 = '''    assert "/stream-bonus" in router\n    assert "load_stream_bonus_workspace_rows" in workspace\n    assert "update_stream_bonus_from_workspace" in workspace\n    assert "管理端修正直播（新制 +2%）" in template\n'''
if needle2 not in test_source:
    raise SystemExit("guard failed: stream bonus regression assertions changed")
TEST.write_text(test_source.replace(needle2, replacement2, 1), encoding="utf-8")

size = ROUTER.stat().st_size
if size > 47000:
    raise SystemExit(f"architecture guard failed after extraction: {size} > 47000")

print(f"bounded stream bonus workspace extraction applied; router={size} bytes")
