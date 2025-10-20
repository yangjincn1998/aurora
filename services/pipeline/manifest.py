import json
import os.path
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from domain.movie import Video, Movie, Metadata
from models.enums import PiplinePhase, StageStatus, MetadataType
from utils.singleton import singleton


class Manifest(ABC):
    """
    清单文件抽象基类。
    Attributes:
        phases (List[PiplinePhase]): 支持的视频级别流水线阶段列表
    """

    def __init__(self, video_phases: List[PiplinePhase] = None):
        self.video_phases = video_phases if video_phases else [
            PiplinePhase.EXTRACT_AUDIO,
            PiplinePhase.DENOISE_AUDIO,
            PiplinePhase.TRANSCRIBE_AUDIO,
            PiplinePhase.CORRECT_SUBTITLE,
            PiplinePhase.TRANSLATE_SUBTITLE,
            PiplinePhase.BILINGUAL_SUBTITLE
        ]

    @abstractmethod
    def set_video_status(self, video: Video):
        """
        根据清单文件设置video的状态
        1.根据清单文件中by_products的路径检查文件是否存在，若不存在，且最终的双语字幕不存在，则说明用户对其不满意，将对应的阶段和后面的阶段设为PENDING.
        如果某个阶段的副产物被删除，但是双语字幕存在，则说明已经完成最后步骤。不用更改状态。
        2.根据清单文件中的状态更新video.status和video.by_products

        Args:
            video (Video): 待设置状态的视频对象
        """
        pass

    @abstractmethod
    def get_metadata(self, movie_code: str) -> Metadata | None:
        pass

    @abstractmethod
    def register_movie(self, movie: Movie):
        """
        注册一个movie到清单中，包括movie元数据信息
        """
        pass

    @abstractmethod
    def update_movie(self, movie: Movie):
        """
        用movie数据更新清单
        """
        pass

    @abstractmethod
    def update_video(self, video: Video):
        """
        用video数据更新清单
        """
        pass

    @abstractmethod
    def update_entity(self, entity_type: MetadataType, original_name: str, translated_name: str):
        """
        用元数据实体信息更新清单
        """
        pass

    @abstractmethod
    def to_json(self, path: str):
        """
        将清单文件内容保存为JSON格式

        Args:
            path (str): 保存路径
        """
        pass

    @abstractmethod
    def get_entity(self, entity_type: MetadataType, original_name: str) -> str | None:
        """
        查询清单，如果存在该元数据实体，返回其翻译名称，否则返回None
        """
        pass


