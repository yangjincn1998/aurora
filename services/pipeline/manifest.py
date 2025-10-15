import json
import sqlite3
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from domain.movie import Video, Movie
from models.enums import PiplinePhase, StageStatus


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
    def register_movie(self, movie: Movie):
        """
        注册一个movie到清单中，包括movie基本信息，包含的video，以及has_a关系
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
    def to_json(self, path: str):
        """
        将清单文件内容保存为JSON格式

        Args:
            path (str): 保存路径
        """
        pass


class SQLiteManifest(Manifest):
    """
    基于SQLite的清单文件实现类。
    Attributes:
        video_phases (List[PiplinePhase]): 支持的视频级文件流水线阶段列表
        db_path (str): SQLite数据库文件路径
    """

    def __init__(self, video_phases: List[PiplinePhase] = None,
                 db_path: str = str(Path(__file__).parent.parent / "manifest.db")):
        super().__init__(video_phases)
        self.db_path = db_path
        self.phase_to_column = {
            PiplinePhase.EXTRACT_AUDIO: ("extracted_audio_status", "extracted_audio_path"),
            PiplinePhase.DENOISE_AUDIO: ("denoised_audio_status", "denoised_audio_path"),
            PiplinePhase.TRANSCRIBE_AUDIO: ("transcribed_subtitle_status", "transcribed_subtitle_path"),
            PiplinePhase.CORRECT_SUBTITLE: ("corrected_subtitle_status", "corrected_subtitle_path"),
            PiplinePhase.TRANSLATE_SUBTITLE: ("translated_subtitle_status", "bilingual_subtitle_path"),
            # Note: bilingual path is output of translate
            PiplinePhase.BILINGUAL_SUBTITLE: ("bilingual_subtitle_status", "bilingual_subtitle_path"),
        }
        self.create_tables()

    def create_tables(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS movie
                       (
                           code
                           TEXT
                           PRIMARY
                           KEY,
                           director_ja
                           TEXT,
                           director_zh
                           TEXT,
                           title_ja
                           TEXT,
                           title_zh
                           TEXT,
                           release_date
                           TEXT,
                           studio_ja
                           TEXT,
                           studio_zh
                           TEXT,
                           synopsis_ja
                           TEXT,
                           synopsis_zh
                           TEXT,
                           categories_ja
                           TEXT,
                           categories_zh
                           TEXT,
                           actors_ja
                           TEXT,
                           actors_zh
                           TEXT,
                           actresses_ja
                           TEXT,
                           actresses_zh
                           TEXT
                       )
                       """)
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
        conn.commit()
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
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            # Assuming movie object has attributes like director_ja, title_zh etc.
            # Based on the DB schema.
            cursor.execute("""
                           UPDATE movie
                           SET director_ja   = ?,
                               director_zh   = ?,
                               title_ja      = ?,
                               title_zh      = ?,
                               release_date  = ?,
                               studio_ja     = ?,
                               studio_zh     = ?,
                               synopsis_ja   = ?,
                               synopsis_zh   = ?,
                               categories_ja = ?,
                               categories_zh = ?,
                               actors_ja     = ?,
                               actors_zh     = ?,
                               actresses_ja  = ?,
                               actresses_zh  = ?
                           WHERE code = ?
                           """, (
                               getattr(movie, 'director_ja', None),
                               getattr(movie, 'director_zh', None),
                               getattr(movie, 'title_ja', None),
                               getattr(movie, 'title_zh', None),
                               getattr(movie, 'release_date', None),
                               getattr(movie, 'studio_ja', None),
                               getattr(movie, 'studio_zh', None),
                               getattr(movie, 'synopsis_ja', None),
                               getattr(movie, 'synopsis_zh', None),
                               json.dumps(getattr(movie, 'categories_ja', [])),
                               json.dumps(getattr(movie, 'categories_zh', [])),
                               json.dumps(getattr(movie, 'actors_ja', [])),
                               json.dumps(getattr(movie, 'actors_zh', [])),
                               json.dumps(getattr(movie, 'actresses_ja', [])),
                               json.dumps(getattr(movie, 'actresses_zh', [])),
                               movie.code
                           ))
            conn.commit()
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
