from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from web.app.config import config


class Base(DeclarativeBase):
    pass


engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False}
    if config.DATABASE_URL.startswith("sqlite")
    else {},
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


def create_all_tables() -> None:
    import shared.models  # noqa: F401

    Base.metadata.create_all(bind=engine)