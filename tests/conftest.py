import pytest
import sqlalchemy.pool
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from aurora.orms.models import Base, Video


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


@pytest.fixture
def sha256():
    return "1234567890abcdef" * 4


@pytest.fixture
def sample_video(session, sha256, tmp_path):
    tmp_file = tmp_path / "videos" / "sample_video.mp4"
    tmp_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file.touch()
    video = Video(
        sha256=sha256,
        absolute_path=str(tmp_file.absolute()),
        filename="sample_video",
        suffix="mp4",
    )
    session.add(video)
    session.commit()
    yield video
    session.delete(video)
    session.commit()


@pytest.fixture
def example_config_yaml_loader():
    with open("config.yaml", "r") as f:
        config = yaml.safe_load(f)
    return config
