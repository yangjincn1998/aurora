from pathlib import Path
from typing import Optional

from domain import movie
from domain.movie import Movie, Video
from models.enums import PiplinePhase, StageStatus
from pipeline.base import VideoPipelineStage
from pipeline.context import PipelineContext
from services.transcription.factory import TranscriberFactory
from services.transcription.quality_checker import QualityChecker
from services.transcription.transcription_service import TranscriptionService
from services.translation.provider import Provider
from utils.logger import get_logger

logger = get_logger(__name__)


class TranscribeAudioStage(VideoPipelineStage):
    """音频转写流水线阶段。

    使用模块化转写服务将音频转写为字幕文件（SRT格式），并集成质量检测。
    """

    def __init__(self, quality_check_provider: Provider):
        """初始化转写阶段。

        Args:
            quality_check_provider: 质量检测使用的LLM提供者
        """
        # 初始化转写器工厂
        self.transcriber_factory = TranscriberFactory()

        # 初始化质量检测器（使用20分钟作为最大间隔阈值）
        self.quality_checker = QualityChecker(quality_check_provider, interval=1200)

        # 初始化转写服务
        self.transcription_service = TranscriptionService(
            transcriber_factory=self.transcriber_factory,
            quality_checker=self.quality_checker,
            max_retries=2
        )

    @property
    def name(self):
        """获取阶段名称。

        Returns:
            str: 阶段名称 "transcribe_audio"。
        """
        return "transcribe_audio"

    def should_execute(self, video: Video, context: PipelineContext) -> bool:
        """判断是否应该执行音频转写阶段。

        Args:
            video (Video): 待检查的视频对象。
            context (PipelineContext): 流水线执行上下文。

        Returns:
            bool: 如果音频转写阶段未成功完成且上一阶段已完成则返回True。
        """
        # 检查上一阶段是否完成
        prev_status = video.status.get(PiplinePhase.DENOISE_AUDIO, StageStatus.PENDING)
        if prev_status != StageStatus.SUCCESS:
            return False

        # 检查当前阶段状态
        status = video.status.get(PiplinePhase.TRANSCRIBE_AUDIO, StageStatus.PENDING)
        return status != StageStatus.SUCCESS

    def execute(self, movie: Movie, video: Video, context: PipelineContext) -> None:
        """执行音频转写处理。

        使用模块化转写服务将音频转写为SRT格式的字幕文件，并进行质量检测。

        Args:
            movie (Movie): 电影对象。
            video (Video): 待处理的视频对象。
            context (PipelineContext): 流水线执行上下文。
        """
        # 获取输入音频文件路径
        input_audio = video.by_products.get(PiplinePhase.DENOISE_AUDIO)
        if not input_audio or not Path(input_audio).exists():
            logger.error(f"Input audio file not found for {video.filename}")
            video.status[PiplinePhase.TRANSCRIBE_AUDIO] = StageStatus.FAILED
            return

        # 使用转写服务进行转写和质量检测
        success, srt_content, failure_reason = self.transcription_service.transcribe_with_quality_check(
            audio_path=input_audio
        )

        if success and srt_content:
            # 确定输出路径
            output_path = Path(context.output_dir) / movie.code / f"{video.filename}.raw.srt"
            output_path.write_text(srt_content, encoding="utf-8")
            logger.info(f"Audio {video.filename} has been transcribed and quality checked successfully.")
            logger.info(f"Transcribed audio saved to {str(output_path)}")

            video.by_products[PiplinePhase.TRANSCRIBE_AUDIO] = str(output_path)
            video.status[PiplinePhase.TRANSCRIBE_AUDIO] = StageStatus.SUCCESS
        else:
            logger.error(f"Transcription failed for {video.filename}: {failure_reason}")
            video.status[PiplinePhase.TRANSCRIBE_AUDIO] = StageStatus.FAILED