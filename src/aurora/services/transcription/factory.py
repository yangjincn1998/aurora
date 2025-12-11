from pathlib import Path

import yaml

from aurora.services.transcription.transcriber import Transcriber, WhisperTranscriber
from aurora.utils.logger import get_logger

logger = get_logger(__name__)


class TranscriberFactory:
    """转写器工厂类。"""

    def create_transcriber(self, type: str, **kwargs) -> Transcriber:
        """
        根据指定类型创建 Transcriber 实例。
        Args:
            type (str): 转写器类型，如 "whisper"。
            **kwargs: 其他可选参数，用于配置转写器。
        Returns:
            Transcriber: 创建好的 Transcriber 实例。
        """
        if type == "whisper":
            model_size = kwargs.get("model_size", "medium")
            device = kwargs.get("device", "cuda")
            compute_type = kwargs.get("compute_type", "float16")
            language = kwargs.get("language", "ja")
            beam_size = kwargs.get("beam_size", 6)
            vad_filter = kwargs.get("vad_filter", True)

            return WhisperTranscriber(
                model_size=model_size,
                device=device,
                compute_type=compute_type,
                language=language,
                beam_size=beam_size,
                vad_filter=vad_filter,
            )
        else:
            raise ValueError(f"Unknown transcriber type: {type}")

    def from_yaml(self, yaml_path: str) -> Transcriber:
        """
        从 YAML 配置文件创建 Transcriber 实例。
        Args:
            yaml_path(str): YAML 配置文件路径。
        Returns:
            Transcriber: 配置好的 Transcriber 实例。
        """
        if not Path(yaml_path).exists():
            raise FileNotFoundError(f"YAML config file not found: {yaml_path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        transcriber_config = config.get("transcriber", {})
        transcriber_type = transcriber_config.get("type", "whisper")

        return self.create_transcriber(transcriber_type, **transcriber_config)
