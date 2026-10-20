from pathlib import Path


CANONICAL_WEB_LABELS = {
    "pending_cs_dispatch": "待客服確認",
    "waiting_acceptance": "等待接單",
    "accepted_pending_pay": "等待付款",
    "active": "進行中",
    "stored": "已暫存",
    "closed": "已結單",
    "cancelled": "已取消",
}


def test_admin_copy_script_keeps_status_values_and_unifies_labels():
    source = Path(
        "web/app/static/js/pages/admin_order_copy_unification.js"
    ).read_text(encoding="utf-8")

    for value, label in CANONICAL_WEB_LABELS.items():
        assert f'{value}: "{label}"' in source

    assert "option.textContent = STATUS_BY_VALUE[value]" in source
    assert "option.value =" not in source


def test_admin_sidebar_loads_copy_unification_as_presentation_only_script():
    source = Path("web/app/templates/_admin_sidebar.html").read_text(encoding="utf-8")
    assert "admin_order_copy_unification.js" in source
    assert "defer" in source


def test_legacy_status_aliases_only_change_display_copy():
    source = Path(
        "web/app/static/js/pages/admin_order_copy_unification.js"
    ).read_text(encoding="utf-8")
    assert 'created: "待客服確認"' in source
    assert 'paid: "進行中"' in source
    assert 'completed: "已結單"' in source
    assert 'done: "已結單"' in source
    assert 'canceled: "已取消"' in source


def test_customer_service_success_copy_is_clean_at_source():
    admin_source = Path("web/app/routers/admin.py").read_text(encoding="utf-8")
    copy_source = Path(
        "web/app/static/js/pages/admin_order_copy_unification.js"
    ).read_text(encoding="utf-8")

    assert "魔丸♫魔丸♫客服分潤狀態已更新。" not in admin_source
    assert "魔丸♫魔丸♫客服分潤狀態已更新。" not in copy_source
    assert 'message="客服分潤狀態已更新。"' in admin_source
