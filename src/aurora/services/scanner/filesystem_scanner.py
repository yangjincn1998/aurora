from pathlib import Path
from typing import List

from aurora_scraper.extractor.extractor import VideoInfoExtractor
from aurora_scraper.models import JavMovie
from aurora_scraper.utils.video_iterate_utils import iterate_videos
from sqlalchemy.orm import Session

from aurora.orms.models import Movie, Video, Actor, Director, Studio, Category
from aurora.utils.file_utils import sample_and_calculate_sha256
from aurora.utils.logger import get_logger

logger = get_logger(__name__)


class LibraryScanner:
    def __init__(
            self,
            session: Session,
            extractor: VideoInfoExtractor,
    ):
        self.session = session
        self.extractor = extractor

    def scan_directory(self, root_path: Path) -> List[Movie]:
        if not root_path.exists():
            raise FileNotFoundError("File not found: %s", str(root_path))
        if not root_path.is_dir():
            raise ValueError("Not a directory: %s", str(root_path))

        try:
            video_files = iterate_videos(root_path)
        except (FileNotFoundError, IOError) as e:
            logger.exception("Error scanning directory: %s", root_path)
            raise e

        scanned_movies = set()
        for file_path in video_files:
            try:
                file_hash = sample_and_calculate_sha256(str(file_path))
                label, number, movie_info = self.extractor.extract_video_metadata(
                    file_path.name
                )
                video = self._sync_video_to_db(file_path, file_hash, label, number)
                if movie_info and video.movie:
                    scanned_movies.add(video.movie)
                    # 每一次提取都有可能提取到上次没有提取到的信息，故而选择对每次提取结果都更新
                    self._update_movie_info(video.movie, movie_info)
                # 更新 extractor 的label以实现自学习
                if label:
                    self.extractor.learn_label(label)
            except (FileNotFoundError, IOError):
                logger.exception("Failed to process video: %s", str(file_path))
                continue
        return list(scanned_movies)

    def _sync_video_path(self, file_path: Path, video: Video):
        if video.absolute_path != str(file_path):
            logger.info("Video moved: %s -> %s", video.filename, file_path.name)
            video.update_video_absolute_path(file_path, self.session)
            file_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            logger.debug("Video exists and unchanged: %s", file_path.name)

    def _sync_video_to_db(
            self,
            file_path: Path,
            file_hash: str,
            label: str | None,
            number: str | None,
    ) -> Video:
        """
        将单个视频文件同步到数据库。
        - 如果哈希存在：更新路径（处理移动/重命名）。
        - 如果哈希不存在：创建 Video 和对应的 Movie。
        Args:
            file_path: 绝对路径
            file_hash: 文件的 hash 值
            label: 提取出的番号标签
            number: 提取出的番号数字部分
        """
        # A. 检查数据库中是否存在该视频 (根据内容哈希)
        video = Video.find_video_by_sha256(file_hash, self.session)

        if video:
            logger.info("Video exists: %s", file_path)
            self._sync_video_path(file_path, video)
        else:
            # === Case 2: 全新视频 ===
            logger.info("New video detected: %s", file_path.name)
            # 查找或创建 Movie
            if not label or not number:
                movie = Movie.get_or_create_anonymous_movie(file_hash, self.session)
            else:
                movie = Movie.get_or_create_standard_movie(label, number, self.session)
            video = Video.create_or_update_video(
                file_path, file_hash, self.session, movie
            )
        return video

    def _update_movie_info(self, movie: Movie, movie_info: JavMovie):
        if movie is None:
            raise ValueError("Movie is None")
        # 实现增量更新

        # 处理演员
        new_actors = []
        for actor_data in movie_info.actors:
            actor = Actor.create_or_get_actor(
                actor_data.current_name, actor_data.all_names, "male", self.session
            )
            new_actors.append(actor)
        for actress in movie_info.actresses:
            actress = Actor.create_or_get_actor(
                actress.current_name, actress.all_names, "female", self.session
            )
            new_actors.append(actress)

        # 处理品类
        new_categories = []
        for category_name in movie_info.categories:
            category = Category.get_or_create_category(category_name, self.session)
            new_categories.append(category)

        movie.actors = new_actors
        movie.categories = new_categories

        # 处理其他字段
        if movie_info.title:
            movie.title_ja = movie_info.title
        if movie_info.release_date:
            movie.release_date = movie_info.release_date
        if movie_info.director:
            movie.director = Director.get_or_create_director(
                movie_info.director, self.session
            )
        if movie_info.producer:
            movie.studio = Studio.get_or_create_studio(
                movie_info.producer, self.session
            )
        # 目前的 JavBus 还没有提取简介的功能
        # movie.synopsis_zh = movie_info.synopsis_zh

        self.session.add(movie)
        self.session.commit()
        return movie