@singleton
class SQLiteManifest(Manifest):
    """
    基于SQLite的清单文件实现类。
    Attributes:
        video_phases (List[PiplinePhase]): 支持的视频级文件流水线阶段列表
        db_path (str): SQLite数据库文件路径
    """

    def __init__(self, video_phases: List[PiplinePhase] = None,
                 db_path: str = os.path.join(os.getcwd(), 'data.sqlite3')):
        super().__init__(video_phases)
        self.db_path = db_path
        self.phase_to_column = {
            PiplinePhase.EXTRACT_AUDIO: ("extracted_audio_status", "extracted_audio_path"),
            PiplinePhase.DENOISE_AUDIO: ("denoised_audio_status", "denoised_audio_path"),
            PiplinePhase.TRANSCRIBE_AUDIO: ("transcribed_subtitle_status", "transcribed_subtitle_path"),
            PiplinePhase.CORRECT_SUBTITLE: ("corrected_subtitle_status", "corrected_subtitle_path"),
            PiplinePhase.TRANSLATE_SUBTITLE: ("translated_subtitle_status", "bilingual_subtitle_path"),
            PiplinePhase.BILINGUAL_SUBTITLE: ("bilingual_subtitle_status", "bilingual_subtitle_path"),
        }
        self.create_tables()

    def create_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # ========== 核心表 ==========

        # 影片表 - 只保留核心字段
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS movie
                       (
                           code
                           TEXT
                           PRIMARY
                           KEY,
                           title_ja
                           TEXT,
                           title_zh
                           TEXT,
                           release_date
                           TEXT,
                           director_ja
                           TEXT,
                           studio_ja
                           TEXT,
                           synopsis_ja
                           TEXT,
                           synopsis_zh
                           TEXT,
                           terms
                           TEXT,-- JSON格式存储术语列表
                           Foreign
                           KEY
                       (
                           director_ja
                       ) REFERENCES director
                       (
                           name_ja
                       ),
                           Foreign KEY
                       (
                           studio_ja
                       ) REFERENCES studio
                       (
                           name_ja
                       )
                       )
                       """)

        # 视频文件表
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS video
                       (
                           sha256
                           TEXT
                           PRIMARY
                           KEY,
                           absolute_path
                           TEXT
                           UNIQUE,
                           filename
                           TEXT,
                           suffix
                           TEXT,
                           is_deleted
                           INTEGER
                           NOT
                           NULL
                           DEFAULT
                           0,
                           extracted_audio_status
                           TEXT,
                           extracted_audio_path
                           TEXT,
                           denoised_audio_status
                           TEXT,
                           denoised_audio_path
                           TEXT,
                           transcribed_subtitle_status
                           TEXT,
                           transcribed_subtitle_path
                           TEXT,
                           corrected_subtitle_status
                           TEXT,
                           corrected_subtitle_path
                           TEXT,
                           translated_subtitle_status
                           TEXT,
                           bilingual_subtitle_path
                           TEXT,
                           bilingual_subtitle_status
                           TEXT
                       )
                       """)

        # 影片-视频关系表
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS has_a
                       (
                           movie_code
                           TEXT,
                           video_sha256
                           TEXT,
                           PRIMARY
                           KEY
                       (
                           movie_code,
                           video_sha256
                       ),
                           FOREIGN KEY
                       (
                           movie_code
                       ) REFERENCES movie
                       (
                           code
                       ),
                           FOREIGN KEY
                       (
                           video_sha256
                       ) REFERENCES video
                       (
                           sha256
                       )
                           )
                       """)

        # ========== 元数据实体表 ==========

        # 导演表
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS director
                       (
                           name_ja
                           TEXT
                           PRIMARY
                           KEY,
                           name_zh
                           TEXT
                       )
                       """)

        # 制作商表
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS studio
                       (
                           name_ja
                           TEXT
                           PRIMARY
                           KEY,
                           name_zh
                           TEXT
                       )
                       """)

        # 类别表
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS category
                       (
                           name_ja
                           TEXT
                           PRIMARY
                           KEY,
                           name_zh
                           TEXT
                       )
                       """)

        # 演员表（男）
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS actor
                       (
                           name_ja
                           TEXT
                           Primary
                           Key,
                           name_zh
                           TEXT
                       )
                       """)

        # 演员表（女）
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS actress
                       (
                           name_ja
                           TEXT
                           Primary
                           Key,
                           name_zh
                           TEXT
                       )
                       """)

        # ========== 关系表 ==========

        # 影片-类别关系表
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS movie_category
                       (
                           movie_code
                           TEXT,
                           category_ja
                           TEXT,
                           PRIMARY
                           KEY
                       (
                           movie_code,
                           category_ja
                       ),
                           FOREIGN KEY
                       (
                           movie_code
                       ) REFERENCES movie
                       (
                           code
                       ),
                           FOREIGN KEY
                       (
                           category_ja
                       ) REFERENCES category
                       (
                           name_ja
                       )
                           )
                       """)

        # 影片-男演员关系表
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS movie_actor
                       (
                           movie_code
                           TEXT,
                           actor_ja
                           TEXT,
                           PRIMARY
                           KEY
                       (
                           movie_code,
                           actor_ja
                       ),
                           FOREIGN KEY
                       (
                           movie_code
                       ) REFERENCES movie
                       (
                           code
                       ),
                           FOREIGN KEY
                       (
                           actor_ja
                       ) REFERENCES actor
                       (
                           name_ja
                       )
                           )
                       """)

        # 影片-女演员关系表
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS movie_actress
                       (
                           movie_code
                           TEXT,
                           actress_ja
                           TEXT,
                           PRIMARY
                           KEY
                       (
                           movie_code,
                           actress_ja
                       ),
                           FOREIGN KEY
                       (
                           movie_code
                       ) REFERENCES movie
                       (
                           code
                       ),
                           FOREIGN KEY
                       (
                           actress_ja
                       ) REFERENCES actress
                       (
                           name_ja
                       )
                           )
                       """)
        conn.commit()
        conn.close()

    def get_metadata(self, movie_code: str) -> Metadata | None:
        """从数据库查询影片元数据。

        Args:
            movie_code (str): 影片番号

        Returns:
            Metadata | None: 元数据对象，如果不存在则返回 None
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            # 1. 查询影片核心信息
            cursor.execute("""
                           SELECT title_ja, title_zh, release_date, director_ja, studio_ja, synopsis_ja, synopsis_zh
                           FROM movie
                           WHERE code = ?
                           """, (movie_code,))
            movie_row = cursor.fetchone()

            # 如果影片不存在，返回 None
            if not movie_row:
                return None

            # 如果影片存在但没有任何元数据，也返回 None
            if not any([movie_row['title_ja'], movie_row['director_ja'], movie_row['studio_ja']]):
                return None

            # 2. 构建 Metadata 对象
            from domain.subtitle import BilingualText

            metadata = Metadata()

            # 标题
            if movie_row['title_ja']:
                metadata.title = BilingualText(
                    original=movie_row['title_ja'],
                    translated=movie_row['title_zh']
                )

            # 发行日期
            metadata.release_date = movie_row['release_date']

            # 导演
            if movie_row['director_ja']:
                cursor.execute("SELECT name_zh FROM director WHERE name_ja = ?", (movie_row['director_ja'],))
                director_row = cursor.fetchone()
                metadata.director = BilingualText(
                    original=movie_row['director_ja'],
                    translated=director_row['name_zh'] if director_row else None
                )

            # 制作商
            if movie_row['studio_ja']:
                cursor.execute("SELECT name_zh FROM studio WHERE name_ja = ?", (movie_row['studio_ja'],))
                studio_row = cursor.fetchone()
                metadata.studio = BilingualText(
                    original=movie_row['studio_ja'],
                    translated=studio_row['name_zh'] if studio_row else None
                )

            # 简介
            if movie_row['synopsis_ja']:
                metadata.synopsis = BilingualText(
                    original=movie_row['synopsis_ja'],
                    translated=movie_row['synopsis_zh']
                )

            # 3. 查询关联的演员和类别

            # 类别
            cursor.execute("""
                           SELECT c.name_ja, c.name_zh
                           FROM movie_category mc
                                    JOIN category c ON mc.category_ja = c.name_ja
                           WHERE mc.movie_code = ?
                           """, (movie_code,))
            categories_rows = cursor.fetchall()
            if categories_rows:
                metadata.categories = [
                    BilingualText(original=row['name_ja'], translated=row['name_zh'])
                    for row in categories_rows
                ]

            # 男演员
            cursor.execute("""
                           SELECT a.name_ja, a.name_zh
                           FROM movie_actor ma
                                    JOIN actor a ON ma.actor_ja = a.name_ja
                           WHERE ma.movie_code = ?
                           """, (movie_code,))
            actors_rows = cursor.fetchall()
            if actors_rows:
                metadata.actors = [
                    BilingualText(original=row['name_ja'], translated=row['name_zh'])
                    for row in actors_rows
                ]

            # 女演员
            cursor.execute("""
                           SELECT a.name_ja, a.name_zh
                           FROM movie_actress ma
                                    JOIN actress a ON ma.actress_ja = a.name_ja
                           WHERE ma.movie_code = ?
                           """, (movie_code,))
            actresses_rows = cursor.fetchall()
            if actresses_rows:
                metadata.actresses = [
                    BilingualText(original=row['name_ja'], translated=row['name_zh'])
                    for row in actresses_rows
                ]

            return metadata

        finally:
            conn.close()

    def register_movie(self, movie: Movie):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT OR IGNORE INTO movie (code) VALUES (?)", (movie.code,))
            for video in movie.videos:
                cursor.execute("""
                               INSERT
                               OR IGNORE INTO video (sha256, absolute_path, filename, suffix)
                VALUES (?, ?, ?, ?)
                               """, (video.sha256, video.absolute_path, video.filename, video.suffix))
                cursor.execute("""
                               INSERT
                               OR IGNORE INTO has_a (movie_code, video_sha256)
                VALUES (?, ?)
                               """, (movie.code, video.sha256))
            conn.commit()
        finally:
            conn.close()

    def update_movie(self, movie: Movie):
        """
        更新影片的元数据信息。

        此方法将Movie对象的元数据保存到数据库的多个表中：
        1. 更新movie表中的核心字段（标题、简介、发行日期、术语）
        2. 插入或获取元数据实体（导演、制作商、类别、演员）
        3. 建立影片与元数据实体的关联关系

        Args:
            movie (Movie): 包含完整元数据的Movie对象
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            metadata = movie.metadata

            # 准备要更新的字段
            title_ja = metadata.title.original if metadata and metadata.title else None
            title_zh = metadata.title.translated if metadata and metadata.title else None
            synopsis_ja = metadata.synopsis.original if metadata and metadata.synopsis else None
            synopsis_zh = metadata.synopsis.translated if metadata and metadata.synopsis else None
            director_ja = metadata.director.original if metadata and metadata.director else None
            studio_ja = metadata.studio.original if metadata and metadata.studio else None
            release_date = metadata.release_date if metadata else None
            terms = json.dumps([term for term in movie.terms], ensure_ascii=False) if movie.terms else None

            # 1. 更新movie表的核心字段（即使metadata为None，也要更新terms）
            cursor.execute("""
                           UPDATE movie
                           SET title_ja     = ?,
                               title_zh     = ?,
                               synopsis_ja  = ?,
                               synopsis_zh  = ?,
                               director_ja  = ?,
                               studio_ja    = ?,
                               release_date = ?,
                               terms        = ?
                           WHERE code = ?
                           """,
                           (title_ja, title_zh, synopsis_ja, synopsis_zh, director_ja, studio_ja, release_date, terms,
                            movie.code))

            # 如果没有metadata，只更新terms后就返回
            if not metadata:
                conn.commit()
                return

            # 2. 处理导演
            if metadata.director:
                self._get_or_create_entity(
                    cursor, 'director',
                    metadata.director.original,
                    metadata.director.translated
                )

            # 3. 处理制作商
            if metadata.studio:
                self._get_or_create_entity(
                    cursor, 'studio',
                    metadata.studio.original,
                    metadata.studio.translated
                )

            # 4. 处理类别
            if metadata.categories:
                # 先清除旧的关联
                cursor.execute("DELETE FROM movie_category WHERE movie_code = ?", (movie.code,))
                # 添加新的关联
                for category in metadata.categories:
                    category_ja = category.original if hasattr(category, 'original') else str(category)
                    category_zh = category.translated if hasattr(category, 'translated') else None

                    self._get_or_create_entity(
                        cursor, 'category',
                        category_ja, category_zh
                    )
                    cursor.execute("""
                                   INSERT
                                   OR IGNORE INTO movie_category (movie_code, category_ja)
                                   VALUES (?, ?)
                                   """, (movie.code, category_ja))

            # 5. 处理男演员
            if metadata.actors:
                # 先清除旧的关联
                cursor.execute("DELETE FROM movie_actor WHERE movie_code = ?", (movie.code,))
                # 添加新的关联
                for actor in metadata.actors:
                    actor_ja = actor.original if hasattr(actor, 'original') else str(actor)
                    actor_zh = actor.translated if hasattr(actor, 'translated') else None

                    self._get_or_create_entity(
                        cursor, 'actor',
                        actor_ja, actor_zh
                    )
                    cursor.execute("""
                                   INSERT
                                   OR IGNORE INTO movie_actor (movie_code, actor_ja)
                                   VALUES (?, ?)
                                   """, (movie.code, actor_ja))

            # 6. 处理女演员
            if metadata.actresses:
                # 先清除旧的关联
                cursor.execute("DELETE FROM movie_actress WHERE movie_code = ?", (movie.code,))
                # 添加新的关联
                for actress in metadata.actresses:
                    actress_ja = actress.original if hasattr(actress, 'original') else str(actress)
                    actress_zh = actress.translated if hasattr(actress, 'translated') else None

                    self._get_or_create_entity(
                        cursor, 'actress',
                        actress_ja, actress_zh
                    )
                    cursor.execute("""
                                   INSERT
                                   OR IGNORE INTO movie_actress (movie_code, actress_ja)
                                   VALUES (?, ?)
                                   """, (movie.code, actress_ja))

            conn.commit()
        finally:
            conn.close()

    def _get_or_create_entity(self, cursor, table_name: str, name_ja: str, name_zh: str = None):
        """
        获取或创建元数据实体（导演、制作商、类别、演员等）。

        如果实体已存在，更新其中文翻译；否则创建新实体。

        Args:
            cursor: 数据库游标
            table_name (str): 表名（director、studio、category、actor、actress）
            name_ja (str): 日文名称（主键）
            name_zh (str): 中文名称（可选）
        """
        if not name_ja:
            return

        # 使用INSERT OR REPLACE来插入或更新
        # 如果name_ja已存在，且提供了name_zh，则更新name_zh
        # 如果name_ja不存在，则插入新记录
        if name_zh:
            cursor.execute(f"""
                           INSERT INTO {table_name} (name_ja, name_zh)
                           VALUES (?, ?)
                           ON CONFLICT(name_ja) DO UPDATE SET name_zh = excluded.name_zh
                           """, (name_ja, name_zh))
        else:
            # 如果没有提供name_zh，只在不存在时插入
            cursor.execute(f"""
                           INSERT OR IGNORE INTO {table_name} (name_ja, name_zh)
                           VALUES (?, NULL)
                           """, (name_ja,))

    def update_entity(self, entity_type: MetadataType, original_name: str, translated_name: str):
        """
        更新元数据实体的翻译。

        Args:
            entity_type (MetadataType): 实体类型
            original_name (str): 日文原文
            translated_name (str): 中文翻译
        """
        table_map = {
            MetadataType.DIRECTOR: 'director',
            MetadataType.ACTOR: 'actor',
            MetadataType.ACTRESS: 'actress',
            MetadataType.STUDIO: 'studio',
            MetadataType.CATEGORY: 'category'
        }

        table_name = table_map.get(entity_type)
        if not table_name:
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            self._get_or_create_entity(cursor, table_name, original_name, translated_name)
            conn.commit()
        finally:
            conn.close()

    def get_entity(self, entity_type: MetadataType, original_name: str) -> str | None:
        """
        查询元数据实体的翻译。

        支持查询所有类型的元数据实体，包括：
        - TITLE/SYNOPSIS: 从movie表查询
        - DIRECTOR/ACTOR/ACTRESS/CATEGORY/STUDIO: 从对应实体表查询

        Args:
            entity_type (MetadataType): 实体类型
            original_name (str): 日文原文

        Returns:
            str | None: 中文翻译，如果不存在则返回None
        """
        if not original_name:
            return None

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            # TITLE和SYNOPSIS从movie表查询
            if entity_type == MetadataType.TITLE:
                cursor.execute("SELECT title_zh FROM movie WHERE title_ja = ?", (original_name,))
                row = cursor.fetchone()
                return row[0] if row and row[0] else None
            elif entity_type == MetadataType.SYNOPSIS:
                cursor.execute("SELECT synopsis_zh FROM movie WHERE synopsis_ja = ?", (original_name,))
                row = cursor.fetchone()
                return row[0] if row and row[0] else None
            else:
                # 其他实体从对应表查询
                table_map = {
                    MetadataType.DIRECTOR: 'director',
                    MetadataType.ACTOR: 'actor',
                    MetadataType.ACTRESS: 'actress',
                    MetadataType.CATEGORY: 'category',
                    MetadataType.STUDIO: 'studio'
                }
                table_name = table_map.get(entity_type)
                if not table_name:
                    return None

                cursor.execute(f"SELECT name_zh FROM {table_name} WHERE name_ja = ?", (original_name,))
                row = cursor.fetchone()
                return row[0] if row and row[0] else None
        finally:
            conn.close()

    def update_video(self, video: Video):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            set_clauses = []
            params = []
            for phase, (status_col, path_col) in self.phase_to_column.items():
                if status_col:
                    status = video.status.get(phase)
                    if status:
                        set_clauses.append(f"{status_col} = ?")
                        params.append(status.value)
                if path_col:
                    path = video.by_products.get(phase)
                    if path:
                        set_clauses.append(f"{path_col} = ?")
                        params.append(path)

            if not set_clauses:
                return  # Nothing to update

            sql = f"UPDATE video SET {', '.join(set_clauses)} WHERE sha256 = ?"
            params.append(video.sha256)

            cursor.execute(sql, tuple(params))
            conn.commit()
        finally:
            conn.close()

    def set_video_status(self, video: Video):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM video WHERE sha256 = ?", (video.sha256,))
            row = cursor.fetchone()
            if not row:
                return

            # 1. 根据清单文件中的状态更新video.status和video.by_products
            for phase in self.video_phases:
                if phase not in self.phase_to_column:
                    continue

                status_col, path_col = self.phase_to_column[phase]

                status = StageStatus(row[status_col]) if status_col and row[status_col] else StageStatus.PENDING
                path = row[path_col] if path_col and row[path_col] else None

                video.status[phase] = status
                if path:
                    video.by_products[phase] = path

            # 2. 检查文件是否存在，并根据最终产物状态决定是否重置
            final_product_path_col = self.phase_to_column[PiplinePhase.BILINGUAL_SUBTITLE][1]
            final_product_path = row[final_product_path_col]
            final_product_exists = final_product_path and Path(final_product_path).exists()

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
            conn.close()

    def to_json(self, path: str):
        """
        将清单内容导出为JSON格式。

        导出包含所有影片、视频和元数据的完整信息。

        Args:
            path (str): 导出文件路径
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            data = {
                'movies': [],
                'videos': [],
                'metadata_entities': {
                    'directors': [],
                    'studios': [],
                    'categories': [],
                    'actors': [],
                    'actresses': []
                }
            }

            # 导出所有影片
            cursor.execute("SELECT * FROM movie")
            for row in cursor.fetchall():
                data['movies'].append(dict(row))

            # 导出所有视频
            cursor.execute("SELECT * FROM video")
            for row in cursor.fetchall():
                data['videos'].append(dict(row))

            # 导出元数据实体
            for entity_type in ['director', 'studio', 'category', 'actor', 'actress']:
                cursor.execute(f"SELECT * FROM {entity_type}")
                plural = entity_type + 's' if entity_type != 'actress' else 'actresses'
                data['metadata_entities'][plural] = [dict(row) for row in cursor.fetchall()]

            # 保存到文件
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        finally:
            conn.close()


