import uuid
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from typing import Literal

from sqlalchemy import (
    Uuid,
    String,
    ForeignKey,
    MetaData,
    UniqueConstraint,
    DateTime,
    Date,
    Table,
    Column,
    event,
    select,
    CheckConstraint,
)
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    attribute_mapped_collection,
    validates,
    Session,
)

from aurora.constants import VIDEO_SUFFIXES
from aurora.domain.enums import StageStatus
from aurora.utils.file_utils import validate_sha256

convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata_obj = MetaData(naming_convention=convention)


def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))


class Base(DeclarativeBase):
    metadata = metadata_obj


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=get_bj_time,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=get_bj_time,
        onupdate=get_bj_time,
    )


act_in = Table(
    "act_in",
    Base.metadata,
    Column("actor_id", Uuid(as_uuid=True), ForeignKey("actors.id"), primary_key=True),
    Column("movie_id", Uuid(as_uuid=True), ForeignKey("movies.id"), primary_key=True),
)

is_a_movie_of = Table(
    "is_a_movie_of",
    Base.metadata,
    Column(
        "category", Uuid(as_uuid=True), ForeignKey("categories.id"), primary_key=True
    ),
    Column("movie_id", Uuid(as_uuid=True), ForeignKey("movies.id"), primary_key=True),
)


class GlossaryHitsIn(Base, TimestampMixin):
    __tablename__ = "glossary_hits_in"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    glossary_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("glossaries.id")
    )
    movie_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("movies.id")
    )


class Actor(Base, TimestampMixin):
    __tablename__ = "actors"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    current_name: Mapped[str] = mapped_column(String, nullable=False)
    gender: Mapped[Literal["male", "female"]] = mapped_column(
        String(10), nullable=False
    )

    names: Mapped[list["ActorName"]] = relationship(back_populates="actor")
    movies: Mapped[list["Movie"]] = relationship(secondary=act_in)
    videos = association_proxy("movies", "videos")

    @classmethod
    def create_or_get_actor(
            cls,
            current_name: str,
            all_names: list[str],
            gender: Literal["female", "male"],
            session: Session,
    ) -> "Actor":
        # 1. 查找：直接通过名字列表找人 (加个性别过滤是为了基本的准确性，顺便也能过 case 2)
        # 这里的逻辑是：只要 all_names 里有任何一个名字匹配上了库里的名字，就是同一个人
        stmt = (
            select(cls)
            .join(cls.names)
            .where(cls.gender == gender, ActorName.jap_text.in_(all_names))
            .limit(1)
        )
        actor = session.scalar(stmt)

        # 2. 如果没找到：创建新演员
        if not actor:
            actor = Actor(current_name=current_name, gender=gender)
            session.add(actor)
            session.flush()  # 拿到 ID
            # 添加所有名字
            for name in all_names:
                ActorName.create_or_get_actor_name(name, actor.id, session)
            return actor

        # 3. 如果找到了：核心更新逻辑 (满足 1 和 3)
        # 获取已知名字集合
        known_names = {n.jap_text for n in actor.names}

        # 【核心逻辑】：只有当传入的 current_name 是一个“完全陌生”的名字时，才更新 current_name
        if current_name not in known_names:
            actor.current_name = current_name

        # 4. 补充新名字 (查漏补缺)
        for name in all_names:
            if name not in known_names:
                ActorName.create_or_get_actor_name(name, actor.id, session)
                # 记得更新一下本地缓存，避免循环中重复添加
                known_names.add(name)

        return actor


