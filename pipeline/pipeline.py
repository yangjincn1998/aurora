from logging import getLogger
from pathlib import Path
from typing import List, Dict


from base import MoviePipelineStage, VideoPipelineStage
from domain.movie import Movie, Video
from services.code_extract.extractor import CodeExtractor
from services.pipeline.manifest import Manifest
from utils.file_utils import calculate_partial_sha256

logger = getLogger(__name__)

class Pipline:
    def __init__(self,
                 movie_stages: List[MoviePipelineStage],
                 video_stages: List[VideoPipelineStage],
                 code_extractor: CodeExtractor,
                 manifest: Manifest
                 ):
        self.movie_stages = movie_stages
        self.video_stages = video_stages
        self.code_extractor = code_extractor
        self.manifest = manifest

    def _process_movie(self, movie):
        logger.info(f"Processing movie {movie.code}")
        for stage in self.movie_stages:
            if stage.should_process(movie):
                stage.execute(movie)
                self.manifest.update_movie(movie)
        for video in movie.videos:
            for stage in self.video_stages:
                if stage.should_execute(video):
                    stage.execute(movie, video)
                    self.manifest.update_video(video)

    def run(self, src_path):
        # 扫描src_path, 生成一张待处理的清单
        movies = self._scan(src_path)
        logger.info(f"Found {len(movies)} movies to process.")
        for movie in movies:
            self.manifest.register_movie(movie)
        for movie in movies:
            self._process_movie(movie)

    def _scan(self, src_dir: str) -> List[Movie]:
        """
        递归地扫描目录下所有字幕视频文件，创建待处理的movie列表

        项目规约：src_path下只有av文件，且每个av文件文件名中都有av番号

        Args：
            src_dir(str): 待处理的文件目录
        Returns：
            List[Movie]: 待处理影片列表
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
            self.manifest.set_video_status(video_dataclass)
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
        return list(movies_map.values())
