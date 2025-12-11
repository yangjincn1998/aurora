import pytest
import sqlalchemy.pool
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from aurora.orms.models import Base
from aurora.services.code_extract.extractor import CodeExtractor


@pytest.fixture(scope="session")
def engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=sqlalchemy.pool.StaticPool,
    )
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def session(engine):
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    Base.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def mock_extractor(mocker):
    return mocker.Mock(spec=CodeExtractor)
