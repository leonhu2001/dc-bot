from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    target = Path(path)
    source = target.read_text(encoding="utf-8")
    if old not in source:
        raise SystemExit(f"guard failed: expected block not found in {path}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")


# 1) Assignment-level tri-state override. None follows the approved report.
replace(
    "shared/models.py",
    "    has_named_bonus: Mapped[bool] = mapped_column(Boolean, default=False)\n\n    assigned_at:",
    "    has_named_bonus: Mapped[bool] = mapped_column(Boolean, default=False)\n    stream_bonus_override: Mapped[bool | None] = mapped_column(Boolean, nullable=True)\n\n    assigned_at:",
)

# 2) Additive compatibility for existing SQLite production databases.
replace(
    "shared/db.py",
    "        if \"closed_at\" not in columns:\n            conn.execute(\n                text(\n                    \"ALTER TABLE web_orders \"\n                    \"ADD COLUMN closed_at DATETIME\"\n                )\n            )\n\n\ndef create_all_tables()",
    "        if \"closed_at\" not in columns:\n            conn.execute(\n                text(\n                    \"ALTER TABLE web_orders \"\n                    \"ADD COLUMN closed_at DATETIME\"\n                )\n            )\n\n        if \"order_assignments\" in tables:\n            assignment_columns = {\n                str(row[1])\n                for row in conn.execute(\n                    text(\"PRAGMA table_info(order_assignments)\")\n                ).fetchall()\n            }\n            if \"stream_bonus_override\" not in assignment_columns:\n                conn.execute(\n                    text(\n                        \"ALTER TABLE order_assignments \"\n                        \"ADD COLUMN stream_bonus_override INTEGER\"\n                    )\n                )\n\n\ndef create_all_tables()",
)

# 3) Make the payout engine use the assignment override without mutating report evidence.
replace(
    "web/app/services/worker_bonus_payout.py",
    "from shared.models import CustomerServicePayout, PayoutStatus, WebOrder, WorkerPayout",
    "from shared.models import CustomerServicePayout, OrderAssignment, PayoutStatus, WebOrder, WorkerPayout",
)
replace(
    "web/app/services/worker_bonus_payout.py",
    "def apply_approved_report_worker_bonuses(order_id: int, *, now: datetime | None = None) -> dict:\n",
    '''def _assignment_stream_override_map(db, order_id: int) -> dict[str, bool]:\n    rows = db.execute(\n        select(\n            OrderAssignment.worker_discord_id,\n            OrderAssignment.stream_bonus_override,\n        )\n        .where(OrderAssignment.order_id == int(order_id))\n        .where(OrderAssignment.is_active.is_(True))\n        .where(OrderAssignment.stream_bonus_override.is_not(None))\n        .order_by(OrderAssignment.id.asc())\n    ).all()\n    return {\n        str(worker_id): bool(override)\n        for worker_id, override in rows\n        if str(worker_id or \"\").strip()\n    }\n\n\ndef _effective_stream_bonus(\n    *,\n    legacy: bool,\n    report_streamed: bool,\n    override: bool | None,\n) -> bool:\n    if legacy:\n        return False\n    if override is None:\n        return bool(report_streamed)\n    return bool(override)\n\n\ndef apply_approved_report_worker_bonuses(order_id: int, *, now: datetime | None = None) -> dict:\n''',
)
replace(
    "web/app/services/worker_bonus_payout.py",
    "        stream_map = _approved_stream_map(db, int(order_id))\n        payouts = list(",
    "        stream_map = _approved_stream_map(db, int(order_id))\n        stream_override_map = _assignment_stream_override_map(db, int(order_id))\n        payouts = list(",
)
replace(
    "web/app/services/worker_bonus_payout.py",
    "            streamed = (not legacy) and bool(stream_map.get(worker_id))\n            named = bool(payout.has_named_bonus)",
    "            stream_override = stream_override_map.get(worker_id)\n            streamed = _effective_stream_bonus(\n                legacy=legacy,\n                report_streamed=bool(stream_map.get(worker_id)),\n                override=stream_override,\n            )\n            named = bool(payout.has_named_bonus)",
)
replace(
    "web/app/services/worker_bonus_payout.py",
    '                "streamed": streamed,\n                "named": named,',
    '                "streamed": streamed,\n                "stream_bonus_override": stream_override,\n                "named": named,',
)

