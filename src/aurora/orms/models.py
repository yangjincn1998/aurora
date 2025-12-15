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

    synopsis_ja: Mapped[str] = mapped_column(String, nullable=True)
    synopsis_zh: Mapped[str] = mapped_column(String, nullable=True)

    videos: Mapped[list["Video"]] = relationship(back_populates="movie")
    terms: Mapped[list["Term"]] = relationship(back_populates="movie")
    glossaries: Mapped[list["Glossary"]] = relationship(
        back_populates="hit_movies", secondary="glossary_hits_in"
    )
    director: Mapped["Director"] = relationship(back_populates="movies")
    studio: Mapped["Studio"] = relationship(back_populates="movies")
    actors: Mapped[list["Actor"]] = relationship(secondary=act_in)
    categories: Mapped[list["Category"]] = relationship(secondary=is_a_movie_of)

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
            session.commit()
        return movie

    @classmethod
    def get_or_create_anonymous_movie(cls, sha256: str, session: Session) -> "Movie":
        movie = cls.find_anonymous_movie(sha256, session)
        if not movie:
            movie = Movie(
                number=sha256,
            )
            session.add(movie)
            session.commit()
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


class Director(Base, TimestampMixin):
    __tablename__ = "directors"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    jap_text: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    sch_text: Mapped[str] = mapped_column(String, nullable=True)

    movies: Mapped[list["Movie"]] = relationship(back_populates="director")


class Studio(Base, TimestampMixin):
    __tablename__ = "studios"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    jap_text: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    sch_text: Mapped[str | None] = mapped_column(String, nullable=True)

    movies: Mapped[list["Movie"]] = relationship(back_populates="studio")
    videos = association_proxy("movies", "videos")


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
    stages: Mapped[dict[str, "VideoStageStatus"]] = relationship(
        "VideoStageStatus",
        collection_class=attribute_mapped_collection("stage_name"),
        cascade="all, delete-orphan",
    )

    def update_video_absolute_path(self, absolute_path: Path, session: Session):
        self.absolute_path = str(absolute_path)
        self.filename = absolute_path.stem
        self.suffix = absolute_path.suffix.lstrip(".")
        session.add(self)
        session.commit()

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
        video.update_video_absolute_path(file_path, session)
        video.movie = movie
        session.add(video)
        session.commit()
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


class VideoStageStatus(Base, TimestampMixin):
    __tablename__ = "video_stage_statuses"
    __table_args__ = (
        UniqueConstraint(
            "video_id", "stage_name", name="uq_video_stage_statuses_video_stage"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("videos.id")
    )
    stage_name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=StageStatus.PENDING.value
    )
    by_product_path: Mapped[str] = mapped_column(String, nullable=True)

    @classmethod
    def create_or_update_stage_for_video(
            cls, video: Video, stage_name, status: StageStatus, session: Session
    ):
        origin_video_stage = session.scalar(
            select(cls).where(cls.video_id == video.id, cls.stage_name == stage_name)
        )
        if origin_video_stage:
            session.delete(origin_video_stage)
            session.commit()
        video_stage = cls(
            video_id=video.id,
            stage_name=stage_name,
            status=status.value,
        )
        session.add(video_stage)
        session.commit()
        return video_stage


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
