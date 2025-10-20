import os
from logging import getLogger
from pathlib import Path
from typing import List, Set, Dict, Optional

from base import MoviePipelineStage, VideoPipelineStage, PipelineStage
from context import PipelineContext
from domain.movie import Movie, Video
from services.code_extract.extractor import CodeExtractor
from services.pipeline.manifest import Manifest
from services.translation.orchestrator import TranslateOrchestrator
from services.web_request.javbus_web_service import JavBusWebService
from services.web_request.missav_web_service import MissAvWebService
from services.web_request.web_service import WebService
from utils.file_utils import calculate_partial_sha256

logger = getLogger(__name__)


class Pipeline:
    def __init__(self,
                 movie_stages: List[MoviePipelineStage],
                 video_stages: List[VideoPipelineStage],
                 code_extractor: CodeExtractor,
                 manifest: Manifest,
                 translator: TranslateOrchestrator,
                 output_dir: str = os.path.join(os.getcwd(), 'output'),
                 web_servers: List[WebService] = None,
                 ):
        self.movie_stages = movie_stages
        self.video_stages = video_stages
        self.all_stages = movie_stages + video_stages
        self.code_extractor = code_extractor
        # 创建 PipelineContext，封装 manifest
        if web_servers is None:
            web_servers = [MissAvWebService(), JavBusWebService()]
        self.context = PipelineContext(
            manifest=manifest,
            output_dir=output_dir,
            translator=translator
        )

    def _get_next_stage(self, movie: Movie, video: Optional[Video] = None) -> Optional[PipelineStage]:
        """根据实体当前状态，决定下一个要执行的阶段。"""
        target_entity = video if video else movie
        stages = self.video_stages if video else self.movie_stages

        for stage in stages:
            if stage.should_execute(target_entity):
                return stage
        return None

    def _process_movie(self, movie: Movie):
        """处理单部影片，直到所有阶段完成。"""
        logger.info(f"开始处理影片: {movie.code}")

        # 处理影片级别的阶段
        while True:
            next_stage = self._get_next_stage(movie)
            if not next_stage:
                logger.info(f"影片 {movie.code} 的所有影片级阶段处理完毕。")
                break

            logger.info(f"影片 {movie.code} 即将执行阶段: {next_stage.__class__.__name__}")
            # 传递 context 给 stage
            next_stage.execute(movie, self.context)
            # 通过 context 更新 manifest
            self.context.update_movie(movie)

        # 处理该影片下所有视频的视频级别阶段
        for video in movie.videos:
            logger.info(f"开始处理视频: {video.filename}")
            while True:
                next_stage = self._get_next_stage(movie, video)
                if not next_stage:
                    logger.info(f"视频 {video.filename} 的所有视频级阶段处理完毕。")
                    break

                logger.info(f"视频 {video.filename} 即将执行阶段: {next_stage.__class__.__name__}")
                # 传递 context 给 stage
                next_stage.execute(movie, video, self.context)
                # 通过 context 更新 manifest
                self.context.update_video(video)

    def run(self, src_path: str):
        """扫描并处理所有影片。"""
        movies = self._scan(src_path)
        logger.info(f"扫描到 {len(movies)} 部影片待处理。")
        for movie in movies:
            # 注册影片和其下的视频，并从数据库同步最新状态
            self.context.register_movie(movie)
            for video in movie.videos:
                self.context.set_video_status(video)

            # 启动该影片的处理流程
            self._process_movie(movie)

    def _scan(self, src_dir: str) -> Set[Movie]:
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
            logger.error(f"Directory {dir_path} does not exist.")
            raise FileNotFoundError(f"Directory {dir_path} does not exist.")
        video_suffixes = [
            '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mpg', '.mpeg'
        ]
        video_to_process = [
            file
            for ext in video_suffixes
            for file in dir_path.rglob(f"*{ext}")
        ]
        logger.info(f"Found {len(video_to_process)} videos.")
        movies_map: Dict[str, Movie] = {}
        for video in video_to_process:
            video_path = str(video.resolve())
            partial_hash = calculate_partial_sha256(video_path)
            if not partial_hash:
                logger.warning(f"Could not calculate SHA256 for {video.name}. Skipping this file.")
                continue

            video_dataclass = Video(
                sha256=partial_hash,
                filename=video.stem,
                suffix=video.suffix,
                absolute_path=video_path
            )
            # 在扫描阶段不再需要 set_video_status，统一移到 run 方法中
            av_code = self.code_extractor.extract_av_code(video.name)
            if av_code:
                movie_code = av_code
            else:
                # 找不到番号的集中在"匿名影片"下
                logger.warning(
                    f"Could not extract AV code from filename: {video.name}. Add this file to the 'anonymous movie'.")
                movie_code = 'anonymous'

            if movie_code not in movies_map:
                movies_map[movie_code] = Movie(code=movie_code)

            movie = movies_map[movie_code]
            movie.videos.append(video_dataclass)
        return set(movies_map.values())