# 4) Admin service: enforce new-policy + approved-report gate and audit the override.
replace(
    "web/app/services/admin_service.py",
    "from web.app.services.worker_bonus_payout import apply_approved_report_worker_bonuses",
    "from web.app.services.worker_bonus_payout import (\n    _is_legacy_order,\n    apply_approved_report_worker_bonuses,\n)",
)
replace(
    "web/app/services/admin_service.py",
    "\ndef remove_worker_from_order(\n",
    '''\ndef can_override_stream_bonus_for_order(db: Session, order_id: int) -> bool:\n    order = db.get(WebOrder, int(order_id))\n    return bool(\n        order is not None\n        and not _is_legacy_order(order)\n        and _order_has_approved_report(db, int(order_id))\n    )\n\n\ndef toggle_stream_bonus_for_assignment(\n    db: Session,\n    *,\n    assignment_id: int,\n    enabled: bool,\n    admin_user: dict,\n) -> None:\n    assignment = db.get(OrderAssignment, int(assignment_id))\n    if assignment is None:\n        raise ValueError(\"找不到這筆接單紀錄。\")\n\n    order = db.get(WebOrder, int(assignment.order_id))\n    if order is None:\n        raise ValueError(\"找不到這張訂單。\")\n    if _is_legacy_order(order):\n        raise ValueError(\"舊制訂單不使用直播 +2% 加成。\")\n    if not _order_has_approved_report(db, int(assignment.order_id)):\n        raise ValueError(\"直播加成只能在報單審核通過後修正。\")\n\n    before_override = assignment.stream_bonus_override\n    assignment.stream_bonus_override = bool(enabled)\n    db.flush()\n\n    recalculate_order_payouts(db, int(assignment.order_id))\n    create_sync_event(\n        db,\n        event_type=SyncEventType.ORDER_UPDATED,\n        order_id=int(assignment.order_id),\n        payload={\n            \"reason\": \"stream_bonus_override_updated\",\n            \"assignment_id\": int(assignment.id),\n            \"worker_discord_id\": str(assignment.worker_discord_id),\n            \"stream_bonus_override\": bool(enabled),\n        },\n    )\n    write_admin_audit_log(\n        db,\n        admin_user=admin_user,\n        action=\"toggle_stream_bonus_override\",\n        target_type=\"order_assignment\",\n        target_id=str(assignment.id),\n        before={\n            \"order_id\": int(assignment.order_id),\n            \"worker_discord_id\": str(assignment.worker_discord_id),\n            \"stream_bonus_override\": before_override,\n        },\n        after={\n            \"order_id\": int(assignment.order_id),\n            \"worker_discord_id\": str(assignment.worker_discord_id),\n            \"stream_bonus_override\": bool(enabled),\n        },\n    )\n    db.commit()\n    _reapply_approved_report_bonuses(int(assignment.order_id), True)\n\n\ndef remove_worker_from_order(\n''',
)

