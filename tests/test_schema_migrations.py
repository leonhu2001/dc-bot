from sqlalchemy import create_engine, text

import shared.db as shared_db
import shared.order_acceptance as order_acceptance


def test_acceptance_schema_adds_required_game_role_column(tmp_path, monkeypatch):
    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'legacy.db'}",
        connect_args={"check_same_thread": False},
    )

    with test_engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE order_acceptance_meta (
                order_id INTEGER PRIMARY KEY,
                order_rule_key TEXT,
                required_staff_count INTEGER NOT NULL DEFAULT 1,
                min_protector_count INTEGER NOT NULL DEFAULT 0,
                allowed_role_ids_json TEXT,
                specified_staff_ids_json TEXT,
                point_benefits_allowed INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'waiting_acceptance',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        ))

    monkeypatch.setattr(order_acceptance, "engine", test_engine)

    order_acceptance.ensure_acceptance_tables()

    with test_engine.begin() as conn:
        columns = {
            str(row[1])
            for row in conn.exec_driver_sql(
                "PRAGMA table_info(order_acceptance_meta)"
            ).fetchall()
        }

    assert "required_game_role_ids_json" in columns
    assert "rule_version" in columns
    assert "rule_snapshot_json" in columns
    assert "price_snapshot_json" in columns


def test_create_all_tables_runs_acceptance_migration(monkeypatch):
    called = {"value": False}

    def fake_ensure_acceptance_tables():
        called["value"] = True

    monkeypatch.setattr(
        order_acceptance,
        "ensure_acceptance_tables",
        fake_ensure_acceptance_tables,
    )

    shared_db.create_all_tables()

    assert called["value"] is True
