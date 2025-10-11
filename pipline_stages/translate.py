import os
from logging import getLogger
from pathlib import Path

from models.movie import Movie, Video, PiplineStage, StageStatus
from models.query_result import ProcessResult
from pipline_stages.base import PiplineStage, VideoPipelineStage
from services.translate.orchestractor import TranslateOrchestrator

logger = getLogger(__name__)

class TranslateStage(PiplineStage, VideoPipelineStage):
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
            str: 阶段名称 "translate"。
        """
        return "translate"

    @staticmethod
    def should_execute(video: Video):
        """判断是否应该执行翻译阶段。

        Args:
            video (Video): 待检查的视频对象。

        Returns:
            bool: 如果翻译阶段未成功完成则返回True。
        """
        return video.status.get(PiplineStage.TRANSLATE, StageStatus.PENDING) != StageStatus.SUCCESS

    def execute(self, movie: Movie, video: Video):
        """执行字幕翻译处理。

        读取校正后的字幕文件，使用翻译服务进行翻译，并将结果保存到输出文件。

        Args:
            movie (Movie): 视频所属的电影对象。
            video (Video): 待处理的视频对象。

        Returns:
            Video: 处理后的视频对象，状态和副产品已更新。
        """
        metadata = movie.metadata.to_flat_dict()
        text_path = video.by_products[PiplineStage.CORRECT]
        text = Path(text_path).read_text(encoding="utf-8")
        result: ProcessResult = self.translator.translate_subtitle(text, metadata)
        if result.success:
            processed_text = result.content
            out_path = os.path.join("output", processed_text+"_jap.srt")
            logger.info(f"The translated srt will be wrote in {out_path}")
            video.by_products[PiplineStage.TRANSLATE] = out_path
            Path(out_path).write_text(processed_text, encoding="utf-8")
            logger.info(f"The translated srt was wrote in {out_path} successfully")
            video.status[PiplineStage.TRANSLATE] = StageStatus.SUCCESS
        else:
            logger.warning("Failed to translate srt")
            video.status[PiplineStage.TRANSLATE] = StageStatus.FAILED
        return video


