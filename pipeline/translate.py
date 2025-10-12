import os
from logging import getLogger
from pathlib import Path

from models.enums import StageStatus, PiplinePhase
from domain.movie import Video, Movie
from models.results import ProcessResult
from pipeline.base import PipelineStage, VideoPipelineStage
from services.translation.orchestrator import TranslateOrchestrator

logger = getLogger(__name__)

class TranslateStage(PipelineStage, VideoPipelineStage):
    """字幕翻译流水线阶段。

    负责将视频字幕从日语翻译为中文。

    Attributes:
        translator (TranslateOrchestrator): 翻译服务协调器。
    """
    def __init__(self, translator: TranslateOrchestrator):
        """初始化翻译阶段。

        Args:
            translator (TranslateOrchestrator): 翻译服务协调器。
        """
        self.translator = translator

    @staticmethod
    def name():
        """获取阶段名称。

        Returns:
            str: 阶段名称 "translation"。
        """
        return "translation"

    @staticmethod
    def should_execute(video: Video):
        """判断是否应该执行翻译阶段。

        Args:
            video (Video): 待检查的视频对象。

        Returns:
            bool: 如果翻译阶段未成功完成则返回True。
        """
        return video.status.get(PiplinePhase.TRANSLATE, StageStatus.PENDING) != StageStatus.SUCCESS

    def execute(self, movie: Movie, video: Video):
        """执行字幕翻译处理。

        读取校正后的字幕文件，使用翻译服务进行翻译，并将结果保存到输出文件。

        Args:
            movie (Movie): 视频所属的电影对象。
            video (Video): 待处理的视频对象。

        """
        metadata = movie.metadata.to_serializable_dict()
        text_path = video.by_products[PiplinePhase.CORRECT]
        text = Path(text_path).read_text(encoding="utf-8")
        result: ProcessResult = self.translator.translate_subtitle(text, metadata)
        if result.success:
            processed_text = result.content
            file_name = video.filename
            out_path = os.path.join("output", file_name+"_jap.srt")
            logger.info(f"The translated srt will be wrote in {out_path}")
            video.by_products[PiplinePhase.TRANSLATE] = out_path
            Path(out_path).write_text(processed_text, encoding="utf-8")
            logger.info(f"The translated srt was wrote in {out_path} successfully")
            video.status[PiplinePhase.TRANSLATE] = StageStatus.SUCCESS
        else:
            logger.warning("Failed to translation srt")
            video.status[PiplinePhase.TRANSLATE] = StageStatus.FAILED
        return


