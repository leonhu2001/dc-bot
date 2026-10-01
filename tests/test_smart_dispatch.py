import sqlite3
from datetime import datetime, timedelta, timezone

from services import smart_dispatch


TAIPEI_TZ = timezone(timedelta(hours=8))


def _setup_assignment_db(path):
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE web_orders (
                id INTEGER PRIMARY KEY,
                status TEXT NOT NULL
            );

            CREATE TABLE order_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                worker_discord_id TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                assigned_at TEXT,
                removed_at TEXT
            );
            """
        )
        conn.commit()


def test_rank_dispatch_candidates_prefers_specified_then_low_load(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    _setup_assignment_db(db_path)

    now = datetime(2026, 10, 2, 12, 0, tzinfo=TAIPEI_TZ)
    today_utc = datetime(2026, 10, 2, 2, 0, 0)

    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            INSERT INTO web_orders (id, status) VALUES
                (1, 'active'),
                (2, 'closed'),
                (3, 'active'),
                (4, 'closed'),
                (5, 'active');
            """
        )

        rows = [
            (1, "A", 1, (today_utc + timedelta(hours=1)).isoformat(sep=" ")),
            (2, "B", 1, (today_utc + timedelta(hours=2)).isoformat(sep=" ")),
            (4, "B", 0, (today_utc + timedelta(hours=3)).isoformat(sep=" ")),
            (4, "C", 0, (today_utc + timedelta(minutes=30)).isoformat(sep=" ")),
            (3, "D", 1, (today_utc + timedelta(hours=4)).isoformat(sep=" ")),
            (5, "D", 1, (today_utc + timedelta(hours=5)).isoformat(sep=" ")),
        ]

        conn.executemany(
            """
            INSERT INTO order_assignments (
                order_id,
                worker_discord_id,
                is_active,
                assigned_at
            )
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()

    ranked = smart_dispatch.rank_dispatch_candidates(
        ["A", "B", "C", "D"],
        specified_staff_ids=["D"],
        db_file=db_path,
        now_taipei=now,
    )

    assert ranked[0] == "D"
    assert ranked[1:] == ["C", "B", "A"]


def test_choose_initial_candidates_keeps_specified_and_batch_size():
    ranked = ["S1", "A", "B", "C", "D", "E", "F"]

    selected = smart_dispatch.choose_initial_candidate_ids(
        ranked,
        specified_staff_ids=["S1"],
        required_staff_count=1,
    )

    assert selected == ["S1"]

    selected_two = smart_dispatch.choose_initial_candidate_ids(
        ranked,
        specified_staff_ids=["S1"],
        required_staff_count=2,
    )

    assert selected_two == ["S1", "A", "B", "C"]


def test_next_candidate_batch_skips_already_notified():
    next_ids = smart_dispatch.next_candidate_batch(
        ["A", "B", "C", "D", "E", "F"],
        ["A", "B", "C"],
        required_staff_count=1,
    )

    assert next_ids == ["D", "E", "F"]


def test_smart_dispatch_plan_persists_and_advances(tmp_path, monkeypatch):
    db_path = tmp_path / "web_dashboard.db"
    fixed_now = datetime(2026, 10, 2, 12, 0, tzinfo=TAIPEI_TZ)

    monkeypatch.setattr(smart_dispatch, "_now_taipei", lambda: fixed_now)

    smart_dispatch.create_smart_dispatch_plan(
        order_id=10,
        dispatch_channel_id="100",
        dispatch_message_id="200",
        required_staff_count=2,
        allowed_role_ids=["1", "2"],
        specified_staff_ids=["9"],
        ranked_candidate_ids=["9", "8", "7", "6"],
        notified_candidate_ids=["9", "8", "7"],
        db_file=db_path,
    )

    plans = smart_dispatch.list_pending_smart_dispatch_plans(
        db_file=db_path,
    )

    assert len(plans) == 1
    assert plans[0]["order_id"] == 10
    assert plans[0]["specified_staff_ids"] == ["9"]
    assert plans[0]["notified_candidate_ids"] == ["9", "8", "7"]

    smart_dispatch.mark_smart_dispatch_stage(
        10,
        stage=1,
        newly_notified_ids=["6"],
        db_file=db_path,
    )

    plans = smart_dispatch.list_pending_smart_dispatch_plans(
        db_file=db_path,
    )

    assert plans[0]["stage"] == 1
    assert plans[0]["notified_candidate_ids"] == ["9", "8", "7", "6"]

    smart_dispatch.set_specified_dm_results(
        10,
        sent_ids=["9"],
        failed_ids=[],
        db_file=db_path,
    )

    smart_dispatch.complete_smart_dispatch_plan(
        10,
        reason="full_expansion_sent",
        db_file=db_path,
    )

    assert smart_dispatch.list_pending_smart_dispatch_plans(
        db_file=db_path,
    ) == []


def test_plan_age_seconds_uses_timezone_aware_created_at():
    plan = {
        "created_at": "2026-10-02T12:00:00+08:00",
    }

    age = smart_dispatch.plan_age_seconds(
        plan,
        now=datetime(2026, 10, 2, 12, 6, 30, tzinfo=TAIPEI_TZ),
    )

    assert age == 390


def test_assignment_metrics_do_not_treat_closed_order_as_active(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    _setup_assignment_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            INSERT INTO web_orders (id, status) VALUES
                (1, 'closed'),
                (2, 'active');

            INSERT INTO order_assignments (
                order_id,
                worker_discord_id,
                is_active,
                assigned_at
            )
            VALUES
                (1, 'A', 1, '2026-10-02 01:00:00'),
                (2, 'B', 1, '2026-10-02 01:00:00');
            """
        )
        conn.commit()

    metrics = smart_dispatch.get_worker_assignment_metrics(
        ["A", "B"],
        db_file=db_path,
        now_taipei=datetime(2026, 10, 2, 12, 0, tzinfo=TAIPEI_TZ),
    )

    assert metrics["A"]["active_count"] == 0
    assert metrics["B"]["active_count"] == 1


