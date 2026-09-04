from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from foundation import write_guard  # noqa: F401  installs the unaudited-write guards
from foundation.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


def make_engine(url: str = DATABASE_URL) -> Engine:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args, future=True)
    if url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


engine = make_engine()
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)


def session_scope() -> Iterator[Session]:
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
