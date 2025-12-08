import uuid
from datetime import datetime, timedelta, timezone, date
from typing import Literal

from sqlalchemy import (
    Uuid,
    String,
    ForeignKey,
    MetaData,
    Integer,
    UniqueConstraint,
    DateTime,
    Date,
    Table,
    Column,
)
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    attribute_mapped_collection,
)

from domain.enums import StageStatus

convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata_obj = MetaData(naming_convention=convention)


# todo: 把所有 set[Movie]改变为list[Movie]， 按发行日期排序
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

    glossary: Mapped["Glossary"] = relationship(back_populates="glossary_hits")
    movie: Mapped["Movie"] = relationship(back_populates="glossary_hits")


class Actor(Base, TimestampMixin):
    __tablename__ = "actors"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    current_name: Mapped[str] = mapped_column(String, nullable=False)
    gender: Mapped[Literal["male", "female"]] = mapped_column(
        String(10), nullable=False
    )

    names: Mapped[set["ActorName"]] = relationship(back_populates="actor")
    movies: Mapped[set["Movie"]] = relationship(secondary=act_in)
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
    movies = association_proxy("actor", "movies")
    videos = association_proxy("actor", "videos")


class Movie(Base, TimestampMixin):
    __tablename__ = "movies"
    __table_args__ = (
        UniqueConstraint("label", "number", name="uq_movies_label_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    label: Mapped[str] = mapped_column(String, nullable=False)
    number: Mapped[int] = mapped_column(Integer, nullable=False)

    title_ja: Mapped[str] = mapped_column(String, nullable=False)
    title_zh: Mapped[str] = mapped_column(String, nullable=False)

    release_date: Mapped[date] = mapped_column(Date, nullable=True)
    director_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("directors.id"), nullable=True
    )
    studio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("studios.id"), nullable=True
    )

    synopsis_ja: Mapped[str] = mapped_column(String, nullable=True)
    synopsis_zh: Mapped[str] = mapped_column(String, nullable=True)

    videos: Mapped[set["Video"]] = relationship(back_populates="movie")
    terms: Mapped[set["Term"]] = relationship(back_populates="movie")
    glossary_hits: Mapped[set["GlossaryHitsIn"]] = relationship(back_populates="movie")
    glossaries = association_proxy("glossary_hits", "glossary")
    director: Mapped["Director"] = relationship(back_populates="movies")
    studio: Mapped["Studio"] = relationship(back_populates="movies")
    actors: Mapped[list["Actor"]] = relationship(secondary=act_in)
    categories: Mapped[list["Category"]] = relationship(secondary=is_a_movie_of)


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
    videos = association_proxy("movies", "videos")


class Studio(Base, TimestampMixin):
    __tablename__ = "studios"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    jap_text: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    sch_text: Mapped[str] = mapped_column(String, nullable=True)

    movies: Mapped[list["Movie"]] = relationship(back_populates="studio")
    videos = association_proxy("movies", "videos")


class Video(Base, TimestampMixin):
    __tablename__ = "videos"
    __table_args__ = (UniqueConstraint("sha256", name="uq_videos_sha256"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    movie_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("movies.id")
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

    glossary_hits: Mapped[list["GlossaryHitsIn"]] = relationship(
        back_populates="glossary"
    )
    hit_movies = association_proxy("glossary_hits", "movie")