class ActorName(Base, TimestampMixin):
    __tablename__ = "actor_names"
    __table_args__ = (
        UniqueConstraint("actor_id", "jap_text", name="uq_actor_name_id_jap_text"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("actors.id")
    )

    jap_text: Mapped[str] = mapped_column(String, nullable=False)
    sch_text: Mapped[str] = mapped_column(String, nullable=True)

    actor: Mapped["Actor"] = relationship(back_populates="names")

    @classmethod
    def create_or_get_actor_name(cls, name: str, actor_id: uuid.UUID, session: Session):
        actor_name = session.scalar(select(cls).where(cls.jap_text == name))
        if not actor_name:
            actor_name = ActorName(jap_text=name, actor_id=actor_id)
        session.add(actor_name)
        return actor_name


class Movie(Base, TimestampMixin):
    __tablename__ = "movies"
    __table_args__ = (
        UniqueConstraint("label", "number", name="uq_movies_label_number"),
    )
    ANONYMOUS_LABEL = "UNKNOWN"

    def __init__(self, **kwargs):
        if "label" not in kwargs:
            kwargs["label"] = self.ANONYMOUS_LABEL
        super().__init__(**kwargs)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    label: Mapped[str] = mapped_column(String, nullable=False)
    number: Mapped[str] = mapped_column(String, nullable=False)

    title_ja: Mapped[str] = mapped_column(String, nullable=True)
    title_zh: Mapped[str] = mapped_column(String, nullable=True)

    release_date: Mapped[date] = mapped_column(Date, nullable=True)
    director_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("directors.id"), nullable=True
    )
    studio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("studios.id"), nullable=True
    )
    series_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("series.id"), nullable=True
    )

    synopsis_ja: Mapped[str] = mapped_column(String, nullable=True)
    synopsis_zh: Mapped[str] = mapped_column(String, nullable=True)

    videos: Mapped[list["Video"]] = relationship(back_populates="movie")
    terms: Mapped[list["Term"]] = relationship(back_populates="movie")
    glossaries: Mapped[list["Glossary"]] = relationship(
        back_populates="hit_movies", secondary="glossary_hits_in"
    )
    director: Mapped["Director"] = relationship(back_populates="movies")
    studio: Mapped["Studio"] = relationship(back_populates="movies")
    actors: Mapped[list["Actor"]] = relationship(secondary=act_in, overlaps="movies")
    categories: Mapped[list["Category"]] = relationship(
        secondary=is_a_movie_of, overlaps="movies"
    )
    stages: Mapped[dict[str, "EntityStageStatus"]] = relationship(
        "EntityStageStatus",
        primaryjoin="and_(EntityStageStatus.movie_id==Movie.id, EntityStageStatus.entity_type=='movie')",
        collection_class=attribute_mapped_collection("stage_name"),
        cascade="all, delete-orphan",
    )
    series: Mapped["Series"] = relationship(back_populates="movies")

    @classmethod
    def find_anonymous_movie(cls, sha256, session: Session) -> "Movie|None":
        return session.scalar(
            select(cls).where(cls.label == cls.ANONYMOUS_LABEL, cls.number == sha256)
        )

    @classmethod
    def find_standard_movie(
            cls, label: str, number: str, session: Session
    ) -> "Movie|None":
        return session.scalar(
            select(cls).where(cls.label == label, cls.number == number)
        )

    @classmethod
    def get_or_create_standard_movie(
            cls, label: str, number: str, session: Session
    ) -> "Movie":
        movie = cls.find_standard_movie(label, number, session)
        if not movie:
            movie = Movie(
                number=number,
                label=label,
            )
            session.add(movie)
        return movie

    @classmethod
    def get_or_create_anonymous_movie(cls, sha256: str, session: Session) -> "Movie":
        movie = cls.find_anonymous_movie(sha256, session)
        if not movie:
            movie = Movie(
                number=sha256,
            )
            session.add(movie)
        return movie

    @property
    def code(self) -> str:
        return f"{self.label}-{self.number}"

    @property
    def is_anonymous(self) -> bool:
        return self.label == self.ANONYMOUS_LABEL

    @validates("label")
    def validate_label(self, key, value: str):
        if value is None:
            return self.ANONYMOUS_LABEL
        return value.upper()

    @validates("number")
    def validate_number(self, key, value: str):
        is_sha256 = validate_sha256(value)
        is_digit = value.isdigit()

        if not is_digit and not is_sha256:
            raise ValueError(
                "Movie number must be all digits or a 64-character SHA256 hash."
            )
        return value