# 5) Workspace data + route.
replace(
    "web/app/routers/admin_order_workspace.py",
    "    add_worker_to_order,\n    remove_worker_from_order,",
    "    add_worker_to_order,\n    can_override_stream_bonus_for_order,\n    remove_worker_from_order,",
)
replace(
    "web/app/routers/admin_order_workspace.py",
    "    toggle_named_bonus_for_assignment,\n)",
    "    toggle_named_bonus_for_assignment,\n    toggle_stream_bonus_for_assignment,\n)",
)
replace(
    "web/app/routers/admin_order_workspace.py",
    "                oa.has_named_bonus,\n                oa.is_active,",
    "                oa.has_named_bonus,\n                oa.stream_bonus_override,\n                oa.is_active,",
)
replace(
    "web/app/routers/admin_order_workspace.py",
    "    return [dict(row) for row in rows]\n\n\ndef _mw_r8_cs_payout_rows",
    '''    result = [dict(row) for row in rows]\n    stream_rows = db.execute(\n        text(\n            \"\"\"\n            SELECT rw.worker_discord_id, rw.streamed\n            FROM order_reports r\n            JOIN order_report_workers rw ON rw.report_id = r.id\n            WHERE r.order_id = :order_id\n              AND r.status = 'approved'\n            \"\"\"\n        ),\n        {\"order_id\": int(order_id)},\n    ).mappings().all()\n    report_stream_map = {\n        str(row.get(\"worker_discord_id\") or \"\"): bool(row.get(\"streamed\"))\n        for row in stream_rows\n        if str(row.get(\"worker_discord_id\") or \"\").strip()\n    }\n    for row in result:\n        worker_id = str(row.get(\"worker_discord_id\") or \"\")\n        report_streamed = bool(report_stream_map.get(worker_id))\n        override = row.get(\"stream_bonus_override\")\n        row[\"report_streamed\"] = report_streamed\n        row[\"effective_stream_bonus\"] = (\n            report_streamed if override is None else bool(override)\n        )\n        row[\"stream_bonus_override_active\"] = override is not None\n    return result\n\n\ndef _mw_r8_cs_payout_rows''',
)
replace(
    "web/app/routers/admin_order_workspace.py",
    "        workspace_assignments = _mw_r8_worker_rows(db, int(order_id))\n        workspace_cs_payouts = _mw_r8_cs_payout_rows(db, int(order_id))",
    "        workspace_assignments = _mw_r8_worker_rows(db, int(order_id))\n        workspace_cs_payouts = _mw_r8_cs_payout_rows(db, int(order_id))\n        stream_bonus_editable = can_override_stream_bonus_for_order(db, int(order_id))",
)
replace(
    "web/app/routers/admin_order_workspace.py",
    '            "workspace_cs_payouts": workspace_cs_payouts,\n            "acceptance_state": acceptance_state,',
    '            "workspace_cs_payouts": workspace_cs_payouts,\n            "stream_bonus_editable": stream_bonus_editable,\n            "acceptance_state": acceptance_state,',
)
replace(
    "web/app/routers/admin_order_workspace.py",
    "\n\n@router.post(\"/admin/order-workspace/{order_id}/assignments/{assignment_id}/remove\")\nasync def admin_order_workspace_remove_worker_r8",
    '''\n\n@router.post(\"/admin/order-workspace/{order_id}/assignments/{assignment_id}/stream-bonus\")\nasync def admin_order_workspace_stream_bonus_r8(\n    order_id: int,\n    assignment_id: int,\n    request: Request,\n    enabled: str | None = Form(default=None),\n):\n    user = require_admin_user(request)\n    if not user:\n        return RedirectResponse(url=\"/service\", status_code=303)\n\n    db = SessionLocal()\n    try:\n        payout_snapshot = _mw_r8_snapshot_payout_status(db, int(order_id))\n        toggle_stream_bonus_for_assignment(\n            db,\n            assignment_id=assignment_id,\n            enabled=enabled == \"on\",\n            admin_user=user,\n        )\n        _mw_r8_restore_payout_status(db, int(order_id), payout_snapshot)\n        db.commit()\n    except ValueError as exc:\n        db.rollback()\n        return _mw4a2r6_redirect(order_id, request=request, error=str(exc))\n    finally:\n        db.close()\n\n    return _mw4a2r6_redirect(order_id, request=request, message=\"直播加成已更新。\")\n\n\n@router.post(\"/admin/order-workspace/{order_id}/assignments/{assignment_id}/remove\")\nasync def admin_order_workspace_remove_worker_r8''',
)

