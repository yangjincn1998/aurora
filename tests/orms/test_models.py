import time
from datetime import date, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.aurora.domain.enums import StageStatus
from src.aurora.orms.models import (
    Actor,
    ActorName,
    Movie,
    Video,
    Glossary,
    Category,
    Director,
    Studio,
)
from src.aurora.orms.models import VideoStageStatus


def test_create_movie(session):
    movie = Movie(
        label="ABC",
        number="123",
        title_ja="テスト映画",
        title_zh="测试电影",
        release_date=date(2000, 1, 1),
    )

    session.add(movie)
    session.commit()
    saved = session.scalar(select(Movie))

    assert saved is not None
    assert saved.label == "ABC"
    assert saved.number == "123"
    assert saved.code == "ABC-123"


def test_create_movie_with_lowercase_label(session):
    movie = Movie(
        label="abc",
        number="123",
    )

    session.add(movie)
    session.commit()
    saved = session.scalar(select(Movie))

    assert saved is not None
    assert saved.code == "ABC-123"


def test_create_invalid_code(session):
    with pytest.raises(ValueError):
        movie = Movie(
            label="ABC",
            number="12A3",
        )
        session.add(movie)
        session.commit()


def test_create_movie_with_unknown_code(session):
    sha256 = "1234567890abcdef" * 4  # 64 chars
    movie = Movie(number=sha256)
    session.add(movie)
    session.commit()
    saved = session.scalar(select(Movie))

    assert saved is not None
    assert saved.is_anonymous


@pytest.fixture
def sample_movie(session):
    movie = Movie(
        label="ABC",
        number="123",
    )
    session.add(movie)
    session.commit()
    saved = session.scalar(select(Movie))
    session.refresh(saved)
    yield saved
    session.delete(saved)
    session.commit()


def test_video_movie_relationship(session, sample_movie):
    video = Video(
        sha256="1234567890abcdef" * 4,
        filename="test_video.mp4",
        absolute_path="/path/to/test_video.mp4",
        suffix="mp4",
    )
    video.movie = sample_movie

    session.add(video)
    session.commit()
    saved = session.scalar(select(Video))

    assert saved is not None
    assert saved in sample_movie.videos
    assert saved.filename == "test_video.mp4"
    assert saved.movie_id == sample_movie.id


def test_validate_video_sha256(session, sample_movie):
    with pytest.raises(ValueError):
        video = Video(
            movie_id=sample_movie.id,
            sha256="invalid_sha256_hash",
            filename="test_video.mp4",
            absolute_path="/path/to/test_video.mp4",
            suffix="mp4",
        )
        session.add(video)
        session.commit()


def test_video_suffix_validation(session, sample_movie):
    with pytest.raises(ValueError):
        video = Video(
            movie_id=sample_movie.id,
            sha256="1234567890abcdef" * 4,
            filename="test_video.unknown",
            absolute_path="/path/to/test_video.unknown",
            suffix="unknown",
        )
        session.add(video)
        session.commit()


@pytest.fixture
def sample_videos(session, sample_movie):
    v1 = Video(
        sha256="1234567890abcdef" * 4,
        filename="test_video.mp4",
        absolute_path="/path/to/test_video.mp4",
        suffix="mp4",
        movie=sample_movie,
    )
    v2 = Video(
        sha256="abcdef1234567890" * 4,
        filename="test_video2.mkv",
        absolute_path="/path/to/test_video2.mkv",
        suffix="mkv",
        movie=sample_movie,
    )
    session.add_all([v1, v2])
    session.commit()
    saves = session.scalars(select(Video)).all()
    for save in saves:
        session.refresh(save)
    yield saves
    for save in saves:
        session.delete(save)
    session.commit()


def test_glossary_hits(session, sample_movie):
    glossary = Glossary(jap_text="test term", sch_text="测试")

    sample_movie.glossaries.append(glossary)
    session.add(glossary)
    session.add(sample_movie)
    session.commit()

    saved_glossary = session.scalar(select(Glossary))
    assert sample_movie in saved_glossary.hit_movies


