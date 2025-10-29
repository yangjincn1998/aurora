import os
from pathlib import Path

from langfuse import get_client, observe

from domain.movie import Video, Movie
from models.enums import StageStatus, PiplinePhase
from models.results import ProcessResult
from pipeline.base import VideoPipelineStage
from pipeline.context import PipelineContext
from utils.logger import get_logger

logger = get_logger(__name__)


class TranslateStage(VideoPipelineStage):
    """字幕翻译流水线阶段。

    负责将视频字幕从日语翻译为中文。"""

    def name(self):
        """获取阶段名称。

        Returns:
            str: 阶段名称 "translation"。
        """
        return "translation"

    def should_execute(self, video: Video, context: PipelineContext):
        """判断是否应该执行翻译阶段。

        Args:
            video (Video): 待检查的视频对象。
            context(PipelineContext):占位。

        Returns:
            bool: 如果翻译阶段未成功完成则返回True。
        """
        return (
                video.status.get(PiplinePhase.TRANSLATE_SUBTITLE, StageStatus.PENDING)
                != StageStatus.SUCCESS
        )

    @observe
    def execute(
            self, movie: Movie, video: Video, context: PipelineContext, stream=False
    ):
        """执行字幕翻译处理。

        读取校正后的字幕文件，使用翻译服务进行翻译，并将结果保存到输出文件。

        Args:
            movie (Movie): 视频所属的电影对象。
            video (Video): 待处理的视频对象。
            context (PipelineContext): 流水线上下文，提供共享的对象和服务。
            stream (bool)：是否使用流式处理翻译结果，默认为False。

        """
        langfuse = get_client()
        langfuse.update_current_trace(
            session_id=context.langfuse_session_id,
            tags=[context.movie_code, "translation", "subtitle"],
        )

        metadata = movie.metadata.to_serializable_dict()
        text_path = video.by_products[PiplinePhase.CORRECT_SUBTITLE]
        text = Path(text_path).read_text(encoding="utf-8")
        result: ProcessResult = context.translator.translate_subtitle(
            text, metadata, movie.terms, stream
        )
        if result.success:
            processed_text = result.content
            file_name = video.filename
            out_path = os.path.join(
                context.output_dir, movie.code, file_name + ".translated.srt"
            )
            logger.info(f"The translated srt will be wrote in {out_path}")
            video.by_products[PiplinePhase.TRANSLATE_SUBTITLE] = out_path
            Path(out_path).touch(exist_ok=True)
            Path(out_path).write_text(processed_text, encoding="utf-8")
            logger.info(f"The translated srt was wrote in {out_path} successfully")
            video.status[PiplinePhase.TRANSLATE_SUBTITLE] = StageStatus.SUCCESS
        else:
            logger.warning("Failed to translation srt")
            video.status[PiplinePhase.TRANSLATE_SUBTITLE] = StageStatus.FAILED
        return