def validate_movie_integrity(mapper, connection, target: Movie):
    """
    在插入或更新前，确保 label 和 number 的逻辑一致性。
    target 就是当前的 Movie 实例。
    如果 label 是 "Unknown"，则 number 必须是 SHA256 哈希。
    """
    if target.label == target.ANONYMOUS_LABEL:
        if len(target.number) != 64:
            raise ValueError(
                "For anonymous movies, number must be a 64-character SHA256 hash."
            )
    else:
        if not target.number.isdigit():
            raise ValueError("For non-anonymous movies, number must be all digits.")


event.listen(Movie, "before_insert", validate_movie_integrity)
event.listen(Movie, "before_update", validate_movie_integrity)


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    jap_text: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    sch_text: Mapped[str] = mapped_column(String, nullable=True)

    movies: Mapped[list["Movie"]] = relationship(secondary=is_a_movie_of)
    videos = association_proxy("movies", "videos")

    @classmethod
    def get_or_create_category(cls, jap_text, session: Session):
        category = session.scalar(select(cls).where(cls.jap_text == jap_text))
        if not category:
            category = Category(jap_text=jap_text)
        session.add(category)
        return category


class Director(Base, TimestampMixin):
    __tablename__ = "directors"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    jap_text: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    sch_text: Mapped[str] = mapped_column(String, nullable=True)

    movies: Mapped[list["Movie"]] = relationship(back_populates="director")

    @classmethod
    def get_or_create_director(cls, jap_text, session: Session) -> "Director":
        director = session.scalar(select(cls).where(cls.jap_text == jap_text))
        if not director:
            director = Director(jap_text=jap_text)
        session.add(director)
        return director


class Studio(Base, TimestampMixin):
    __tablename__ = "studios"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    jap_text: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    sch_text: Mapped[str | None] = mapped_column(String, nullable=True)

    movies: Mapped[list["Movie"]] = relationship(back_populates="studio")

    @classmethod
    def get_or_create_studio(cls, jap_text, session: Session) -> "Studio":
        studio = session.scalar(select(cls).where(cls.jap_text == jap_text))
        if not studio:
            studio = Studio(jap_text=jap_text)
        session.add(studio)
        return studio


