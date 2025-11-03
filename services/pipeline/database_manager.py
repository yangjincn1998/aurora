import itertools
import os.path
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import List, Literal, Optional, Generator

from domain.movie import Video, Movie, Metadata, Actor, Term
from models.enums import PiplinePhase, StageStatus, MetadataType


class DatabaseManager:
    """
    基于SQLite的数据库管理实现类。
    Attributes:
        video_phases (List[PiplinePhase]): 支持的视频级文件流水线阶段列表
        db_path (str): SQLite数据库文件路径
    """

    def __init__(self, db_path: str = os.path.join(os.getcwd(), "data.sqlite3")):
        self.video_phases: List[PiplinePhase] = [
            PiplinePhase.EXTRACT_AUDIO,
            PiplinePhase.DENOISE_AUDIO,
            PiplinePhase.TRANSCRIBE_AUDIO,
            PiplinePhase.CORRECT_SUBTITLE,
            PiplinePhase.TRANSLATE_SUBTITLE,
            PiplinePhase.BILINGUAL_SUBTITLE,
        ]
        self.db_path = db_path
        self.phase_to_column = {
            PiplinePhase.EXTRACT_AUDIO: (
                "extracted_audio_status",
                "extracted_audio_path",
            ),
            PiplinePhase.DENOISE_AUDIO: (
                "denoised_audio_status",
                "denoised_audio_path",
            ),
            PiplinePhase.TRANSCRIBE_AUDIO: (
                "transcribed_subtitle_status",
                "transcribed_subtitle_path",
            ),
            PiplinePhase.CORRECT_SUBTITLE: (
                "corrected_subtitle_status",
                "corrected_subtitle_path",
            ),
            PiplinePhase.TRANSLATE_SUBTITLE: (
                "translated_subtitle_status",
                "bilingual_subtitle_path",
            ),
            PiplinePhase.BILINGUAL_SUBTITLE: (
                "bilingual_subtitle_status",
                "bilingual_subtitle_path",
            ),
        }
        self.create_tables()

    @contextmanager
    def get_cursor(self, commit: bool = False) -> Generator[sqlite3.Cursor, None, None]:
        """
        获取数据库游标的上下文管理器

        Args:
            commit (bool): 是否在退出时自动提交事务

        Yields:
            sqlite3.Cursor: 数据库游标
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            yield cursor
            if commit:
                conn.commit()
        finally:
            conn.close()

    def create_tables(self):
        with self.get_cursor(commit=True) as cursor:
            # ========== 核心表 ==========

            # 影片表 - 只保留核心字段
            cursor.execute(
                """
                create table if not exists movies(
                    code text primary key,
                    title_ja text,
                    title_zh text,
                    release_date text,
                    director_ja text,
                    studio_ja text,
                    synopsis_ja text,
                    synopsis_zh text,
                    foreign key (director_ja) references directors (name_ja),
                    foreign key (studio_ja) references studios (name_ja)
                )
                """
            )

            # 视频文件表
            cursor.execute(
                """
                create table if not exists videos(
                    sha256 text primary key,
                    absolute_path text unique,
                    filename text,
                    suffix text,
                    is_deleted integer not null default 0,
                    extracted_audio_status text,
                    extracted_audio_path text,
                    denoised_audio_status text,
                    denoised_audio_path text,
                    transcribed_subtitle_status text,
                    transcribed_subtitle_path text,
                    corrected_subtitle_status text,
                    corrected_subtitle_path text,
                    translated_subtitle_status text,
                    bilingual_subtitle_path text,
                    bilingual_subtitle_status text
                )
                """
            )

            # ========== 元数据实体表 ==========

            # 导演表
            cursor.execute(
                """
                create table if not exists directors(
                    name_ja text primary key,
                    name_zh text
                )
                """
            )

            # 制作商表
            cursor.execute(
                """
                create table if not exists studios(
                    name_ja text primary key,
                    name_zh text
                )
                """
            )

            # 类别表
            cursor.execute(
                """
                create table if not exists categories(
                    name_ja text primary key,
                    name_zh text
                )
                """
            )

            # 演员表 - 使用UUID作为主键
            cursor.execute(
                """
                create table if not exists actors(
                    actor_id text primary key,
                    current_name text not null,
                    gender text not null
                )
                """
            )

            # 演员名表
            cursor.execute(
                """
                create table if not exists actor_names(
                    name_ja text primary key,
                    name_zh text,
                    actor_id text not null,
                    foreign key (actor_id) references actors (actor_id)
                )
                """
            )

            # 术语表
            cursor.execute(
                """
                create table if not exists terms(
                    id integer primary key autoincrement,
                    origin text not null,
                    recommended_translation text,
                    description text,
                    movie_code text not null,
                    foreign key (movie_code) references movies (code)
                )
                """
            )

            # ========== 关系表 ==========

            # 影片-视频关系表
            cursor.execute(
                """
                create table if not exists movie_videos(
                    movie_code text,
                    video_sha256 text,
                    primary key (movie_code, video_sha256),
                    foreign key (movie_code) references movies (code),
                    foreign key (video_sha256) references videos (sha256)
                )
                """
            )

            # 影片-类别关系表
            cursor.execute(
                """
                create table if not exists movie_categories(
                    movie_code text,
                    category_ja text,
                    primary key (movie_code, category_ja),
                    foreign key (movie_code) references movies (code),
                    foreign key (category_ja) references categories (name_ja)
                )
                """
            )

            # 演员-电影关系表（统一处理男演员和女演员）
            cursor.execute(
                """
                create table if not exists act_in(
                    movie_code text,
                    actor_id text,
                    primary key (movie_code, actor_id),
                    foreign key (movie_code) references movies (code),
                    foreign key (actor_id) references actors (actor_id)
                )
                """
            )

            # ========== 创建索引优化查询性能 ==========

            # 视频文件路径索引
            cursor.execute(
                "create index if not exists idx_videos_absolute_path on videos(absolute_path)"
            )
            cursor.execute(
                "create index if not exists idx_videos_filename on videos(filename)"
            )

            # 演员相关索引
            cursor.execute(
                "create index if not exists idx_actor_names_actor_id on actor_names(actor_id)"
            )
            cursor.execute(
                "create index if not exists idx_actors_gender on actors(gender)"
            )
            cursor.execute(
                "create index if not exists idx_actors_current_name on actors(current_name)"
            )

            # 关系表索引
            cursor.execute(
                "create index if not exists idx_movie_videos_movie_code on movie_videos(movie_code)"
            )
            cursor.execute(
                "create index if not exists idx_movie_videos_video_sha256 on movie_videos(video_sha256)"
            )
            cursor.execute(
                "create index if not exists idx_movie_categories_movie_code on movie_categories(movie_code)"
            )
            cursor.execute(
                "create index if not exists idx_act_in_movie_code on act_in(movie_code)"
            )
            cursor.execute(
                "create index if not exists idx_act_in_actor_id on act_in(actor_id)"
            )

            # 术语表索引
            cursor.execute(
                "create index if not exists idx_terms_movie_code on terms(movie_code)"
            )
            cursor.execute(
                "create index if not exists idx_terms_origin on terms(origin)"
            )

    def get_metadata(
        self, movie_code: str, cursor: Optional[sqlite3.Cursor] = None
    ) -> Metadata | None:
        """从数据库查询影片元数据。

        Args:
            movie_code (str): 影片番号
            cursor (Optional[sqlite3.Cursor]): 数据库游标，如果为None则内部创建

        Returns:
            Metadata | None: 元数据对象，如果不存在则返回 None
        """
        internal_cursor = False
        if cursor is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            internal_cursor = True

        try:
            # 1. 查询影片核心信息
            cursor.execute(
                """
                select title_ja, title_zh, synopsis_ja, synopsis_zh, release_date, director_ja, studio_ja
                from movies where code = ?
                """,
                (movie_code,),
            )
            movie_row = cursor.fetchone()

            # 如果影片不存在，返回 None
            if not movie_row:
                return None

            # 处理外部cursor可能返回tuple的情况
            if isinstance(movie_row, tuple):
                # 如果是tuple，按索引访问
                (
                    title_ja,
                    title_zh,
                    synopsis_ja,
                    synopsis_zh,
                    release_date,
                    director_ja,
                    studio_ja,
                ) = movie_row
            else:
                # 如果是Row对象，按列名访问
                title_ja = movie_row["title_ja"]
                title_zh = movie_row["title_zh"]
                synopsis_ja = movie_row["synopsis_ja"]
                synopsis_zh = movie_row["synopsis_zh"]
                release_date = movie_row["release_date"]
                director_ja = movie_row["director_ja"]
                studio_ja = movie_row["studio_ja"]

            # 如果影片存在但没有任何元数据，也返回 None
            if not any([title_ja, director_ja, studio_ja]):
                return None

            # 2. 构建 Metadata 对象
            from domain.subtitle import BilingualText

            metadata = Metadata()

            # 标题
            if title_ja:
                metadata.title = BilingualText(original=title_ja, translated=title_zh)

            # 发行日期
            metadata.release_date = release_date

            # 导演
            if director_ja:
                cursor.execute(
                    "select name_zh from directors where name_ja = ?",
                    (director_ja,),
                )
                director_row = cursor.fetchone()
                metadata.director = BilingualText(
                    original=director_ja,
                    translated=(
                        director_row["name_zh"]
                        if director_row and isinstance(director_row, dict)
                        else None
                    ),
                )

            # 制作商
            if studio_ja:
                cursor.execute(
                    "select name_zh from studios where name_ja = ?",
                    (studio_ja,),
                )
                studio_row = cursor.fetchone()
                metadata.studio = BilingualText(
                    original=studio_ja,
                    translated=(
                        studio_row["name_zh"]
                        if studio_row and isinstance(studio_row, dict)
                        else None
                    ),
                )

            # 简介
            if synopsis_ja:
                metadata.synopsis = BilingualText(
                    original=synopsis_ja,
                    translated=synopsis_zh,
                )

            # 3. 查询关联的演员和类别

            # 类别
            cursor.execute(
                """
                           SELECT c.name_ja, c.name_zh
                           FROM movie_categories mc
                                    JOIN categories c ON mc.category_ja = c.name_ja
                           WHERE mc.movie_code = ?
                """,
                (movie_code,),
            )
            categories_rows = cursor.fetchall()
            if categories_rows:
                metadata.categories = [
                    BilingualText(original=row["name_ja"], translated=row["name_zh"])
                    for row in categories_rows
                ]

            # 演员 - 修复查询逻辑
            cursor.execute(
                """
                select a.actor_id, a.current_name, a.gender, an.name_ja, an.name_zh
                from act_in as ai
                join actors as a on ai.actor_id = a.actor_id
                left join actor_names as an on ai.actor_id = an.actor_id
                where ai.movie_code = ?
                order by a.actor_id;
                """,
                (movie_code,),
            )
            actors_rows = cursor.fetchall()
            for actor_id, group in itertools.groupby(
                actors_rows, lambda row: row["actor_id"]
            ):
                rows = list(group)
                first_row = rows[0]
                current_name = first_row["current_name"]
                gender = first_row["gender"]
                actor = Actor(current_name=current_name, all_names=[])
                for row in rows:
                    if row["name_ja"]:  # 确保名字不为空
                        actor.all_names.append(
                            BilingualText(
                                original=row["name_ja"], translated=row["name_zh"]
                            )
                        )
                if gender == "male":
                    metadata.actors.append(actor)
                else:
                    metadata.actresses.append(actor)

            return metadata

        finally:
            if internal_cursor:
                conn.close()

    def register_movie(self, movie: Movie, cursor: Optional[sqlite3.Cursor] = None):
        internal_cursor = False
        if cursor is None:
            cursor = self.get_cursor(commit=True).__enter__()
            internal_cursor = True

        try:
            cursor.execute(
                "INSERT OR IGNORE INTO movies (code) VALUES (?)", (movie.code,)
            )
            for video in movie.videos:
                cursor.execute(
                    """
                               INSERT
                               OR IGNORE INTO videos (sha256, absolute_path, filename, suffix)
                VALUES (?, ?, ?, ?)
                    """,
                    (video.sha256, video.absolute_path, video.filename, video.suffix),
                )
                cursor.execute(
                    """
                               INSERT
                               OR IGNORE INTO movie_videos (movie_code, video_sha256)
                VALUES (?, ?)
                    """,
                    (movie.code, video.sha256),
                )
            if internal_cursor:
                # 如果是内部创建的cursor，需要在这里提交
                conn = sqlite3.connect(self.db_path)
                conn.commit()
                conn.close()
        except:
            if internal_cursor:
                # 如果是内部创建的cursor，需要手动处理连接
                pass
            raise

    def update_movie(self, movie: Movie, cursor: Optional[sqlite3.Cursor] = None):
        """
        更新影片的元数据信息。

        此方法将Movie对象的元数据保存到数据库的多个表中：
        1. 更新movies表中的核心字段（标题、简介、发行日期、术语）
        2. 插入或获取元数据实体（导演、制作商、类别、演员）
        3. 建立影片与元数据实体的关联关系

        Args:
            movie (Movie): 包含完整元数据的Movie对象
            cursor (Optional[sqlite3.Cursor]): 数据库游标，如果为None则内部创建
        """
        internal_cursor = False
        if cursor is None:
            cursor = self.get_cursor(commit=True).__enter__()
            internal_cursor = True

        try:
            metadata = movie.metadata

            # 准备要更新的字段
            title_ja = metadata.title.original if metadata and metadata.title else None
            title_zh = (
                metadata.title.translated if metadata and metadata.title else None
            )
            synopsis_ja = (
                metadata.synopsis.original if metadata and metadata.synopsis else None
            )
            synopsis_zh = (
                metadata.synopsis.translated if metadata and metadata.synopsis else None
            )
            director_ja = (
                metadata.director.original if metadata and metadata.director else None
            )
            studio_ja = (
                metadata.studio.original if metadata and metadata.studio else None
            )
            release_date = metadata.release_date if metadata else None

            # 1. 更新movies表的核心字段（修复WHERE子句）
            cursor.execute(
                """
                           UPDATE movies
                           SET title_ja     = ?,
                               title_zh     = ?,
                               synopsis_ja  = ?,
                               synopsis_zh  = ?,
                               director_ja  = ?,
                               studio_ja    = ?,
                               release_date = ?
                           WHERE code = ?
                           """,
                (
                    title_ja,
                    title_zh,
                    synopsis_ja,
                    synopsis_zh,
                    director_ja,
                    studio_ja,
                    release_date,
                    movie.code,
                ),
            )

            # 如果没有metadata，只更新terms后就返回
            if not metadata:
                return

            # 2. 处理导演
            if metadata.director:
                self._get_or_create_entity(
                    cursor,
                    "directors",
                    metadata.director.original,
                    metadata.director.translated,
                )

            # 3. 处理制作商
            if metadata.studio:
                self._get_or_create_entity(
                    cursor,
                    "studios",
                    metadata.studio.original,
                    metadata.studio.translated,
                )

            # 4. 处理类别
            if metadata.categories:
                # 先清除旧的关联（修复表名）
                cursor.execute(
                    "delete from movie_categories where movie_code = ?", (movie.code,)
                )
                # 添加新的关联
                for category in metadata.categories:
                    category_ja = (
                        category.original
                        if hasattr(category, "original")
                        else str(category)
                    )
                    category_zh = (
                        category.translated if hasattr(category, "translated") else None
                    )

                    self._get_or_create_entity(
                        cursor, "categories", category_ja, category_zh
                    )
                    cursor.execute(
                        """
                                   INSERT
                                   OR IGNORE INTO movie_categories (movie_code, category_ja)
                                   VALUES (?, ?)
                        """,
                        (movie.code, category_ja),
                    )

            # 5. 处理男演员和女演员
            if metadata.actors:
                self._handle_actors(movie, "male", cursor)
            if metadata.actresses:
                self._handle_actors(movie, "female", cursor)

            # 6. 处理术语
            if movie.terms:
                self.update_terms(movie, cursor)

        finally:
            if internal_cursor:
                pass  # 上下文管理器会自动处理连接

    def _get_or_create_entity(
        self, cursor: sqlite3.Cursor, table_name: str, name_ja: str, name_zh: str = None
    ):
        """
        获取或创建元数据实体（导演、制作商、类别、演员名等）。

        如果实体已存在，更新其中文翻译；否则创建新实体。

        Args:
            cursor: 数据库游标
            table_name (str): 表名
            name_ja (str): 日文名称（主键）
            name_zh (str): 中文名称（可选）
        """
        if not name_ja:
            return

        # 使用INSERT OR REPLACE来插入或更新
        # 如果name_ja已存在，且提供了name_zh，则更新name_zh
        # 如果name_ja不存在，则插入新记录
        if name_zh:
            cursor.execute(
                f"""
                           INSERT INTO {table_name} (name_ja, name_zh)
                           VALUES (?, ?)
                           ON CONFLICT(name_ja) DO UPDATE SET name_zh = excluded.name_zh
                           """,
                (name_ja, name_zh),
            )
        else:
            # 如果没有提供name_zh，只在不存在时插入
            cursor.execute(
                f"""
                           INSERT OR IGNORE INTO {table_name} (name_ja, name_zh)
                           VALUES (?, NULL)
                           """,
                (name_ja,),
            )

    def get_entity(
        self,
        entity_type: MetadataType,
        original_name: str,
        cursor: Optional[sqlite3.Cursor] = None,
    ) -> str | None:
        """
        查询元数据实体的翻译。

        支持查询所有类型的元数据实体，包括：
        - TITLE/SYNOPSIS: 从movies表查询
        - DIRECTOR/ACTOR/ACTRESS/CATEGORY/STUDIO: 从对应实体表查询

        Args:
            entity_type (MetadataType): 实体类型
            original_name (str): 日文原文
            cursor (Optional[sqlite3.Cursor]): 数据库游标，如果为None则内部创建

        Returns:
            str | None: 中文翻译，如果不存在则返回None
        """
        if not original_name:
            return None

        internal_cursor = False
        if cursor is None:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            internal_cursor = True

        try:
            # TITLE和SYNOPSIS从movies表查询（修复表名）
            if entity_type == MetadataType.TITLE:
                cursor.execute(
                    "SELECT title_zh FROM movies WHERE title_ja = ?", (original_name,)
                )
                row = cursor.fetchone()
                return row[0] if row and row[0] else None
            elif entity_type == MetadataType.SYNOPSIS:
                cursor.execute(
                    "SELECT synopsis_zh FROM movies WHERE synopsis_ja = ?",
                    (original_name,),
                )
                row = cursor.fetchone()
                return row[0] if row and row[0] else None
            else:
                # 其他实体从对应表查询
                table_map = {
                    MetadataType.DIRECTOR: "directors",
                    MetadataType.ACTOR: "actor_names",
                    MetadataType.CATEGORY: "categories",
                    MetadataType.STUDIO: "studios",
                }
                table_name = table_map.get(entity_type)
                if not table_name:
                    return None

                cursor.execute(
                    f"SELECT name_zh FROM {table_name} WHERE name_ja = ?",
                    (original_name,),
                )
                row = cursor.fetchone()
                return row[0] if row and row[0] else None
        finally:
            if internal_cursor:
                conn.close()

    def get_movie(
        self, movie_code: str, cursor: Optional[sqlite3.Cursor] = None
    ) -> Movie | None:
        """
        根据电影番号从清单中获取完整的Movie对象。

        Args:
            movie_code (str): 电影番号
            cursor (Optional[sqlite3.Cursor]): 数据库游标，如果为None则内部创建

        Returns:
            Movie | None: Movie对象，如果不存在则返回None
        """
        internal_cursor = False
        if cursor is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            internal_cursor = True

        try:
            # 1. 查询影片是否存在（修复表名）
            cursor.execute("SELECT * FROM movies WHERE code = ?", (movie_code,))
            movie_row = cursor.fetchone()

            if not movie_row:
                return None

            # 2. 创建Movie对象
            movie = Movie(code=movie_code)

            # 3. 加载元数据
            movie.metadata = self.get_metadata(movie_code, cursor)

            # 4. 加载术语列表
            cursor.execute(
                """
            select origin, recommended_translation, description
            from terms where movie_code = ?
            """,
                (movie.code,),
            )
            term_rows = cursor.fetchall()
            for row in term_rows:
                term: Term = {
                    "japanese": row["origin"],
                    "recommended_chinese": row["recommended_translation"],
                    "description": row["description"],
                }
                movie.terms.append(term)

            # 5. 查询并加载关联的视频（修复表名）
            cursor.execute(
                """
                           SELECT v.sha256
                           FROM movie_videos mv
                                    JOIN videos v ON mv.video_sha256 = v.sha256
                           WHERE mv.movie_code = ?
                """,
                (movie_code,),
            )
            video_rows = cursor.fetchall()

            for video_row in video_rows:
                video = self.get_video(video_row["sha256"], cursor)
                if video:
                    movie.videos.append(video)

            return movie

        finally:
            if internal_cursor:
                conn.close()

    def get_video(
        self, sha256: str, cursor: Optional[sqlite3.Cursor] = None
    ) -> Video | None:
        """
        根据SHA256哈希值从清单中获取完整的Video对象。

        Args:
            sha256 (str): 视频文件的SHA256哈希值
            cursor (Optional[sqlite3.Cursor]): 数据库游标，如果为None则内部创建

        Returns:
            Video | None: Video对象，如果不存在则返回None
        """
        internal_cursor = False
        if cursor is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            internal_cursor = True

        try:
            # 查询视频基本信息（修复表名）
            cursor.execute("SELECT * FROM videos WHERE sha256 = ?", (sha256,))
            row = cursor.fetchone()

            if not row:
                return None

            # 创建Video对象
            video = Video(
                sha256=row["sha256"],
                filename=row["filename"],
                suffix=row["suffix"],
                absolute_path=row["absolute_path"],
            )

            # 加载流水线状态和副产品
            for phase in self.video_phases:
                if phase not in self.phase_to_column:
                    continue

                status_col, path_col = self.phase_to_column[phase]

                # 加载状态 - 修复枚举值处理
                if status_col and row[status_col]:
                    try:
                        # StageStatus枚举值是字符串，直接存储和读取
                        status_str = row[status_col]
                        video.status[phase] = StageStatus(status_str)
                    except (ValueError, TypeError):
                        video.status[phase] = StageStatus.PENDING
                else:
                    video.status[phase] = StageStatus.PENDING

                # 加载副产品路径
                if path_col and row[path_col]:
                    video.by_products[phase] = row[path_col]

            return video

        finally:
            if internal_cursor:
                conn.close()

    def update_video_location(
        self,
        video: Video,
        filename: str,
        new_absolute_path: str,
        cursor: Optional[sqlite3.Cursor] = None,
    ):
        internal_cursor = False
        if cursor is None:
            cursor = self.get_cursor(commit=True).__enter__()
            internal_cursor = True

        try:
            # 修复表名
            cursor.execute(
                """
                           UPDATE videos
                           SET absolute_path = ?
                           WHERE sha256 = ?
                """,
                (new_absolute_path, video.sha256),
            )
            cursor.execute(
                """
                           UPDATE videos
                           SET filename = ?
                           WHERE sha256 = ?
                """,
                (filename, video.sha256),
            )
        finally:
            if internal_cursor:
                pass  # 上下文管理器会自动处理连接

    def update_video(self, video: Video, cursor: Optional[sqlite3.Cursor] = None):
        internal_cursor = False
        if cursor is None:
            cursor = self.get_cursor(commit=True).__enter__()
            internal_cursor = True

        try:
            set_clauses = []
            params = []
            for phase, (status_col, path_col) in self.phase_to_column.items():
                if status_col:
                    status = video.status.get(phase)
                    if status:
                        set_clauses.append(f"{status_col} = ?")
                        params.append(status.value)  # StageStatus枚举的value是字符串
                if path_col:
                    path = video.by_products.get(phase)
                    if path:
                        set_clauses.append(f"{path_col} = ?")
                        params.append(path)

            if not set_clauses:
                return  # Nothing to update

            # 修复表名
            sql = f"UPDATE videos SET {', '.join(set_clauses)} WHERE sha256 = ?"
            params.append(video.sha256)

            cursor.execute(sql, tuple(params))
        finally:
            if internal_cursor:
                pass  # 上下文管理器会自动处理连接

    def set_video_status(self, video: Video, cursor: Optional[sqlite3.Cursor] = None):
        internal_cursor = False
        if cursor is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            internal_cursor = True

        try:
            # 修复表名
            cursor.execute("SELECT * FROM videos WHERE sha256 = ?", (video.sha256,))
            row = cursor.fetchone()
            if not row:
                return

            # 1. 根据清单文件中的状态更新video.status和video.by_products
            for phase in self.video_phases:
                if phase not in self.phase_to_column:
                    continue

                status_col, path_col = self.phase_to_column[phase]

                # 修复状态读取逻辑
                if status_col and row[status_col]:
                    try:
                        status_str = row[status_col]
                        video.status[phase] = StageStatus(status_str)
                    except (ValueError, TypeError):
                        video.status[phase] = StageStatus.PENDING
                else:
                    video.status[phase] = StageStatus.PENDING

                path = row[path_col] if path_col and row[path_col] else None
                if path:
                    video.by_products[phase] = path

            # 2. 检查文件是否存在，并根据最终产物状态决定是否重置
            final_product_path_col = self.phase_to_column[
                PiplinePhase.BILINGUAL_SUBTITLE
            ][1]
            final_product_path = row[final_product_path_col]
            final_product_exists = (
                final_product_path and Path(final_product_path).exists()
            )

            if final_product_exists:
                return

            # 如果最终的双语字幕不存在，则检查中间产物，并重置状态
            for i, phase in enumerate(self.video_phases):
                path = video.by_products.get(phase)
                if path is None or not Path(path).exists():
                    for subsequent_phase in self.video_phases[i:]:
                        video.status[subsequent_phase] = StageStatus.PENDING
                        if subsequent_phase in video.by_products:
                            del video.by_products[subsequent_phase]
                    break
        finally:
            if internal_cursor:
                conn.close()

    def _get_or_create_actor_id(self, actor: Actor, cursor: sqlite3.Cursor) -> str:
        """
        在数据库中寻找演员ID，使用UUID

        Args:
            actor: 演员类实例。
            cursor: 数据库游标。

        Returns:
            str: 演员的UUID。
        """
        for name in actor.all_names:
            cursor.execute(
                """
                select actor_id from actor_names where name_ja = ?
            """,
                (name.original,),
            )
            row = cursor.fetchone()
            if row:
                return row[0]
        # 如果没有的话新建一个UUID
        return str(uuid.uuid4())

    def _handle_actors(
        self, movie: Movie, gender: Literal["male", "female"], cursor: sqlite3.Cursor
    ):
        """处理演员信息，使用统一的演员表和UUID ID"""
        # 根据性别选择对应的演员列表
        actors_list = (
            movie.metadata.actors if gender == "male" else movie.metadata.actresses
        )

        # 清除旧的关联
        cursor.execute("DELETE FROM act_in WHERE movie_code = ?", (movie.code,))

        for actor in actors_list:
            actor_id = self._get_or_create_actor_id(actor, cursor)

            # 插入或更新演员基本信息
            cursor.execute(
                """
                insert or replace into actors (actor_id, current_name, gender)
                values (?, ?, ?)
                """,
                (actor_id, actor.current_name, gender),
            )

            # 建立电影与演员的关系
            cursor.execute(
                """
                insert or ignore into act_in (movie_code, actor_id)
                values (?, ?)
                """,
                (movie.code, actor_id),
            )

            # 插入演员的所有名字
            for name in actor.all_names:
                cursor.execute(
                    """
                    insert or replace into actor_names (name_ja, name_zh, actor_id)
                    values (?, ?, ?)
                    """,
                    (name.original, name.translated, actor_id),
                )

    def update_terms(self, movie: Movie, cursor: Optional[sqlite3.Cursor] = None):
        internal_cursor = False
        if cursor is None:
            cursor = self.get_cursor(commit=True).__enter__()
            internal_cursor = True

        try:
            # 先删除旧的术语
            cursor.execute("DELETE FROM terms WHERE movie_code = ?", (movie.code,))

            # 插入新的术语
            for term in movie.terms:
                cursor.execute(
                    """
                    insert into terms (origin, recommended_translation, description, movie_code)
                    values (?, ?, ?, ?)
                    """,
                    (
                        term["japanese"],
                        term["recommended_chinese"],
                        term["description"],
                        movie.code,
                    ),
                )
        finally:
            if internal_cursor:
                pass  # 上下文管理器会自动处理连接
