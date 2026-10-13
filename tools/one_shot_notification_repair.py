from __future__ import annotations

from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return source.replace(old, new, 1)


def patch_reporting() -> None:
    path = Path("web/app/services/order_reporting.py")
    source = path.read_text(encoding="utf-8")
    source = replace_once(
        source,
        '        f"填寫報單：{report_url}"\n',
        '        "請點下方按鈕進入報單頁。"\n',
        "report copy",
    )
    source = replace_once(
        source,
        '            "content": content,\n            "allowed_mentions": {"parse": []},\n',
        '            "content": content,\n'
        '            "components": [\n'
        '                {\n'
        '                    "type": 1,\n'
        '                    "components": [\n'
        '                        {\n'
        '                            "type": 2,\n'
        '                            "style": 5,\n'
        '                            "label": "填寫報單",\n'
        '                            "url": report_url,\n'
        '                            "emoji": {"name": "📝"},\n'
        '                        }\n'
        '                    ],\n'
        '                }\n'
        '            ],\n'
        '            "allowed_mentions": {"parse": []},\n',
        "report payload",
    )
    path.write_text(source, encoding="utf-8")


def patch_payout_router() -> None:
    path = Path("web/app/routers/admin_payout_summary.py")
    source = path.read_text(encoding="utf-8")
    import_line = "from web.app.services.audit_trail import write_sqlite_audit_log\n"
    import_block = import_line + "from web.app.services.payout_notifications import send_payout_paid_notification\n"
    if import_block not in source:
        source = replace_once(source, import_line, import_block, "payout import")

    route_marker = '@router.post("/admin/payouts/summary/mark-paid")\n'
    if "def _collect_bulk_payout_notification_targets" not in source:
        helper_block = '''def _collect_bulk_payout_notification_targets(month: str, role: str) -> list[dict]:
    targets: list[dict] = []
    for person in fetch_rows(month, role, None, status="unpaid"):
        person_id = str(person.get("discord_id") or "").strip()
        person_role = str(person.get("role") or "all").strip() or "all"
        if not person_id:
            continue
        targets.append(
            {
                "person_id": person_id,
                "person_role": person_role,
                "before": _audit_payout_state(
                    month,
                    person_role,
                    person_id=person_id,
                ),
            }
        )
    return targets


def _send_bulk_payout_paid_notifications(targets: list[dict]) -> None:
    for target in targets:
        try:
            send_payout_paid_notification(
                db_file=db_path(),
                person_id=target["person_id"],
                before=target["before"],
                after={
                    "target_status": "paid",
                    "person_role": target["person_role"],
                },
            )
        except Exception as exc:
            print(
                "[payout_notification] bulk delivery failed:",
                target.get("person_id"),
                repr(exc),
            )


'''
        source = replace_once(source, route_marker, helper_block + route_marker, "payout route")

    source = replace_once(
        source,
        '    before = _audit_payout_state(month, role)\n    update_summary_payout_status(month, role, "paid")\n',
        '    notification_targets = _collect_bulk_payout_notification_targets(month, role)\n'
        '    before = _audit_payout_state(month, role)\n'
        '    update_summary_payout_status(month, role, "paid")\n',
        "bulk paid start",
    )
    source = replace_once(
        source,
        '        reason="批次標記薪資已發放",\n        db_file=db_path(),\n    )\n    return RedirectResponse(\n',
        '        reason="批次標記薪資已發放",\n        db_file=db_path(),\n    )\n'
        '    _send_bulk_payout_paid_notifications(notification_targets)\n'
        '    return RedirectResponse(\n',
        "bulk paid end",
    )
    path.write_text(source, encoding="utf-8")


