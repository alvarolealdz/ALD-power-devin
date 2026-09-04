import pytest
from sqlalchemy.orm import Session, sessionmaker

from foundation import seed as seed_module
from foundation.db import Base, make_engine
from foundation.write_guard import raw_writes_allowed


@pytest.fixture()
def engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session(engine) -> Session:
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    yield session
    session.close()


@pytest.fixture()
def seeded(session):
    return seed_module.seed(session)


@pytest.fixture()
def allow_raw_writes():
    with raw_writes_allowed():
        yield
