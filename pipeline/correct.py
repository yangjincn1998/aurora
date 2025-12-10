import os.path
from pathlib import Path

from langfuse import observe, get_client

from domain.enums import StageStatus, PiplinePhase
from domain.movie import Movie, Video
from domain.results import ProcessResult
from pipeline.base import VideoPipelineStage
from pipeline.context import PipelineContext
from utils.logger import setup_logger

logger = setup_logger("translator")


class CorrectStage(VideoPipelineStage):
    """字幕校正流水线阶段。

    负责对视频字幕进行校正处理。
    """

    def name(self):
        """获取阶段名称。

        Returns:
            str: 阶段名称 "correction"。
        """
        return "correction"

    def should_execute(self, video, context: PipelineContext):
        """判断是否应该执行校正阶段。

        Args:
            video (Video): 待检查的视频对象。
            context(PipelineContext): 流水线执行上下文。
        Returns:
            bool: 如果校正阶段未成功完成则返回True。
        """
        # 检查当前阶段状态
        status = video.status.get(PiplinePhase.CORRECT_SUBTITLE, StageStatus.PENDING)
        return status != StageStatus.SUCCESS

    @observe
    def execute(self, movie: Movie, video: Video, context: PipelineContext):
        """执行字幕校正处理。

        读取原始字幕文件，使用校正服务进行校正，并将结果保存到输出文件。

        Args:
            movie (Movie): 视频所属的电影对象。
            video (Video): 待处理的视频对象。
            context (PipelineContext): 流水线执行上下文。

        """
        langfuse = get_client()
        langfuse.update_current_trace(
            session_id=context.langfuse_session_id,
            tags=["correct", "subtitle", movie.code],
        )
        srt_raw = Path(video.by_products[PiplinePhase.TRANSCRIBE_AUDIO]).read_text(
            encoding="utf-8"
        )
        result: ProcessResult = context.translator.correct_subtitle(
            text=srt_raw,
            metadata=movie.metadata.to_serial_dict(),
            terms=movie.terms,
        )
        if result.success:
            corrected_srt = result.content
            corrected_path = os.path.join(
                context.output_dir, movie.code, video.filename + ".corrected.srt"
            )
            video.by_products[PiplinePhase.CORRECT_SUBTITLE] = corrected_path
            path = Path(corrected_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            path.write_text(corrected_srt, encoding="utf-8")
            logger.info("Successfully corrected subtitle, saved to %s", corrected_path)
            existed_terms = {term["japanese"] for term in movie.terms}
            for term in result.terms:
                if term["japanese"] not in existed_terms:
                    movie.terms.append(term)
                    existed_terms.add(term["japanese"])
            video.status[PiplinePhase.CORRECT_SUBTITLE] = StageStatus.SUCCESS
        else:
            logger.error("Failed to correct subtitle for video %s", video.filename)
            video.status[PiplinePhase.CORRECT_SUBTITLE] = StageStatus.FAILED
        return
