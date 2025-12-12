import os
from pathlib import Path
from typing import List, Iterator

from sqlalchemy.orm import Session

from aurora.constants import VIDEO_SUFFIXES
from aurora.orms.models import Movie, Video
from aurora.services.code_extract.extractor import CodeExtractor
from aurora.utils.file_utils import sample_and_calculate_sha256
from aurora.utils.logger import get_logger

logger = get_logger(__name__)


class LibraryScanner:
    def __init__(self, session: Session, code_extractor: CodeExtractor):
        self.session = session
        self.extractor = code_extractor

    def scan_directory(self, root_path: str) -> List[Movie]:
        """
        扫描目录，将新发现的视频同步到数据库，并返回所有相关的 Movie 对象。
        """
        root = Path(root_path)
        if not root.exists():
            raise FileNotFoundError(f"Path not found: {root_path}")

        scanned_movies = set()

        # 1. 遍历文件系统
        for file_path in self._walk_video_files(root):
            try:
                # 2. 采样计算指纹 (SHA256)
                file_hash = sample_and_calculate_sha256(str(file_path))
                # 3. 核心逻辑：Check or Create (Upsert)
                video = self._sync_video_to_db(file_path, file_hash)

                # 收集涉及到的 Movie 对象，用于后续 Pipeline 处理
                if video.movie:
                    scanned_movies.add(video.movie)

            except FileNotFoundError or IOError:
                logger.exception(f"Error scanning file %s, skipping it...", file_path)
                continue

        # 提交所有更改
        self.session.commit()

        return list(scanned_movies)

    @staticmethod
    def _walk_video_files(root: Path) -> Iterator[Path]:
        """迭代器：递归查找视频文件"""
        for root_dir, _, files in os.walk(root):
            for file in files:
                path = Path(root_dir) / file
                if path.suffix.lower() in VIDEO_SUFFIXES:
                    yield path

    def _sync_video_to_db(self, file_path: Path, file_hash: str) -> Video:
        """
        将单个视频文件同步到数据库。
        - 如果哈希存在：更新路径（处理移动/重命名）。
        - 如果哈希不存在：创建 Video 和对应的 Movie。
        Args:
            file_path: 绝对路径
            file_hash: 文件的 hash 值
        """
        # A. 检查数据库中是否存在该视频 (根据内容哈希)
        video = Video.find_video_by_sha256(file_hash, self.session)

        if video:
            # === Case 1: 视频已存在 (可能是移动了位置) ===
            if video.absolute_path != str(file_path):
                logger.info("Video moved: %s -> %s", video.filename, file_path.name)
                video.update_video_absolute_path(file_path, self.session)
                file_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                logger.debug("Video exists and unchanged: %s", file_path.name)
        else:
            # === Case 2: 全新视频 ===
            logger.info("New video detected: %s", file_path.name)
            label, number = self.extractor.extract_av_code(file_path.name)

            # 查找或创建 Movie
            movie = Movie.get_or_create_standard_movie(label, number, self.session)
            video = Video.create_or_update_video(file_path, file_hash, self.session, movie)
        return video

    def _get_or_create_movie(
        self, av_code: str | None, file_hash: str, filename: str
    ) -> Movie:
        """根据番号查找电影，如果不存在则创建（处理匿名逻辑）"""

        if av_code:
            label, number = av_code
            movie = Movie.find_standard_movie(label, number, self.session)

            if not movie:
                movie = Movie(
                    label=label,
                    number=number,
                )
                self.session.add(movie)
        else:
            movie = Movie.find_anonymous_movie(file_hash, self.session)

            if not movie:
                movie = Movie(
                    number=file_hash,
                )
                self.session.add(movie)

        return movie
