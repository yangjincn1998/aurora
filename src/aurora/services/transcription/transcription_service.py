from pathlib import Path
from typing import Tuple, Optional

from aurora.pipeline.context import PipelineContext
from aurora.services.transcription.factory import TranscriberFactory
from aurora.services.transcription.quality_checker import QualityChecker
from aurora.utils.logger import get_logger

logger = get_logger(__name__)


class TranscriptionService:
    """综合转写服务。

    集成音频转写、质量检测和重试机制。
    """

    def __init__(
        self,
        transcriber_factory: TranscriberFactory,
        quality_checker: QualityChecker,
        max_retries: int = 2,
    ):
        """初始化转写服务。

        Args:
            transcriber_factory: 转写器工厂
            quality_checker: 质量检测器
            max_retries: 最大重试次数
        """
        self.transcriber_factory = transcriber_factory
        self.quality_checker = quality_checker
        self.max_retries = max_retries

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "TranscriptionService":
        """从YAML配置文件创建TranscriptionService实例。

        Args:
            yaml_path: YAML配置文件路径

        Returns:
            TranscriptionService实例
        """
        transcriber_factory = TranscriberFactory()
        quality_checker = QualityChecker.from_config_yaml(yaml_path)

        return cls(transcriber_factory, quality_checker)

    def transcribe_with_quality_check(
        self, audio_path: str, context: "PipelineContext"
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """转写音频并进行质量检测，支持重试机制。

        Args:
            audio_path: 音频文件路径
            context: 流水线执行上下文,用于更新llm_quality_check的context参数,设置langfuse session id
        Returns:
            (是否成功, SRT字幕内容, 失败原因)
        """
        if not Path(audio_path).exists():
            return False, None, f"音频文件不存在: {audio_path}"

        for attempt in range(self.max_retries + 1):
            logger.info("转写尝试 %d/%d", attempt + 1, self.max_retries + 1)

            try:
                # 创建转写器实例
                transcriber = self.transcriber_factory.create_transcriber("whisper")

                # 执行转写
                srt_content = transcriber.transcribe(audio_path)

                if not srt_content:
                    logger.warning("转写结果为空")
                    if attempt < self.max_retries:
                        logger.info("将进行重试...")
                        continue
                    else:
                        return False, None, "转写结果为空"

                # 质量检测
                quality_passed = self.quality_checker.quality_check(
                    srt_content, context
                )

                if not quality_passed:
                    logger.warning("质量检测失败")
                    if attempt < self.max_retries:
                        logger.info("将进行重试...")
                        continue
                    else:
                        return False, srt_content, "质量检测失败"

                # 转写和质量检测都通过
                logger.info("转写质量检测通过")
                return True, srt_content, None

            except Exception as e:
                logger.exception("转写尝试 %d 失败", attempt + 1)
                if attempt < self.max_retries:
                    logger.info("将进行重试...")
                else:
                    return False, None, f"转写失败: {str(e)}"

        # 理论上不会执行到这里
        return False, None, "转写失败：未知错误"
