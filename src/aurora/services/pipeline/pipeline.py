from pathlib import Path

from aurora.domain.enums import StageStatus
from aurora.domain.pipeline import PipelineContext
from aurora.orms.models import Movie, Video, EntityStageStatus
from aurora.services.scanner.filesystem_scanner import LibraryScanner
from aurora.services.stages.base import PipelineStage
from aurora.utils.logger import get_logger

logger = get_logger(__name__)


class Pipeline:
    def __init__(
            self,
            movie_stages: list[PipelineStage],
            video_stages: list[PipelineStage],
            scanner: LibraryScanner,
            context: PipelineContext,
    ):
        self.movie_stages = movie_stages
        self.video_stages = video_stages
        self.scanner = scanner
        self.context = context

    def _sync_video_status(self, video: Video):
        # 1. 终局检查：如果最终产物存在且状态成功，直接返回
        terminal_stage = self.video_stages[-1].name
        terminal_info = video.stages.get(terminal_stage)

        if (
                terminal_info
                and terminal_info.status == StageStatus.SUCCESS.value
                and Path(terminal_info.by_product_path).exists()
        ):
            logger.info(
                "Video %s has executed successfully, no need to sync.", video.filename
            )
            return

        # 2. 寻找回退点 (Find the break point)
        reset_index = -1
        for i, stage in enumerate(self.video_stages):
            stage_info = video.stages.get(stage.name)

            # 情况 A: 全新阶段 (Fresh)
            if not stage_info:
                logger.debug(
                    "Video %s is fresh on stage %s, set pending from it.",
                    video.filename,
                    stage.name,
                )
                reset_index = i
                break

            # 情况 B: 状态异常 (Failed/Skipped/Pending)
            # 将 PENDING 也归为此类，逻辑是一样的
            if stage_info.status in {
                StageStatus.FAILED.value,
                StageStatus.SKIPPED.value,
                StageStatus.PENDING.value,
            }:
                logger.debug(
                    "Video %s status is %s on stage %s, set pending from it.",
                    video.filename,
                    stage_info.status,
                    stage.name,
                )
                reset_index = i
                break

            # 情况 C: 状态成功但文件丢失 (User deleted artifact)
            if not Path(stage_info.by_product_path).exists():
                logger.info(
                    "User didn't feel satisfied for production of video %s stage %s (file missing), set pending from it.",
                    video.filename,
                    stage.name,
                )
                reset_index = i
                break

        # 3. 执行回退清理 (如果找到了回退点)
        if reset_index != -1:
            # 直接切片遍历，语义更强：从这里开始，后面的都要重置
            for stage in self.video_stages[reset_index:]:
                stage_info = video.stages.get(stage.name)

                # [优化点] 清理垃圾：使用 missing_ok=True 消除一层 if 嵌套
                if stage_info and stage_info.by_product_path:
                    Path(stage_info.by_product_path).unlink(missing_ok=True)

                # 更新数据库状态
                EntityStageStatus.create_or_update_stage(
                    video, stage.name, StageStatus.PENDING, self.context.session
                )

    def _run_video_pipeline(self, video: Video):
        self._sync_video_status(video)
        for stage in self.video_stages:
            stage_name = stage.name
            current_status_obj = video.stages.get(stage_name, None)
            if not current_status_obj:
                raise ValueError(
                    "can't video %s stage for %s", video.filename, stage_name
                )
            if (
                    current_status_obj
                    and current_status_obj.status == StageStatus.SUCCESS.value
            ):
                logger.info(
                    "Stage %s has been skipped due to successfully executed.",
                    stage_name,
                )
                continue
            elif (
                    current_status_obj
                    and current_status_obj.status == StageStatus.SKIPPED.value
            ):
                logger.info(
                    "Stage %s has been skipped due to not a critical failure.",
                    stage_name,
                )
                continue
            elif (
                    current_status_obj
                    and current_status_obj.status == StageStatus.FAILED.value
            ):
                logger.info(
                    "Stage %s executed with a critical failure. Abort pipeline execute for %s",
                    stage_name,
                    video.filename,
                )
                break

            logger.info("Running Stage %s", stage_name)

            try:
                result = stage.execute(video, self.context.session)  # 这里的
            except Exception as e:
                logger.exception("Stage %s failed", stage_name)

    def process_movie(self, movie: Movie):
        logger.info("Start to process movie %s", movie.code)
        self._run_movie_pipeline(movie)
        for video in movie.videos:
            self._run_video_pipeline(video)

    def run(self, root_path: str):
        try:
            movies = self.scanner.scan_directory(root_path)
        except FileNotFoundError as e:
            logger.exception("Scanning directory %s failed", root_path)
            raise e

        for movie in movies:
            self.process_movie(movie)
