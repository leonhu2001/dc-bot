from collections.abc import Generator
from datetime import date, datetime
import sqlite3

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from web.app.config import config


class Base(DeclarativeBase):
    pass


def register_sqlite_datetime_adapters() -> None:
    """Keep SQLite datetime persistence explicit on Python 3.12+.

    Python's implicit sqlite3 date/datetime adapters are deprecated. The
    project intentionally stores naive UTC datetimes as ISO text, so register
    that behavior explicitly instead of relying on the interpreter default.
    """

    sqlite3.register_adapter(date, lambda value: value.isoformat())
    sqlite3.register_adapter(datetime, lambda value: value.isoformat(" "))


if config.DATABASE_URL.startswith("sqlite"):
    register_sqlite_datetime_adapters()


engine = create_engine(
    config.DATABASE_URL,
    connect_args={
        "check_same_thread": False,
        "timeout": 15,
    }
    if config.DATABASE_URL.startswith("sqlite")
    else {},
    pool_pre_ping=True,
)

if config.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def _worker_payout_identity(obj) -> tuple[int, str] | None:
    if getattr(obj, "__tablename__", None) != "worker_payouts":
        return None

    order_id = getattr(obj, "order_id", None)
    worker_discord_id = str(
        getattr(obj, "worker_discord_id", "") or ""
    ).strip()

    if order_id is None or not worker_discord_id:
        return None

    return int(order_id), worker_discord_id


@event.listens_for(Session, "before_flush")
def _deduplicate_pending_worker_payouts(session, flush_context, instances) -> None:
    """Collapse duplicate pending worker payouts before SQL is emitted.

    SessionLocal intentionally disables autoflush. If a payout recalculation is
    triggered twice in one transaction, the first set of newly-added
    WorkerPayout objects may still only exist in ``session.new`` when the second
    recalculation runs. A bulk DELETE therefore cannot see or remove them, and
    both sets would otherwise be inserted together at commit time.

    A worker has exactly one payout row per order, so keeping the newest pending
    object for the same ``(order_id, worker_discord_id)`` key is deterministic
    and prevents that same-session failure mode without touching persisted
    accounting history.
    """

    newest_by_key = {}
    stale_objects = []
    touched_keys = session.info.setdefault(
        "worker_payout_keys_to_validate",
        set(),
    )

    for obj in list(session.new):
        key = _worker_payout_identity(obj)
        if key is None:
            continue

        touched_keys.add(key)
        previous = newest_by_key.get(key)
        if previous is not None:
            stale_objects.append(previous)
        newest_by_key[key] = obj

    for obj in stale_objects:
        if obj in session:
            session.expunge(obj)


@event.listens_for(Session, "after_flush_postexec")
def _validate_worker_payout_uniqueness_after_flush(
    session,
    flush_context,
) -> None:
    """Reject a transaction that still creates duplicate payout identities.

    This runs *after* SQLAlchemy has completed its INSERT/DELETE ordering, so it
    stays compatible with legacy payout rebuild paths that mark old ORM rows for
    deletion and add their replacements in the same flush. Unlike a SQLite
    UNIQUE trigger/index, it does not reject that legitimate replace pattern.
    """

    touched_keys = session.info.pop(
        "worker_payout_keys_to_validate",
        set(),
    )
    if not touched_keys:
        return

    connection = session.connection()
    for order_id, worker_discord_id in touched_keys:
        count = int(
            connection.execute(
                text(
                    "SELECT COUNT(*) FROM worker_payouts "
                    "WHERE order_id=:order_id "
                    "AND worker_discord_id=:worker_discord_id"
                ),
                {
                    "order_id": int(order_id),
                    "worker_discord_id": str(worker_discord_id),
                },
            ).scalar_one()
            or 0
        )
        if count > 1:
            raise RuntimeError(
                "worker_payout_duplicate_guard: "
                f"order_id={order_id} "
                f"worker_discord_id={worker_discord_id} "
                f"count={count}"
            )


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db_session() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