def append_tests() -> None:
    order_test = Path("tests/test_order_reporting.py")
    source = order_test.read_text(encoding="utf-8")
    marker = "def test_report_reminder_dm_uses_discord_link_button_instead_of_raw_url"
    if marker not in source:
        source += '''\n\ndef test_report_reminder_dm_uses_discord_link_button_instead_of_raw_url():
    root = Path(__file__).resolve().parents[1]
    runtime_source = (root / "web/app/services/order_reporting.py").read_text(encoding="utf-8")
    assert '"components": [' in runtime_source
    assert '"style": 5' in runtime_source
    assert '"label": "填寫報單"' in runtime_source
    assert '"url": report_url' in runtime_source
    assert '"emoji": {"name": "📝"}' in runtime_source
    assert 'f"填寫報單：{report_url}"' not in runtime_source
'''
        order_test.write_text(source, encoding="utf-8")

    payout_test = Path("tests/test_payout_notifications.py")
    source = payout_test.read_text(encoding="utf-8")
    if "def test_single_person_paid_audit_hook_stays_connected" not in source:
        source += '''\n\ndef test_single_person_paid_audit_hook_stays_connected(tmp_path, monkeypatch):
    from web.app.services import audit_trail
    captured = []

    def fake_send_payout_paid_notification(**kwargs):
        captured.append(kwargs)
        return {"sent": True, "total": 321}

    monkeypatch.setattr(payout_notifications, "send_payout_paid_notification", fake_send_payout_paid_notification)
    audit_trail.write_sqlite_audit_log(
        admin_discord_id="999",
        action="set_person_payout_status",
        target_type="payout_person",
        target_id="123",
        before=_snapshot(worker_unpaid=1),
        after={**_snapshot(), "target_status": "paid", "person_role": "worker"},
        db_file=tmp_path / "audit.db",
    )
    assert len(captured) == 1
    assert str(captured[0]["person_id"]) == "123"
    assert captured[0]["after"]["target_status"] == "paid"


def test_bulk_paid_notification_targets_only_capture_currently_unpaid_people(monkeypatch):
    from web.app.routers import admin_payout_summary
    rows = [
        {"discord_id": "101", "role": "worker"},
        {"discord_id": "202", "role": "customer_service"},
    ]
    snapshots = []
    monkeypatch.setattr(
        admin_payout_summary,
        "fetch_rows",
        lambda month, role, q, status="unpaid": rows if status == "unpaid" else [],
    )

    def fake_snapshot(month, role, *, person_id=None):
        snapshots.append((month, role, person_id))
        return _snapshot(
            worker_unpaid=1 if role == "worker" else 0,
            cs_unpaid=1 if role == "customer_service" else 0,
        )

    monkeypatch.setattr(admin_payout_summary, "_audit_payout_state", fake_snapshot)
    targets = admin_payout_summary._collect_bulk_payout_notification_targets("2026-10", "all")
    assert [item["person_id"] for item in targets] == ["101", "202"]
    assert snapshots == [
        ("2026-10", "worker", "101"),
        ("2026-10", "customer_service", "202"),
    ]


def test_bulk_paid_notification_failure_isolated_per_person(monkeypatch):
    from web.app.routers import admin_payout_summary
    calls = []

    def fake_send(**kwargs):
        calls.append(str(kwargs["person_id"]))
        if str(kwargs["person_id"]) == "101":
            raise RuntimeError("DM blocked")
        return {"sent": True}

    monkeypatch.setattr(admin_payout_summary, "send_payout_paid_notification", fake_send)
    monkeypatch.setattr(admin_payout_summary, "db_path", lambda: "unused.db")
    admin_payout_summary._send_bulk_payout_paid_notifications(
        [
            {"person_id": "101", "person_role": "worker", "before": _snapshot(worker_unpaid=1)},
            {"person_id": "202", "person_role": "worker", "before": _snapshot(worker_unpaid=1)},
        ]
    )
    assert calls == ["101", "202"]
'''
        payout_test.write_text(source, encoding="utf-8")


def main() -> None:
    patch_reporting()
    patch_payout_router()
    append_tests()


if __name__ == "__main__":
    main()