def test_timestamp_mixin(session):
    # 使用 Category 作为简单的测试对象
    cat = Category(jap_text="Test Time")
    session.add(cat)
    session.commit()

    assert cat.created_at is not None
    assert cat.updated_at is not None
    assert abs(cat.created_at - cat.updated_at) < timedelta(milliseconds=100)

    # 记录旧时间
    old_update_time = cat.updated_at

    # 模拟延时 (因为计算机太快，不sleep可能时间戳一样)
    time.sleep(0.1)

    # 更新数据
    cat.jap_text = "Updated Time"
    session.commit()
    session.refresh(cat)

    # 验证 updated_at 更新了，但 created_at 没变
    assert cat.updated_at > old_update_time
    assert cat.created_at < cat.updated_at


def test_director_unique_constraint(session):
    d1 = Director(jap_text="Director A")
    session.add(d1)
    session.commit()

    # 尝试插入重复的 jap_text
    d2 = Director(jap_text="Director A")
    session.add(d2)
    with pytest.raises(Exception):
        session.commit()
    session.rollback()


def test_studio_movie_relationship(session, sample_movie):
    studio = Studio(jap_text="Moodyz")
    # 测试反向关联
    sample_movie.studio = studio
    session.add(studio)
    session.commit()

    assert studio.movies == [sample_movie]
    assert sample_movie.studio_id == studio.id


def test_category_many_to_many(session, sample_movie):
    cat1 = Category(jap_text="Drama")
    cat2 = Category(jap_text="Action")

    # 测试多对多添加
    sample_movie.categories.extend([cat1, cat2])
    session.add_all([cat1, cat2])
    session.commit()

    assert len(sample_movie.categories) == 2
    assert sample_movie in cat1.movies
    assert sample_movie in cat2.movies


def test_actor_creation_and_names(session):
    actor = Actor(current_name="Yui", gender="female")

    # 添加别名
    ActorName(jap_text="Yui Hatano", actor=actor)
    ActorName(jap_text="波多野结衣", sch_text="波老师", actor=actor)

    session.add(actor)
    session.commit()

    saved_actor = session.scalar(select(Actor))
    assert len(saved_actor.names) == 2
    assert saved_actor.names[0].actor_id == saved_actor.id


def test_actor_name_unique_constraint(session):
    actor = Actor(current_name="Test", gender="female")
    session.add(actor)
    session.commit()

    # 同一个演员不能有两个相同的 jap_text
    n1 = ActorName(jap_text="Name A", actor=actor)
    session.add(n1)
    session.commit()

    n2 = ActorName(jap_text="Name A", actor=actor)
    session.add(n2)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_actor_movie_link(session, sample_movie):
    actor = Actor(current_name="Star", gender="female")
    # 测试中间表 act_in
    sample_movie.actors.append(actor)
    session.add(actor)
    session.commit()

    assert actor in sample_movie.actors
    assert sample_movie in actor.movies


def test_video_stage_dictionary_mapping(session, sample_movie):
    video = Video(
        sha256="a" * 64,
        filename="test.mp4",
        absolute_path="/tmp/test.mp4",
        suffix="mp4",
        movie=sample_movie,
    )

    # 1. 测试通过字典 key 添加状态
    stage_transcribe = VideoStageStatus(
        stage_name="transcribe", status=StageStatus.SUCCESS.value
    )
    video.stages["transcribe"] = stage_transcribe

    session.add(video)
    session.commit()

    # 2. 验证是否可以通过 key 读取
    saved_video = session.scalar(select(Video).where(Video.filename == "test.mp4"))
    assert "transcribe" in saved_video.stages
    assert saved_video.stages["transcribe"].status == StageStatus.SUCCESS.value

    # 3. 测试级联删除 (delete-orphan)
    # 从字典中移除，应该导致数据库行被删除
    del saved_video.stages["transcribe"]
    session.commit()

    # 验证数据库中确实没了
    count = session.query(VideoStageStatus).count()
    assert count == 0


def test_video_stage_unique_constraint(session, sample_movie):
    """确保同一个视频的同一个阶段不能有两条记录"""
    video = Video(
        sha256="b" * 64,
        filename="t2.mp4",
        absolute_path="/t",
        suffix="mp4",
        movie=sample_movie,
    )
    session.add(video)
    session.commit()

    # 手动添加两条冲突记录 (绕过 ORM 字典覆盖机制，直接测数据库约束)
    s1 = VideoStageStatus(video_id=video.id, stage_name="ocr", status="PENDING")
    s2 = VideoStageStatus(video_id=video.id, stage_name="ocr", status="FAILED")

    session.add_all([s1, s2])
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
