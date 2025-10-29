from pathlib import Path
from typing import Optional, Tuple
import re
from abc import ABC, abstractmethod
from faster_whisper import WhisperModel
from utils.logger import get_logger

logger = get_logger(__name__)


class Transcriber(ABC):
    """
    音频转写器。
    """
    @abstractmethod
    def transcribe(self, path: str) -> Optional[str]:
        """
        转写音频文件为字幕文本。

        Args:
            path (str): 音频文件路径。

        Returns:
            Optional[str]: 转写后的字幕文本，如果失败则返回 None。
        Raises:
            FileNotFoundError: 如果音频文件不存在。
            ValueError: 如果转写过程中发生错误。
        """
        pass


class WhisperTranscriber(Transcriber):
    """
    基于 Faster Whisper 的音频转写器实现。
    """

    def __init__(self, model_size: str = "medium", device: str = "cuda", compute_type: str = "float16",
                 language: str = "ja", beam_size: int = 6, vad_filter: bool = True):
        """
        初始化 WhisperTranscriber。

        Args:
            model_size (str): Whisper 模型大小。
            device (str): 计算设备，如 "cuda" 或 "cpu"。
            compute_type (str): 计算类型，如 "float16"。
            language (str): 音频语言，默认为日语。
            beam_size (int): 束搜索大小。
            vad_filter (bool): 是否启用语音活动检测。
        """
        self.language = language
        self.beam_size = beam_size
        self.vad_filter = vad_filter

        try:
            self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        except Exception as e:
            logger.warning(f"Failed to load {device} faster-whisper model: {e}")
            logger.info("Falling back to CPU mode with int8")
            self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe(self, path: str) -> Optional[str]:
        """
        转写音频文件为SRT字幕。

        Args:
            path (str): 音频文件路径。

        Returns:
            Optional[str]: SRT格式的字幕内容，如果失败则返回 None。
        """
        if not Path(path).exists():
            raise FileNotFoundError(f"Audio file not found: {path}")

        try:
            segments, info = self.model.transcribe(
                path,
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
                language=self.language
            )

            srt_content = []
            for i, segment in enumerate(segments):
                start_time = self._format_time_srt(segment.start)
                end_time = self._format_time_srt(segment.end)
                text = segment.text.strip()

                srt_content.append(str(i+1))
                srt_content.append(f"{start_time} --> {end_time}")
                srt_content.append(text)
                srt_content.append("")

            return "\n".join(srt_content)

        except Exception as e:
            logger.error(f"Transcription failed for {path}: {e}")
            return None

    @staticmethod
    def _format_time_srt(seconds: float) -> str:
        """将秒数转换为 SRT 时间格式 (HH:MM:SS,mmm)

        Args:
            seconds: 秒数

        Returns:
            SRT时间格式字符串
        """
        hours = int(seconds // 3600)
        seconds %= 3600
        minutes = int(seconds // 60)
        seconds %= 60
        milliseconds = int((seconds - int(seconds)) * 1000)
        seconds = int(seconds)

        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"