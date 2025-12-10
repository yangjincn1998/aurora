import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from domain.movie import Movie, Video
from pipeline.base import MoviePipelineStage, VideoPipelineStage, PipelineStage
from pipeline.context import PipelineContext
from pipeline.correct import CorrectStage
from services.code_extract.extractor import CodeExtractor
from services.pipeline.database_manager import DatabaseManager
from services.translation.orchestrator import TranslateOrchestrator
from utils.file_utils import calculate_partial_sha256
from utils.logger import get_logger

logger = get_logger(__name__)


class Pipeline:
    def __init__(
        self,
        movie_stages: List[MoviePipelineStage],
        video_stages: List[VideoPipelineStage],
        code_extractor: CodeExtractor,
        database_manager: DatabaseManager,
        translator: TranslateOrchestrator,
        output_dir: str = os.path.join(os.getcwd(), "output"),
    ):
        self.movie_stages = movie_stages
        self.video_stages = video_stages
        self.all_stages = movie_stages + video_stages
        self.code_extractor = code_extractor
        self.database_manager = database_manager
        # 创建 PipelineContext，封装 database_manager
        self.context = PipelineContext(
            database_manager=database_manager,
            output_dir=output_dir,
            translator=translator,
        )

    def _get_next_stage(
        self, movie: Movie, video: Optional[Video] = None
    ) -> Optional[PipelineStage]:
        """根据实体当前状态，决定下一个要执行的阶段。"""
        target_entity = video if video else movie
        stages = self.video_stages if video else self.movie_stages

        for stage in stages:
            if stage.should_execute(target_entity, self.context):
                return stage
        return None

    def run(self, src_path: str):
        """扫描并处理所有影片。"""
        movies = self._scan(src_path)
        logger.info("扫描到 %d 部影片待处理。", len(movies))
        for movie in movies:
            # 启动该影片的处理流程（内部包含注册和状态同步）
            self._process_movie(movie)

    def _process_movie(self, movie: Movie):
        """处理单部影片，直到所有阶段完成。"""
        logger.info("开始处理影片: %s", movie.code)

        # 开始事务，整部影片处理过程中使用单一数据库连接
        self.context.begin_transaction()
        try:
            # 注册影片和其下的视频，并从数据库同步最新状态
            self.context.register_movie(movie)
            for video in movie.videos:
                self.context.set_video_status(video)

            # 处理影片级别的阶段
            while True:
                next_stage = self._get_next_stage(movie)
                if not next_stage:
                    logger.info("影片 %s 的所有影片级阶段处理完毕。", movie.code)
                    break

                logger.info(
                    "影片 %s 即将执行阶段: %s",
                    movie.code,
                    next_stage.__class__.__name__,
                )
                self.context.movie_code = movie.code
                # 生成 Langfuse 会话 ID
                session_id = movie.code + ":" + datetime.now().strftime("%Y-%m-%d")
                self.context.langfuse_session_id = session_id
                # 传递 context 给 stage
                next_stage.execute(movie, self.context)
                # 通过 context 更新 database_manager
                self.context.update_movie(movie)

            # 规范化命名（在同一事务中）
            for video in movie.videos:
                video_name = (
                    movie.code + " " + movie.metadata.title.translated
                    if movie.metadata.title.translated
                    else movie.metadata.title.original
                )
                new_abs_path = str(
                    Path(video.absolute_path).parent / (video_name + video.suffix)
                )
                if video.absolute_path != new_abs_path:
                    Path(video.absolute_path).rename(new_abs_path)
                    video.absolute_path = new_abs_path
                    video.filename = video_name
                # 同步到数据库中
                self.context.update_video_location(video, new_abs_path, video_name)

            # 处理该影片下所有视频的视频级别阶段（在同一事务中）
            for video in movie.videos:
                logger.info("开始处理视频: %s", video.filename)
                while True:
                    next_stage = self._get_next_stage(movie, video)
                    if not next_stage:
                        logger.info(
                            "视频 %s 的所有视频级阶段处理完毕。", video.filename
                        )
                        break

                    logger.info(
                        "视频 %s 即将执行阶段: %s",
                        video.filename,
                        next_stage.__class__.__name__,
                    )
                    # 传递 context 给 stage
                    next_stage.execute(movie, video, self.context)
                    # 通过 context 更新 database_manager
                    if isinstance(next_stage, CorrectStage):
                        self.context.update_terms(movie)
                    self.context.update_video(video)

            # 提交事务
            self.context.commit_transaction()
        except Exception as e:
            # 发生错误时回滚事务
            logger.exception("处理影片 %s 时发生错误", movie.code)
            self.context.rollback_transaction()
            raise

    def _scan(self, src_dir: str) -> List[Movie]:
        """
        递归地扫描目录下所有字幕视频文件，创建待处理的movie列表

        项目规约：src_path下只有av文件，且每个av文件文件名中都有av番号

        Args：
            src_dir(str): 待处理的文件目录
        Returns：
            Set[Movie]: 待处理影片集合
        Raises:
            FileNotFoundError: 传入的src_dir不是要给有效的目录名
        """
        dir_path = Path(src_dir)
        if not dir_path.is_dir():
            logger.error("Directory %s does not exist.", dir_path)
            raise FileNotFoundError(f"Directory {dir_path} does not exist.")
        video_suffixes = [
            ".mp4",
            ".mkv",
            ".avi",
            ".mov",
            ".wmv",
            ".flv",
            ".webm",
            ".mpg",
            ".mpeg",
        ]
        video_to_process = [
            file for ext in video_suffixes for file in dir_path.rglob(f"*{ext}")
        ]
        logger.info("Found %d videos.", len(video_to_process))
        movies_map: Dict[str, Movie] = {}
        for video in video_to_process:
            video_path = str(video.resolve())
            partial_hash = calculate_partial_sha256(video_path)
            if not partial_hash:
                logger.warning(
                    "Could not calculate SHA256 for %s. Skipping this file.", video.name
                )
                continue

            video_dataclass = Video(
                sha256=partial_hash,
                filename=video.stem,
                suffix=video.suffix,
                absolute_path=video_path,
            )
            # 在扫描阶段不再需要 set_video_status，统一移到 run 方法中
            av_code = self.code_extractor.extract_av_code(video.name)
            if av_code:
                movie_code = av_code
            else:
                # 找不到番号的集中在"匿名影片"下
                logger.warning(
                    "Could not extract AV code from filename: %s. Add this file to the 'anonymous movie'.",
                    video.name,
                )
                movie_code = "anonymous"

            if movie_code not in movies_map:
                movies_map[movie_code] = Movie(code=movie_code)

            movie = movies_map[movie_code]
            movie.videos.append(video_dataclass)
        return list(movies_map.values())
