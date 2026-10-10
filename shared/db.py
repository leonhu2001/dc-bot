from collections.abc import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from web.app.config import config


class Base(DeclarativeBase):
    pass


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


def create_all_tables() -> None:
    import shared.models  # noqa: F401
    import shared.staff_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    ensure_sqlite_additive_columns(engine)

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
