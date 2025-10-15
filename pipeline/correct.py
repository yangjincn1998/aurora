import os.path
from logging import getLogger
from pathlib import Path

from base import PipelineStage, VideoPipelineStage
from domain.movie import Movie, Video
from models.enums import StageStatus, PiplinePhase
from models.results import ProcessResult
from services.translation.orchestrator import TranslateOrchestrator

logger = getLogger(__name__)


class CorrectStage(PipelineStage, VideoPipelineStage):
    """字幕校正流水线阶段。

    负责对视频字幕进行校正处理。
    Attributes:
        translator (TranslateOrchestrator): 翻译服务协调器。
    """

    def __init__(self, translator: TranslateOrchestrator):
        self.translator = translator

    @staticmethod
    def name():
        """获取阶段名称。

        Returns:
            str: 阶段名称 "correction"。
        """
        return "correction"

    @staticmethod
    def should_execute(video):
        """判断是否应该执行校正阶段。

        Args:
            video (Video): 待检查的视频对象。

        Returns:
            bool: 如果校正阶段未成功完成则返回True。
        """
        return video.status.get(PiplinePhase.CORRECT_SUBTITLE, StageStatus.PENDING) != StageStatus.SUCCESS

    def execute(self, movie: Movie, video: Video):
        """执行字幕校正处理。

        读取原始字幕文件，使用校正服务进行校正，并将结果保存到输出文件。

        Args:
            movie (Movie): 视频所属的电影对象。
            video (Video): 待处理的视频对象。

        """
        srt_raw = Path(video.by_products[PiplinePhase.TRANSCRIBE_AUDIO]).read_text(encoding="utf-8")
        result: ProcessResult = self.translator.correct_subtitle(
            text=srt_raw,
            metadata=movie.metadata.to_serializable_dict(),
            terms=[term.to_serializable_dict() for term in movie.terms]
        )
        if result.success:
            corrected_srt = result.content
            corrected_path = os.path.join("output", video.filename + "_corrected.srt")
            video.by_products[PiplinePhase.CORRECT_SUBTITLE] = corrected_srt
            Path(corrected_path).touch(exist_ok=True)
            Path(corrected_path).write_text(corrected_srt, encoding="utf-8")
            logger.info(f"Successfully corrected subtitle, saved to {corrected_path}")
            for term in result.terms:

        video.status[PiplinePhase.CORRECT_SUBTITLE] = StageStatus.SUCCESS
        else:
        logger.error(f"Failed to correct subtitle for video {video.filename}")
        video.status[PiplinePhase.CORRECT_SUBTITLE] = StageStatus.FAILED

    return
