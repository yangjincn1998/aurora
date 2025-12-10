import json
import subprocess
from pathlib import Path

from domain.enums import PiplinePhase, StageStatus
from domain.movie import Movie, Video
from pipeline.base import VideoPipelineStage
from pipeline.context import PipelineContext
from utils.logger import get_logger

logger = get_logger(__name__)


class ExtractAudioStage(VideoPipelineStage):
    """音频提取流水线阶段。

    使用ffmpeg从视频文件中提取音频轨道。
    """

    @property
    def name(self):
        """获取阶段名称。

        Returns:
            str: 阶段名称 "extract_audio"。
        """
        return "extract_audio"

    def should_execute(self, video: Video, context: PipelineContext) -> bool:
        """判断是否应该执行音频提取阶段。

        Args:
            video (Video): 待检查的视频对象。
            context(PipelineContext): 占位。

        Returns:
            bool: 如果音频提取阶段未成功完成则返回True。
        """
        status = video.status.get(PiplinePhase.EXTRACT_AUDIO, StageStatus.PENDING)
        return status != StageStatus.SUCCESS

    def execute(self, movie: Movie, video: Video, context: PipelineContext) -> None:
        """执行音频提取处理。

        使用ffmpeg从视频中提取音频，保存为WAV格式（适合后续处理）。

        Args:
            movie (Movie): 电影对象。
            video (Video): 待处理的视频对象。
            context (PipelineContext): 流水线执行上下文。
        """
        try:
            # 确定输出路径
            video_path = Path(video.absolute_path)
            output_dir = Path(context.output_dir) / movie.code
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / (video.filename + ".extract.wav")

            # 如果输出文件已存在，直接标记为成功
            if output_path.exists():
                logger.info("Audio file already exists: %s", output_path)
                video.status[PiplinePhase.EXTRACT_AUDIO] = StageStatus.SUCCESS
                video.by_products[PiplinePhase.EXTRACT_AUDIO] = str(output_path)
                return

            # 使用ffmpeg提取音频
            # -i: 输入文件
            # -vn: 不处理视频
            # -acodec pcm_s16le: 使用PCM编码（WAV格式）
            # -ar 16000: 采样率16kHz（Whisper推荐）
            # -ac 1: 单声道
            command = [
                "ffmpeg",
                "-i",
                str(video_path),
                "-vn",  # 不处理视频
                "-acodec",
                "pcm_s16le",  # PCM编码
                "-ar",
                "16000",  # 16kHz采样率
                "-ac",
                "1",  # 单声道
                "-y",  # 覆盖已存在文件
                str(output_path),
            ]

            logger.info("Extracting audio from %s...", video.filename)
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=3600  # 1小时超时
            )

            if result.returncode != 0:
                logger.error("FFmpeg error: %s", result.stderr)
                video.status[PiplinePhase.EXTRACT_AUDIO] = StageStatus.FAILED
                return

            # 验证输出文件是否创建
            if not output_path.exists():
                logger.error("Output file not created: %s", output_path)
                video.status[PiplinePhase.EXTRACT_AUDIO] = StageStatus.FAILED
                return

            # 校验音频时长
            video_duration = self._get_duration(video_path)
            audio_duration = self._get_duration(output_path)

            if video_duration is None:
                logger.warning(
                    "Could not get video duration for %s, skipping duration check",
                    video.filename,
                )
            elif audio_duration is None:
                logger.error("Could not get audio duration for %s", output_path)
                video.status[PiplinePhase.EXTRACT_AUDIO] = StageStatus.FAILED
                return
            # 检查时长差异
            duration_diff = abs(video_duration - audio_duration)
            if duration_diff > 180:  # 3分钟 = 180秒
                logger.error(
                    "Duration mismatch for %s: video=%.2fs, audio=%.2fs, diff=%.2fs (threshold: 180s)",
                    video.filename,
                    video_duration,
                    audio_duration,
                    duration_diff,
                )
                video.status[PiplinePhase.EXTRACT_AUDIO] = StageStatus.FAILED
                # 删除不合格的音频文件
                output_path.unlink()
                return
            logger.info(
                "Duration check passed: video=%.2fs, audio=%.2fs, diff=%.2fs",
                video_duration,
                audio_duration,
                duration_diff,
            )

            # 标记为成功
            video.status[PiplinePhase.EXTRACT_AUDIO] = StageStatus.SUCCESS
            video.by_products[PiplinePhase.EXTRACT_AUDIO] = str(output_path)
            logger.info("Successfully extracted audio to: %s", output_path)

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg timeout for %s", video.filename)
            video.status[PiplinePhase.EXTRACT_AUDIO] = StageStatus.FAILED
        except Exception:
            logger.exception("Failed to extract audio from %s", video.filename)
            video.status[PiplinePhase.EXTRACT_AUDIO] = StageStatus.FAILED

    @staticmethod
    def _get_duration(file_path: Path) -> float | None:
        """使用ffprobe获取媒体文件的时长。

        Args:
            file_path (Path): 媒体文件路径。

        Returns:
            float | None: 时长（秒），如果失败则返回None。
        """
        try:
            command = [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(file_path),
            ]

            result = subprocess.run(command, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                logger.error("ffprobe error for %s: %s", file_path, result.stderr)
                return None

            # 解析JSON输出
            data = json.loads(result.stdout)
            duration_str = data.get("format", {}).get("duration")

            if duration_str is None:
                logger.error("Duration not found in ffprobe output for %s", file_path)
                return None

            return float(duration_str)

        except subprocess.TimeoutExpired:
            logger.error("ffprobe timeout for %s", file_path)
            return None
        except json.JSONDecodeError:
            logger.exception("Failed to parse ffprobe output for %s", file_path)
            return None
        except Exception:
            logger.exception("Failed to get duration for %s", file_path)
            return None
