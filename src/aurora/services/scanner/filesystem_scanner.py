from pathlib import Path
from typing import List

from aurora_scraper.extractor.extractor import VideoInfoExtractor
from aurora_scraper.models import JavMovie
from aurora_scraper.utils.video_iterate_utils import iterate_videos
from sqlalchemy.orm import Session

from aurora.orms.models import Movie, Video, Actor, Director, Studio, Category, Series
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

    def scan_directory(self, root_path: Path, force_extract=False) -> List[Movie]:
        """
        扫描文件夹，提取所有的文件番号，和元数据
        Args:
            root_path: 目标文件夹
            force_extract: 数据库中已有记录时，是否重新提取番号和元数据
        """
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
                video = Video.find_video_by_sha256(file_hash, self.session)
                if video:
                    self._sync_video_path(file_path, video)
                else:
                    video = Video.create_or_update_video(
                        file_path, file_hash, self.session
                    )
                movie = video.movie
                if not movie or force_extract:
                    label, number, movie_info = self.extractor.extract_video_metadata(
                        file_path.name
                    )
                    if label and number:
                        # 每一次提取都有可能提取到上次没有提取到的信息，故而选择对每次提取结果都更新
                        movie = self._create_or_update_movie_with_metadata(
                            label, number, movie_info
                        )
                    else:
                        # 没有提取到，则标记为匿名影片
                        movie = Movie.get_or_create_anonymous_movie(
                            file_hash, self.session
                        )
                    video.movie = movie
                    # 更新 extractor 的label以实现自学习
                    if label:
                        self.extractor.learn_label(label)
                else:
                    logger.info(
                        "Has extract metadata for video %s, the code is %s",
                        str(file_path),
                        movie.code,
                    )
                if not video.movie.is_anonymous:
                    scanned_movies.add(video.movie)
            except (FileNotFoundError, IOError):
                logger.exception("Failed to process video: %s", str(file_path))
                continue
        return list(scanned_movies)

    def _sync_video_path(self, file_path: Path, video: Video):
        if video.absolute_path != str(file_path):
            logger.info(
                "Video moved or renamed: %s -> %s",
                video.absolute_path,
                str(file_path.absolute()),
            )
            video.update_video_absolute_path(file_path, self.session)
        else:
            logger.debug("Video exists and unchanged: %s", file_path.name)

    def _create_or_update_movie_with_metadata(self, label, number, movie_info):
        movie = Movie.get_or_create_standard_movie(label, number, self.session)
        self._update_movie_info(movie, movie_info)
        return movie

    def _update_movie_info(self, movie: Movie, movie_info: JavMovie) -> None:
        if movie is None:
            raise ValueError("Movie is None")
        if not movie_info:
            return
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
        if movie_info.series:
            movie.series = Series.get_or_create_series(movie_info.series, self.session)
        # 目前的 JavBus 还没有提取简介的功能
        # movie.synopsis_zh = movie_info.synopsis_zh

        self.session.add(movie)
        self.session.commit()
        return
