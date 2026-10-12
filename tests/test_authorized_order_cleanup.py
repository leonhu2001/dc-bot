from sqlalchemy import create_engine, text

from services.authorized_order_cleanup import purge_authorized_test_orders


def test_purge_only_removes_authorized_cancelled_test_orders(tmp_path):
    db = tmp_path / "cleanup.db"
    engine = create_engine(f"sqlite:///{db}")

    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                bot_order_no TEXT,
                status TEXT,
                item TEXT,
                order_rule_key TEXT
            )
            """
        )
        conn.exec_driver_sql(
            "CREATE TABLE roulette_draws (id INTEGER PRIMARY KEY, order_id INTEGER)"
        )
        conn.exec_driver_sql(
            "CREATE TABLE wallet_transactions (id INTEGER PRIMARY KEY, order_id INTEGER)"
        )
        conn.execute(
            text(
                """
                INSERT INTO web_orders
                    (id, bot_order_no, status, item, order_rule_key)
                VALUES
                    (1, 'MO20261012001', 'cancelled', '俄羅斯輪盤', 'admin_delta_desktop_fun_20261007053129_91eb'),
                    (2, 'MO20261012002', 'cancelled', '俄羅斯輪盤', 'admin_delta_desktop_fun_20261007053129_91eb'),
                    (3, 'MO20261012999', 'cancelled', '俄羅斯輪盤', 'admin_delta_desktop_fun_20261007053129_91eb')
                """
            )
        )
        conn.exec_driver_sql("INSERT INTO roulette_draws (id, order_id) VALUES (1, 1), (2, 2), (3, 3)")
        conn.exec_driver_sql("INSERT INTO wallet_transactions (id, order_id) VALUES (1, 1), (2, 2)")

    result = purge_authorized_test_orders(engine)
    assert result["status"] == "applied"
    assert {row["order_no"] for row in result["deleted"]} == {
        "MO20261012001",
        "MO20261012002",
    }

    with engine.begin() as conn:
        orders = conn.execute(text("SELECT bot_order_no FROM web_orders ORDER BY id")).scalars().all()
        draws = conn.execute(text("SELECT order_id FROM roulette_draws ORDER BY id")).scalars().all()
        wallet = conn.execute(text("SELECT order_id FROM wallet_transactions ORDER BY id")).scalars().all()

    assert orders == ["MO20261012999"]
    assert draws == [3]
    assert wallet == [1, 2]
    assert purge_authorized_test_orders(engine)["status"] == "already_applied"


def test_purge_fails_closed_if_target_was_reopened(tmp_path):
    db = tmp_path / "cleanup-reopened.db"
    engine = create_engine(f"sqlite:///{db}")

    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                bot_order_no TEXT,
                status TEXT,
                item TEXT,
                order_rule_key TEXT
            )
            """
        )
        conn.execute(
            text(
                """
                INSERT INTO web_orders
                    (id, bot_order_no, status, item, order_rule_key)
                VALUES
                    (1, 'MO20261012001', 'active', '俄羅斯輪盤', 'admin_delta_desktop_fun_20261007053129_91eb')
                """
            )
        )

    result = purge_authorized_test_orders(engine)
    assert result["status"] == "skipped"

    with engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM web_orders")).scalar_one()
    assert count == 1
