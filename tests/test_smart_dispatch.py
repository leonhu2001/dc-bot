import sqlite3
from datetime import datetime, timedelta, timezone

from services import smart_dispatch


TAIPEI_TZ = timezone(timedelta(hours=8))


def test_game_requirement_intersects_existing_order_roles():
    from views.smart_dispatch import get_eligible_dispatch_candidate_ids

    class Role:
        def __init__(self, role_id):
            self.id = role_id

    class Member:
        def __init__(self, member_id, role_ids):
            self.id = member_id
            self.bot = False
            self.roles = [Role(role_id) for role_id in role_ids]

    class Guild:
        def __init__(self):
            self.members = [
                Member(1, [100, 200]),
                Member(2, [100]),
                Member(3, [200]),
                Member(4, [100, 200, 300]),
            ]

    result = get_eligible_dispatch_candidate_ids(
        Guild(),
        allowed_role_ids=["100"],
        required_game_role_ids=["200"],
    )

    assert result == ["1", "4"]


def test_specified_staff_cannot_bypass_game_requirement():
    from views.smart_dispatch import get_eligible_dispatch_candidate_ids

    class Role:
        def __init__(self, role_id):
            self.id = role_id

    class Member:
        def __init__(self, member_id, role_ids):
            self.id = member_id
            self.bot = False
            self.roles = [Role(role_id) for role_id in role_ids]

    class Guild:
        members = [
            Member(1, [100]),
            Member(2, [100, 200]),
        ]

    result = get_eligible_dispatch_candidate_ids(
        Guild(),
        allowed_role_ids=["100"],
        specified_staff_ids=["1", "2"],
        required_game_role_ids=["200"],
    )

    assert result == ["2"]


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
        required_game_role_ids=["1555453449066254417"],
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
    assert plans[0]["required_game_role_ids"] == [
        "1555453449066254417"
    ]
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


def test_prepare_recovery_can_exclude_already_accepted_candidates():
    class Role:
        def __init__(self, role_id):
            self.id = role_id

    class Member:
        def __init__(self, member_id, role_ids):
            self.id = member_id
            self.bot = False
            self.roles = [Role(role_id) for role_id in role_ids]

    class Guild:
        def __init__(self):
            self.members = [
                Member(1, [100]),
                Member(2, [100]),
                Member(3, [100]),
                Member(4, [100]),
            ]

        def get_member(self, member_id):
            return next(
                (
                    member
                    for member in self.members
                    if member.id == member_id
                ),
                None,
            )

        def get_role(self, role_id):
            return None

    result = __import__(
        "views.smart_dispatch",
        fromlist=["prepare_initial_smart_dispatch"],
    ).prepare_initial_smart_dispatch(
        Guild(),
        allowed_role_ids=["100"],
        specified_staff_ids=[],
        required_staff_count=1,
        excluded_staff_ids=["1"],
        db_file="/tmp/does-not-exist-smart-dispatch.db",
    )

    assert "1" not in result["ranked_candidate_ids"]
    assert "1" not in result["initial_notified_ids"]


def test_smart_dispatch_table_migrates_legacy_platform_role_into_game_roles(tmp_path):
    db_path = tmp_path / "web_dashboard.db"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE smart_dispatch_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL UNIQUE,
                dispatch_channel_id TEXT NOT NULL,
                dispatch_message_id TEXT NOT NULL,
                required_staff_count INTEGER NOT NULL DEFAULT 1,
                allowed_role_ids_json TEXT NOT NULL DEFAULT '[]',
                required_platform_role_id TEXT,
                specified_staff_ids_json TEXT NOT NULL DEFAULT '[]',
                ranked_candidate_ids_json TEXT NOT NULL DEFAULT '[]',
                notified_candidate_ids_json TEXT NOT NULL DEFAULT '[]',
                specified_dm_sent_ids_json TEXT NOT NULL DEFAULT '[]',
                specified_dm_failed_ids_json TEXT NOT NULL DEFAULT '[]',
                stage INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                completion_reason TEXT,
                last_error TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO smart_dispatch_notifications (
                order_id,
                dispatch_channel_id,
                dispatch_message_id,
                required_staff_count,
                allowed_role_ids_json,
                required_platform_role_id,
                specified_staff_ids_json,
                ranked_candidate_ids_json,
                notified_candidate_ids_json,
                created_at,
                updated_at
            )
            VALUES (1, '10', '20', 1, '["100"]', ?, '[]', '[]', '[]', ?, ?)
            """,
            (
                "1555453449066254417",
                datetime.now(TAIPEI_TZ).isoformat(),
                datetime.now(TAIPEI_TZ).isoformat(),
            ),
        )
        conn.commit()

    smart_dispatch.ensure_smart_dispatch_tables(db_path)

    plan = smart_dispatch.get_smart_dispatch_plan(
        1,
        db_file=db_path,
    )

    assert plan is not None
    assert plan["required_game_role_ids"] == [
        "1555453449066254417"
    ]
