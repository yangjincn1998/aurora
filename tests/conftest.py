import pytest
import sqlalchemy.pool
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from orms.models import Base


@pytest.fixture(scope="function")
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=sqlalchemy.pool.StaticPool,
    )

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    Base.metadata.drop_all(engine)