def test_initial_candidates_do_not_notify_non_specified_when_all_slots_reserved():
    selected = smart_dispatch.choose_initial_candidate_ids(
        ["S1", "S2", "A", "B", "C"],
        specified_staff_ids=["S1", "S2"],
        required_staff_count=2,
    )

    assert selected == ["S1", "S2"]


def test_plan_create_is_idempotent_without_reset(tmp_path, monkeypatch):
    db_path = tmp_path / "web_dashboard.db"
    fixed_now = datetime(2026, 10, 2, 12, 0, tzinfo=TAIPEI_TZ)
    monkeypatch.setattr(smart_dispatch, "_now_taipei", lambda: fixed_now)

    smart_dispatch.create_smart_dispatch_plan(
        order_id=77,
        dispatch_channel_id="100",
        dispatch_message_id="200",
        required_staff_count=1,
        allowed_role_ids=["1"],
        specified_staff_ids=[],
        ranked_candidate_ids=["A", "B", "C"],
        notified_candidate_ids=["A", "B", "C"],
        db_file=db_path,
    )

    smart_dispatch.mark_smart_dispatch_stage(
        77,
        stage=1,
        newly_notified_ids=["D"],
        db_file=db_path,
    )

    smart_dispatch.create_smart_dispatch_plan(
        order_id=77,
        dispatch_channel_id="999",
        dispatch_message_id="999",
        required_staff_count=4,
        allowed_role_ids=["2"],
        specified_staff_ids=["S"],
        ranked_candidate_ids=["S"],
        notified_candidate_ids=["S"],
        db_file=db_path,
    )

    plan = smart_dispatch.get_smart_dispatch_plan(
        77,
        db_file=db_path,
    )

    assert plan is not None
    assert plan["stage"] == 1
    assert plan["dispatch_channel_id"] == "100"
    assert plan["notified_candidate_ids"] == ["A", "B", "C", "D"]


def test_assignment_metrics_count_waiting_acceptance_claims(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    _setup_assignment_db(db_path)

    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE order_acceptance_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                staff_discord_id TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            );

            INSERT INTO web_orders (id, status)
            VALUES (10, 'waiting_acceptance');

            INSERT INTO order_acceptance_claims (
                order_id,
                staff_discord_id,
                is_active
            )
            VALUES (10, 'WAITING', 1);
            """
        )
        conn.commit()

    metrics = smart_dispatch.get_worker_assignment_metrics(
        ["WAITING"],
        db_file=db_path,
        now_taipei=datetime(2026, 10, 2, 12, 0, tzinfo=TAIPEI_TZ),
    )

    assert metrics["WAITING"]["active_count"] == 1
