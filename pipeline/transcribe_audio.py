from pathlib import Path
from typing import Optional

import whisper

from domain.movie import Movie, Video
from models.enums import PiplinePhase, StageStatus
from pipeline.base import VideoPipelineStage
from pipeline.context import PipelineContext
from utils.logger import get_logger

logger = get_logger(__name__)


class TranscribeAudioStage(VideoPipelineStage):
    """音频转写流水线阶段。

    使用Whisper将音频转写为字幕文件（SRT格式）。
    """

    def __init__(self, output_dir: str = None, model_size: str = 'large', language: str = 'ja'):
        """初始化音频转写阶段。

        Args:
            output_dir (str, optional): 输出目录路径。如果为None，则保存在音频文件同目录。
            model_size (str): Whisper模型大小，可选: tiny, base, small, medium, large, large-v2, large-v3。
            language (str): 音频语言代码，默认'ja'（日语）。
        """
        self.output_dir = output_dir
        self.model_size = model_size
        self.language = language
        self._model: Optional[whisper.Whisper] = None

    @property
    def model(self):
        """懒加载Whisper模型。"""
        if self._model is None:
            logger.info(f"Loading Whisper model: {self.model_size}")
            self._model = whisper.load_model(self.model_size)
        return self._model

    @property
    def name(self):
        """获取阶段名称。

        Returns:
            str: 阶段名称 "transcribe_audio"。
        """
        return "transcribe_audio"

    def should_execute(self, movie: Movie, video: Video) -> bool:
        """判断是否应该执行音频转写阶段。

        Args:
            movie (Movie): 电影对象。
            video (Video): 待检查的视频对象。

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

        使用Whisper模型将音频转写为SRT格式的字幕文件。

        Args:
            movie (Movie): 电影对象。
            video (Video): 待处理的视频对象。
            context (PipelineContext): 流水线执行上下文。
        """
        try:
            # 获取输入音频文件路径
            input_audio = video.by_products.get(PiplinePhase.DENOISE_AUDIO)
            if not input_audio or not Path(input_audio).exists():
                logger.error(f"Input audio file not found for {video.filename}")
                video.status[PiplinePhase.TRANSCRIBE_AUDIO] = StageStatus.FAILED
                return

            input_path = Path(input_audio)

            # 确定输出路径
            if self.output_dir:
                output_dir = Path(self.output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
            else:
                output_dir = input_path.parent

            output_path = output_dir / f"{video.filename}.srt"

            # 如果输出文件已存在，直接标记为成功
            if output_path.exists():
                logger.info(f"Transcription already exists: {output_path}")
                video.status[PiplinePhase.TRANSCRIBE_AUDIO] = StageStatus.SUCCESS
                video.by_products[PiplinePhase.TRANSCRIBE_AUDIO] = str(output_path)
                return

            # 使用Whisper转写音频
            logger.info(f"Transcribing audio for {video.filename} using Whisper {self.model_size}...")

            result = self.model.transcribe(
                str(input_path),
                language=self.language,
                verbose=True,
                word_timestamps=False  # 如果需要词级时间戳可以设为True
            )

            # 将结果转换为SRT格式
            self._write_srt(result['segments'], output_path)

            # 验证输出文件是否创建
            if not output_path.exists():
                logger.error(f"SRT file not created: {output_path}")
                video.status[PiplinePhase.TRANSCRIBE_AUDIO] = StageStatus.FAILED
                return

            # 标记为成功
            video.status[PiplinePhase.TRANSCRIBE_AUDIO] = StageStatus.SUCCESS
            video.by_products[PiplinePhase.TRANSCRIBE_AUDIO] = str(output_path)
            logger.info(f"Successfully transcribed audio to: {output_path}")

        except Exception as e:
            logger.error(f"Failed to transcribe audio for {video.filename}: {e}")
            video.status[PiplinePhase.TRANSCRIBE_AUDIO] = StageStatus.FAILED

    def _write_srt(self, segments, output_path: Path):
        """将Whisper转写结果写入SRT文件。

        Args:
            segments: Whisper转写结果的segments列表。
            output_path (Path): 输出SRT文件路径。
        """
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, segment in enumerate(segments, start=1):
                # 写入序号
                f.write(f"{i}\n")

                # 写入时间戳
                start_time = self._format_timestamp(segment['start'])
                end_time = self._format_timestamp(segment['end'])
                f.write(f"{start_time} --> {end_time}\n")

                # 写入文本
                f.write(f"{segment['text'].strip()}\n\n")

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """将秒数转换为SRT时间戳格式 (HH:MM:SS,mmm)。

        Args:
            seconds (float): 秒数。

        Returns:
            str: SRT格式的时间戳。
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