class Video(Base, TimestampMixin):
    __tablename__ = "videos"
    __table_args__ = (UniqueConstraint("sha256", name="uq_videos_sha256"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    movie_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("movies.id"), nullable=True
    )

    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    suffix: Mapped[str] = mapped_column(String, nullable=False)
    absolute_path: Mapped[str] = mapped_column(String, nullable=False)

    movie: Mapped["Movie"] = relationship(back_populates="videos")
    stages: Mapped[dict[str, "EntityStageStatus"]] = relationship(
        "EntityStageStatus",
        primaryjoin="and_(EntityStageStatus.video_id==Video.id, EntityStageStatus.entity_type=='video')",
        collection_class=attribute_mapped_collection("stage_name"),
        cascade="all, delete-orphan",
    )

    def update_video_absolute_path(self, absolute_path: Path, session: Session):
        self.absolute_path = str(absolute_path)
        self.filename = absolute_path.stem
        self.suffix = absolute_path.suffix.lstrip(".")
        session.add(self)

    @classmethod
    def create_or_update_video(
            cls, file_path: Path, sha256: str, session: Session, movie=None
    ) -> "Video":
        video = session.scalar(select(cls).where(cls.sha256 == sha256))
        if not video:
            video = Video(
                absolute_path=str(file_path),
                sha256=sha256,
                filename=file_path.stem,
                suffix=file_path.suffix.lstrip("."),
            )
            session.add(video)
        video.movie = movie
        video.update_video_absolute_path(file_path, session)
        return video

    @classmethod
    def find_video_by_sha256(cls, sha256: str, session: Session) -> "Video|None":
        stmt = select(cls).where(cls.sha256 == sha256)
        return session.scalar(stmt)

    @validates("sha256")
    def validate_sha256(self, key, value: str):
        if not validate_sha256(value):
            raise ValueError("SHA256 must be a 64-character hexadecimal string.")
        return value.lower()

    @validates("suffix")
    def validate_suffix(self, key, value: str):
        # VIDEO_SUFFIXES = {
        #     "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "mpg", "mpeg", "3gp"
        # }
        if value.lower() not in VIDEO_SUFFIXES:
            raise ValueError(f"Unsupported video suffix: {value}")
        return value.lower()


class EntityStageStatus(Base, TimestampMixin):
    __tablename__ = "entity_stage_statuses"
    __table_args__ = (
        UniqueConstraint(
            "video_id", "stage_name", name="uq_video_stage_statuses_video_stage"
        ),
        UniqueConstraint(
            "movie_id", "stage_name", name="uq_video_stage_statuses_movie_stage"
        ),
        CheckConstraint(
            "(video_id IS NOT NULL AND movie_id IS NULL) OR (video_id IS NULL AND movie_id IS NOT NULL)",
            name="chk_entity_stage_one_fk",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("videos.id"), nullable=True
    )
    movie_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("movies.id"), nullable=True
    )
    entity_type: Mapped[Literal["movie", "video"]] = mapped_column(
        String, nullable=False
    )
    stage_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=StageStatus.PENDING.value
    )
    by_product_path: Mapped[str] = mapped_column(String, nullable=True)

    @validates("entity_id")
    def validate_entity_id(self, key, value: str):
        if value not in {"movie", "video"}:
            raise ValueError(f"Unsupported entity id: {value}")

    @classmethod
    def create_or_update_stage(
            cls, entity: Video | Movie, stage_name, status: StageStatus, session: Session
    ):
        is_video = isinstance(entity, Video)
        entity_type = "video" if is_video else "movie"

        if is_video:
            stmt = select(cls).where(
                cls.video_id == entity.id, cls.stage_name == stage_name
            )
        else:
            stmt = select(cls).where(
                cls.movie_id == entity.id, cls.stage_name == stage_name
            )

        existing_stage = session.scalar(stmt)
        if existing_stage:
            session.delete(existing_stage)
            session.flush()
        new_stage = cls(
            entity_type=entity_type,
            stage_name=stage_name,
            status=status.value,
            video_id=entity.id if is_video else None,
            movie_id=entity.id if not is_video else None,
        )
        session.add(new_stage)
        return new_stage


class Term(Base, TimestampMixin):
    __tablename__ = "terms"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    origin: Mapped[str] = mapped_column(String, nullable=False)
    recommended_translation: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=True)
    movie_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("movies.id")
    )

    movie: Mapped["Movie"] = relationship(back_populates="terms")


class Glossary(Base, TimestampMixin):
    __tablename__ = "glossaries"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    jap_text: Mapped[str] = mapped_column(String, nullable=False)
    sch_text: Mapped[str] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(String, nullable=True)

    hit_movies: Mapped[list["Movie"]] = relationship(
        back_populates="glossaries", secondary="glossary_hits_in"
    )


class Series(Base, TimestampMixin):
    __tablename__ = "series"
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    jap_text: Mapped[str] = mapped_column(String, nullable=False)
    sch_text: Mapped[str] = mapped_column(String, nullable=True)

    movies: Mapped[list["Movie"]] = relationship(back_populates="series")

    @classmethod
    def get_or_create_series(cls, series_text: str, session: Session):
        series = session.scalar(select(cls).where(cls.jap_text == series_text))
        if not series:
            series = Series(
                jap_text=series_text,
            )
        session.add(series)
        return series