# 6) Workspace UI: explicit live-bonus checkbox next to named bonus.
replace(
    "web/app/templates/admin_order_detail.html",
    '''                        </form>\n\n                        <form class=\"mw-r8-inline-form\" method=\"post\" action=\"/admin/order-workspace/{{ order.id }}/manual-payout?return_to={{ request.query_params.get('return_to', '') | urlencode }}\">''',
    '''                        </form>\n\n                        <form class=\"mw-r8-inline-form\" method=\"post\" action=\"/admin/order-workspace/{{ order.id }}/assignments/{{ row.assignment_id }}/stream-bonus?return_to={{ request.query_params.get('return_to', '') | urlencode }}\">\n<input type=\"hidden\" name=\"csrf_token\" value=\"{{ request.session.get('csrf_token', '') }}\">\n                            <label class=\"mw-r8-check\">\n                                <input type=\"checkbox\" name=\"enabled\" value=\"on\" {% if row.effective_stream_bonus %}checked{% endif %} {% if not stream_bonus_editable %}disabled{% endif %}>\n                                管理端修正直播（新制 +2%）\n                            </label>\n                            <button class=\"mw-r8-btn\" type=\"submit\" {% if not stream_bonus_editable %}disabled{% endif %}>修正直播</button>\n                            <small class=\"mw-r8-meta\">\n                                {% if row.stream_bonus_override_active %}\n                                    管理端覆寫｜核准報單原值：{{ '有直播' if row.report_streamed else '無直播' }}\n                                {% elif stream_bonus_editable %}\n                                    目前跟隨核准報單\n                                {% else %}\n                                    需新制且報單審核通過\n                                {% endif %}\n                            </small>\n                        </form>\n\n                        <form class=\"mw-r8-inline-form\" method=\"post\" action=\"/admin/order-workspace/{{ order.id }}/manual-payout?return_to={{ request.query_params.get('return_to', '') | urlencode }}\">''',
)

# Focused regression tests committed with the feature.
Path("tests/test_admin_stream_bonus_override.py").write_text(
    '''from pathlib import Path\n\nfrom web.app.services.worker_bonus_payout import _effective_stream_bonus\n\n\nROOT = Path(__file__).resolve().parents[1]\n\n\ndef test_effective_stream_bonus_follows_report_until_admin_override():\n    assert _effective_stream_bonus(legacy=False, report_streamed=True, override=None) is True\n    assert _effective_stream_bonus(legacy=False, report_streamed=False, override=None) is False\n    assert _effective_stream_bonus(legacy=False, report_streamed=True, override=False) is False\n    assert _effective_stream_bonus(legacy=False, report_streamed=False, override=True) is True\n\n\ndef test_legacy_orders_never_gain_stream_bonus_from_override():\n    assert _effective_stream_bonus(legacy=True, report_streamed=True, override=True) is False\n\n\ndef test_stream_bonus_override_is_additive_and_workspace_controlled():\n    model = (ROOT / \"shared/models.py\").read_text(encoding=\"utf-8\")\n    schema = (ROOT / \"shared/db.py\").read_text(encoding=\"utf-8\")\n    service = (ROOT / \"web/app/services/admin_service.py\").read_text(encoding=\"utf-8\")\n    router = (ROOT / \"web/app/routers/admin_order_workspace.py\").read_text(encoding=\"utf-8\")\n    template = (ROOT / \"web/app/templates/admin_order_detail.html\").read_text(encoding=\"utf-8\")\n\n    assert \"stream_bonus_override: Mapped[bool | None]\" in model\n    assert \"ADD COLUMN stream_bonus_override INTEGER\" in schema\n    assert \"toggle_stream_bonus_for_assignment\" in service\n    assert \"直播加成只能在報單審核通過後修正\" in service\n    assert \"/stream-bonus\" in router\n    assert \"管理端修正直播（新制 +2%）\" in template\n\n\ndef test_payout_engine_reads_override_without_mutating_report_rows():\n    source = (ROOT / \"web/app/services/worker_bonus_payout.py\").read_text(encoding=\"utf-8\")\n    assert \"_assignment_stream_override_map\" in source\n    assert \"OrderAssignment.stream_bonus_override.is_not(None)\" in source\n    assert \"UPDATE order_report_workers\" not in source\n''',
    encoding="utf-8",
)

print("bounded admin stream bonus patch applied")