class JsonManifest(Manifest):
    """
    基于JSON的清单文件实现类。
    Attributes:
        video_phases (List[PiplinePhase]): 支持的视频级文件流水线阶段列表
        file_path (str): 清单文件路径
        video_phases_map (Dict[PiplinePhase, str]): 流水线阶段到JSON键的映射
        phase_status_map (Dict[StageStatus, str]): 阶段状态到JSON值的映射
    """

    def __init__(self, video_phases: List[PiplinePhase] = None, file_path: str = str(Path(__file__) / "manifest.json")):
        super().__init__(video_phases)
        self.file_path = file_path
        self.video_phases_map = {
            PiplinePhase.PROCESSING_METADATA: "processing_metadata",
            PiplinePhase.EXTRACT_AUDIO: "extract_audio",
            PiplinePhase.DENOISE_AUDIO: "denoise_audio",
            PiplinePhase.TRANSCRIBE_AUDIO: "transcribe_audio",
            PiplinePhase.CORRECT_SUBTITLE: "correct_subtitle",
            PiplinePhase.TRANSLATE_SUBTITLE: "translate_subtitle",
            PiplinePhase.BILINGUAL_SUBTITLE: "bilingual_subtitle"
        }
        self.phase_status_map = {
            StageStatus.PENDING: "pending",
            StageStatus.SUCCESS: "success",
            StageStatus.FAILED: "failed"
        }

    def _get_status(self, video: Video):
        """
        从清单文件中获取video的状态信息

        Args:
            video (Video): 待获取状态的视频对象

        Returns:
            Dict[PiplinePhase, StageStatus]: video的状态字典
            Dict[PiplinePhase, Any]: video的by_products字典
        """
        try:
            with Path(self.file_path).open(encoding="utf-8") as f:
                json_content = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            json_content = {}
        video_info = json_content.get(video.filename, {})
        return video_info.get("status", {}), video_info.get("by_products", {})

    def set_video_status(self, video: Video):
        status_dict, by_products_dict = self._get_status(video)

        # 1. 根据清单文件中的状态更新video.status和video.by_products
        video.status = {PiplinePhase(phase): StageStatus(status) for phase, status in status_dict.items()}
        video.by_products = {PiplinePhase(phase): path for phase, path in by_products_dict.items()}

        # 2. 检查文件是否存在，并根据最终产物状态决定是否重置
        final_product_phase = PiplinePhase.BILINGUAL_SUBTITLE
        final_product_path = video.by_products.get(final_product_phase)
        final_product_exists = final_product_path and Path(final_product_path).exists()

        if final_product_exists:
            for phase in self.video_phases:
                video.status[phase] = StageStatus.SUCCESS
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

    def register_movie(self, movie: Movie):
        pass

    def update_movie(self, movie: Movie):
        pass

    def update_video(self, video: Video):
        pass

    def to_json(self, path: str):
        pass


if __name__ == "__main__":
    manifest = SQLiteManifest()
    manifest.to_json(str(Path(__file__).parent / "manifest.json"))
