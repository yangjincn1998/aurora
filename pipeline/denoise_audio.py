from pathlib import Path

from domain.enums import PiplinePhase, StageStatus
from domain.movie import Movie, Video
from pipeline.base import VideoPipelineStage
from pipeline.context import PipelineContext
from services.denoise.denoiser import Denoiser
from utils.logger import get_logger

logger = get_logger(__name__)


class DenoiseAudioStage(VideoPipelineStage):
    """音频降噪流水线阶段。

    使用模块化降噪器进行音频降噪处理。
    """

    def __init__(self, denoiser: Denoiser):
        """初始化音频降噪阶段。
        Args:
            denoiser (Denoiser): 降噪器实例
        """
        self.denoiser = denoiser

    @property
    def name(self):
        """获取阶段名称 "denoise_audio"""
        return "denoise_audio"

    def should_execute(self, video: Video, context: PipelineContext) -> bool:
        """判断是否应该执行音频降噪阶段。"""
        prev_status = video.status.get(PiplinePhase.EXTRACT_AUDIO, StageStatus.PENDING)
        if prev_status != StageStatus.SUCCESS:
            return False
        status = video.status.get(PiplinePhase.DENOISE_AUDIO, StageStatus.PENDING)
        return status != StageStatus.SUCCESS

    def execute(self, movie: Movie, video: Video, context: PipelineContext) -> None:
        """执行音频降噪处理。

        使用模块化降噪器进行音频降噪。

        Args:
            movie (Movie): 电影对象。
            video (Video): 待处理的视频对象。
            context (PipelineContext): 流水线执行上下文。
        """
        # 获取输入音频文件路径
        input_audio_path = video.by_products.get(PiplinePhase.EXTRACT_AUDIO)
        if not input_audio_path or not Path(input_audio_path).exists():
            logger.error("Input audio file not found for %s", video.filename)
            video.status[PiplinePhase.DENOISE_AUDIO] = StageStatus.FAILED
            return

        # 确定输出路径
        output_dir = Path(context.output_dir) / movie.code
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{video.filename}.denoised.wav"

        logger.info("Starting denoising for: %s", video.filename)

        # 使用降噪器进行降噪处理
        success, message = self.denoiser.denoise(input_audio_path, str(output_path))

        if success:
            logger.info(
                "Audio %s has been denoised successfully: %s", video.filename, message
            )
            video.by_products[PiplinePhase.DENOISE_AUDIO] = str(output_path)
            video.status[PiplinePhase.DENOISE_AUDIO] = StageStatus.SUCCESS
        else:
            logger.error("Denoising failed for %s: %s", video.filename, message)
            video.status[PiplinePhase.DENOISE_AUDIO] = StageStatus.FAILED