def ensure_sqlite_additive_columns(bind=engine) -> None:
    if getattr(bind.dialect, "name", "") != "sqlite":
        return

    with bind.begin() as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                text(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table'"
                )
            ).fetchall()
        }

        if "web_orders" not in tables:
            return

        columns = {
            str(row[1])
            for row in conn.execute(
                text("PRAGMA table_info(web_orders)")
            ).fetchall()
        }

        if "historical_discount_amount" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE web_orders "
                    "ADD COLUMN historical_discount_amount INTEGER"
                )
            )

        if "closed_at" not in columns:
            conn.execute(
                text(
                    "ALTER TABLE web_orders "
                    "ADD COLUMN closed_at DATETIME"
                )
            )

        if "order_assignments" in tables:
            assignment_columns = {
                str(row[1])
                for row in conn.execute(
                    text("PRAGMA table_info(order_assignments)")
                ).fetchall()
            }
            if "stream_bonus_override" not in assignment_columns:
                conn.execute(
                    text(
                        "ALTER TABLE order_assignments "
                        "ADD COLUMN stream_bonus_override INTEGER"
                    )
                )


def ensure_store_binding_constraints(bind=engine) -> None:
    """Guarantee that one staff member cannot have two active bindings.

    Older deployments only enforced this in service code. Before installing
    the SQLite partial unique index, repair any pre-existing duplicates by
    keeping the newest active row and ending the older rows at the newer row's
    start time. Historical eligibility before that boundary is preserved.
    """
    if getattr(bind.dialect, "name", "") != "sqlite":
        return

    with bind.begin() as conn:
        table_exists = conn.execute(
            text(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='staff_store_bindings'"
            )
        ).first()
        if not table_exists:
            return

        duplicate_ids = [
            str(row[0])
            for row in conn.execute(
                text(
                    "SELECT staff_discord_id "
                    "FROM staff_store_bindings "
                    "WHERE status='active' "
                    "GROUP BY staff_discord_id HAVING COUNT(*) > 1"
                )
            ).all()
        ]

        for staff_id in duplicate_ids:
            rows = conn.execute(
                text(
                    "SELECT id, started_at, created_at "
                    "FROM staff_store_bindings "
                    "WHERE staff_discord_id=:staff_id AND status='active' "
                    "ORDER BY COALESCE(started_at, created_at) DESC, id DESC"
                ),
                {"staff_id": staff_id},
            ).mappings().all()
            if len(rows) < 2:
                continue

            keep = rows[0]
            boundary = keep.get("started_at") or keep.get("created_at") or datetime.utcnow()
            for stale in rows[1:]:
                conn.execute(
                    text(
                        "UPDATE staff_store_bindings "
                        "SET status='ended', "
                        "ended_at=COALESCE(ended_at, :boundary), "
                        "note=CASE "
                        "WHEN note IS NULL OR note='' THEN :repair_note "
                        "ELSE note || '｜' || :repair_note END "
                        "WHERE id=:row_id"
                    ),
                    {
                        "boundary": boundary,
                        "repair_note": "系統修復：重複綁店資格已自動結束",
                        "row_id": int(stale["id"]),
                    },
                )

        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_staff_store_bindings_one_active "
                "ON staff_store_bindings(staff_discord_id) "
                "WHERE status='active'"
            )
        )


def create_all_tables() -> None:
    import shared.models  # noqa: F401
    import shared.staff_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_sqlite_additive_columns(engine)
    ensure_store_binding_constraints(engine)

    # order_acceptance_meta / claims are maintained outside SQLAlchemy's
    # declarative metadata. Run their additive schema migration as part of the
    # canonical database initializer so deploys and fresh restores are complete
    # before either service starts serving traffic.
    from shared.order_acceptance import ensure_acceptance_tables
    from shared.order_state import ensure_order_cancellation_table

    ensure_acceptance_tables()
    ensure_order_cancellation_table(engine)

    from services.loyalty_benefits import ensure_loyalty_tables
    ensure_loyalty_tables(engine)

    # Reporting is part of the canonical schema so the close trigger is
    # installed even when the bot starts before the web dashboard. Existing
    # closed orders are backfilled as already reported before the trigger is
    # created; only future close transitions become missing reports.
    from web.app.services.order_reporting import ensure_order_reporting_tables
    ensure_order_reporting_tables(engine)
