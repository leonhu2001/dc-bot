from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DEPLOYED_BASE = "547da839d29c571198e30c4964fc985e4484debf"


def replace_once(path: Path, old: str, new: str) -> None:
    source = path.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"expected exactly one match in {path}: found {count}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def restore_guard_to_deployed_state() -> None:
    guard_path = ROOT / "web/app/static/js/mw_order_guard.js"
    guard_source = subprocess.check_output(
        [
            "git",
            "show",
            f"{DEPLOYED_BASE}:web/app/static/js/mw_order_guard.js",
        ],
        cwd=ROOT,
        text=True,
    )
    guard_path.write_text(guard_source, encoding="utf-8")

    guard_test = ROOT / "tests/test_order_guard_canonical_state.py"
    if guard_test.exists():
        guard_test.unlink()


def fix_self_service_financial_configuration() -> None:
    path = ROOT / "services/self_service_runtime.py"

    replace_once(
        path,
        '    financial_keys = {\n        "ORDER_POINT_BENEFIT_SPECS",\n',
        '    # ORDER_POINT_BENEFIT_SPECS is owned by self_service_selection_runtime,\n'
        '    # so bot.py must not be required to re-export it just to configure\n'
        '    # the financial runtime.\n'
        '    financial_keys = {\n',
    )

    replace_once(
        path,
        '            order_point_benefit_specs=namespace["ORDER_POINT_BENEFIT_SPECS"],\n',
        '            order_point_benefit_specs=ORDER_POINT_BENEFIT_SPECS,\n',
    )


def fix_admin_dashboard_meta_loader() -> None:
    path = ROOT / "web/app/routers/admin_dashboard.py"

    marker = (
        'TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"\n'
        'templates = Jinja2Templates(directory=str(TEMPLATES_DIR))\n\n'
        '@router.get("/admin")\n'
    )

    helper = '''TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"\ntemplates = Jinja2Templates(directory=str(TEMPLATES_DIR))\n\n\ndef _load_admin_order_meta_by_order(db) -> dict[int, dict]:\n    table_row = db.execute(\n        text(\n            """\n            SELECT name\n            FROM sqlite_master\n            WHERE type = 'table'\n              AND name = 'web_admin_order_meta'\n            LIMIT 1\n            """\n        )\n    ).first()\n\n    if table_row is None:\n        return {}\n\n    rows = db.execute(\n        text("SELECT * FROM web_admin_order_meta")\n    ).mappings().all()\n\n    result: dict[int, dict] = {}\n    for row in rows:\n        data = dict(row)\n        try:\n            order_id = int(data.get("order_id"))\n        except (TypeError, ValueError):\n            continue\n        result[order_id] = data\n\n    return result\n\n\n@router.get("/admin")\n'''

    replace_once(path, marker, helper)
    replace_once(
        path,
        "            _mw4a2r6_meta_map(\n",
        "            _load_admin_order_meta_by_order(\n",
    )


def write_regression_tests() -> None:
    path = ROOT / "tests/test_incident_hotfix_20261013.py"
    path.write_text(
        '''from sqlalchemy import create_engine, text\nfrom sqlalchemy.orm import Session\n\nfrom services import self_service_runtime\nfrom web.app.routers import admin_dashboard\n\n\ndef test_self_service_financial_runtime_configures_without_bot_reexport(monkeypatch):\n    captured = {}\n\n    def fake_configure_self_service_financials(**kwargs):\n        captured.update(kwargs)\n\n    monkeypatch.setattr(\n        self_service_runtime,\n        "configure_self_service_financials",\n        fake_configure_self_service_financials,\n    )\n\n    namespace = {\n        "POINT_REDEEM_ITEMS_BY_KEY": {},\n        "_to_int": lambda value, default=0: default,\n        "allocate_store_absorbed_fixed_discount": lambda *args, **kwargs: None,\n        "get_current_reward_points": lambda *args, **kwargs: 0,\n        "get_customer_reward_data": lambda *args, **kwargs: {},\n        "get_effective_member_level": lambda *args, **kwargs: {"name": "普通魔丸"},\n        "get_self_service_quantity_unit": lambda *args, **kwargs: "小時",\n        "get_vip_discount_pay_rate": lambda *args, **kwargs: 100,\n    }\n\n    self_service_runtime.configure_self_service_runtime(namespace)\n\n    assert captured["order_point_benefit_specs"] is self_service_runtime.ORDER_POINT_BENEFIT_SPECS\n    assert callable(captured["self_service_staff_price"])\n    assert captured["self_service_staff_price"] is self_service_runtime.get_self_service_staff_price\n\n\ndef test_admin_dashboard_meta_loader_handles_existing_table():\n    engine = create_engine("sqlite:///:memory:")\n    with Session(engine) as db:\n        db.execute(\n            text(\n                """\n                CREATE TABLE web_admin_order_meta (\n                    order_id INTEGER PRIMARY KEY,\n                    internal_note TEXT NOT NULL DEFAULT '',\n                    needs_attention INTEGER NOT NULL DEFAULT 0,\n                    attention_reason TEXT NOT NULL DEFAULT ''\n                )\n                """\n            )\n        )\n        db.execute(\n            text(\n                """\n                INSERT INTO web_admin_order_meta\n                    (order_id, internal_note, needs_attention, attention_reason)\n                VALUES\n                    (123, 'test note', 1, 'check me')\n                """\n            )\n        )\n\n        result = admin_dashboard._load_admin_order_meta_by_order(db)\n\n    assert result[123]["internal_note"] == "test note"\n    assert result[123]["needs_attention"] == 1\n\n\ndef test_admin_dashboard_meta_loader_handles_missing_table():\n    engine = create_engine("sqlite:///:memory:")\n    with Session(engine) as db:\n        assert admin_dashboard._load_admin_order_meta_by_order(db) == {}\n\n\ndef test_admin_dashboard_no_longer_calls_removed_phase_helper():\n    source = admin_dashboard.__file__\n    from pathlib import Path\n\n    text_source = Path(source).read_text(encoding="utf-8")\n    assert "_mw4a2r6_meta_map(" not in text_source\n    assert "_load_admin_order_meta_by_order(" in text_source\n''',
        encoding="utf-8",
    )


def main() -> None:
    restore_guard_to_deployed_state()
    fix_self_service_financial_configuration()
    fix_admin_dashboard_meta_loader()
    write_regression_tests()


if __name__ == "__main__":
    main()
