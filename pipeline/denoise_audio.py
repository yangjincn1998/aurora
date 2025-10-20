import subprocess
from pathlib import Path

from domain.movie import Movie, Video
from models.enums import PiplinePhase, StageStatus
from pipeline.base import VideoPipelineStage
from pipeline.context import PipelineContext
from utils.logger import get_logger

logger = get_logger(__name__)


class DenoiseAudioStage(VideoPipelineStage):
    """音频降噪流水线阶段。

    使用demucs分离人声和背景音，只保留人声部分。
    """

    def __init__(self, output_dir: str = None, model: str = 'htdemucs'):
        """初始化音频降噪阶段。

        Args:
            output_dir (str, optional): 输出目录路径。如果为None，则保存在音频文件同目录。
            model (str): demucs模型名称，默认'htdemucs'（高质量混合Transformer模型）。
        """
        self.output_dir = output_dir
        self.model = model

    @property
    def name(self):
        """获取阶段名称。

        Returns:
            str: 阶段名称 "denoise_audio"。
        """
        return "denoise_audio"

    def should_execute(self, movie: Movie, video: Video) -> bool:
        """判断是否应该执行音频降噪阶段。

        Args:
            movie (Movie): 电影对象。
            video (Video): 待检查的视频对象。

        Returns:
            bool: 如果音频降噪阶段未成功完成且上一阶段已完成则返回True。
        """
        # 检查上一阶段是否完成
        prev_status = video.status.get(PiplinePhase.EXTRACT_AUDIO, StageStatus.PENDING)
        if prev_status != StageStatus.SUCCESS:
            return False

        # 检查当前阶段状态
        status = video.status.get(PiplinePhase.DENOISE_AUDIO, StageStatus.PENDING)
        return status != StageStatus.SUCCESS

    def execute(self, movie: Movie, video: Video, context: PipelineContext) -> None:
        """执行音频降噪处理。

        使用demucs分离音频中的人声（vocals）和背景音（accompaniment），
        只保留人声部分用于后续的语音识别。

        Args:
            movie (Movie): 电影对象。
            video (Video): 待处理的视频对象。
            context (PipelineContext): 流水线执行上下文。
        """
        try:
            # 获取输入音频文件路径
            input_audio = video.by_products.get(PiplinePhase.EXTRACT_AUDIO)
            if not input_audio or not Path(input_audio).exists():
                logger.error(f"Input audio file not found for {video.filename}")
                video.status[PiplinePhase.DENOISE_AUDIO] = StageStatus.FAILED
                return

            input_path = Path(input_audio)

            # 确定输出目录
            if self.output_dir:
                output_dir = Path(self.output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
            else:
                output_dir = input_path.parent / "demucs_output"
                output_dir.mkdir(parents=True, exist_ok=True)

            # demucs会在output_dir下创建 model_name/track_name/vocals.wav
            expected_vocals_path = output_dir / self.model / input_path.stem / "vocals.wav"

            # 如果输出文件已存在，直接标记为成功
            if expected_vocals_path.exists():
                logger.info(f"Denoised audio already exists: {expected_vocals_path}")
                video.status[PiplinePhase.DENOISE_AUDIO] = StageStatus.SUCCESS
                video.by_products[PiplinePhase.DENOISE_AUDIO] = str(expected_vocals_path)
                return

            # 使用demucs分离人声
            # -n: 指定模型
            # -o: 输出目录
            # --two-stems vocals: 只分离人声和其他（加快处理）
            command = [
                'demucs',
                '-n', self.model,
                '-o', str(output_dir),
                '--two-stems', 'vocals',  # 只分离人声，加快处理
                str(input_path)
            ]

            logger.info(f"Denoising audio for {video.filename} using {self.model}...")
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=7200  # 2小时超时（demucs可能很慢）
            )

            if result.returncode != 0:
                logger.error(f"Demucs error: {result.stderr}")
                video.status[PiplinePhase.DENOISE_AUDIO] = StageStatus.FAILED
                return

            # 验证输出文件是否创建
            if not expected_vocals_path.exists():
                logger.error(f"Vocals file not created: {expected_vocals_path}")
                video.status[PiplinePhase.DENOISE_AUDIO] = StageStatus.FAILED
                return

            # 标记为成功
            video.status[PiplinePhase.DENOISE_AUDIO] = StageStatus.SUCCESS
            video.by_products[PiplinePhase.DENOISE_AUDIO] = str(expected_vocals_path)
            logger.info(f"Successfully denoised audio to: {expected_vocals_path}")

        except subprocess.TimeoutExpired:
            logger.error(f"Demucs timeout for {video.filename}")
            video.status[PiplinePhase.DENOISE_AUDIO] = StageStatus.FAILED
        except Exception as e:
            logger.error(f"Failed to denoise audio for {video.filename}: {e}")
            video.status[PiplinePhase.DENOISE_AUDIO] = StageStatus.FAILED
