# == audio_extractor.py ==

import logging
import subprocess
import shlex
from pathlib import Path
from typing import List, Dict

# --- 从我们自己的模块导入 ---
try:
    from config import AUDIO_DIR
    from exceptions import FatalError
    # StatManager 不再需要导入
except ImportError:
    # 支持独立测试时的回退定义
    class FatalError(Exception):
        pass


    AUDIO_DIR = Path("./_temp/audio")

logger = logging.getLogger(__name__)

# --- 核心配置常量 ---
DURATION_THRESHOLD_SECONDS: int = 180  # 视频与音频时长差异阈值（3分钟）


# --- 内部异常 ---
class _AudioProcessingError(Exception):
    """定义一个仅在模块内部使用的特定异常，用于表示音频处理失败。"""
    pass


# --- 内部辅助函数 (_ 开头) ---

def _run_command(cmd_args: List[str]) -> str:
    """[内部函数] 执行一个外部命令，并返回其标准输出。"""
    cmd_str = ' '.join(shlex.quote(arg) for arg in cmd_args)
    logger.debug(f"正在执行命令: {cmd_str}")
    try:
        result = subprocess.run(
            cmd_args, check=True, capture_output=True, text=True,
            encoding='utf-8', timeout=1800  # 设置30分钟超时
        )
        return result.stdout.strip()
    except FileNotFoundError:
        logger.critical(f"命令 '{cmd_args[0]}' 未找到。请确保 ffmpeg/ffprobe 已安装并位于系统的PATH中。")
        raise _AudioProcessingError(f"依赖缺失: {cmd_args[0]} 未找到。")
    except subprocess.CalledProcessError as e:
        error_details = f"命令执行失败，返回码: {e.returncode}\n--- stderr ---\n{e.stderr.strip()}"
        logger.error(error_details)
        raise _AudioProcessingError(error_details)
    except subprocess.TimeoutExpired:
        logger.error(f"命令执行超时: {cmd_str}")
        raise _AudioProcessingError("命令执行超时。")


def _get_media_duration(file_path: Path) -> float:
    """[内部函数] 使用 ffprobe 获取媒体文件的时长（秒）。"""
    if not file_path.exists() or file_path.stat().st_size == 0:
        raise _AudioProcessingError(f"媒体文件不存在或为空: {file_path}")
    command = [
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)
    ]
    try:
        duration_str = _run_command(command)
        return float(duration_str)
    except (ValueError, _AudioProcessingError) as e:
        raise _AudioProcessingError(f"获取时长失败: {file_path.name}") from e


# --- 核心功能函数 (Core Function Layer) ---

def _extract_and_validate_audio(video_path: Path, output_audio_path: Path):
    """
    【核心功能函数】
    从视频中提取音频，并校验提取后文件的时长是否与原视频匹配。
    """
    logger.info(f"[{video_path.name}] 正在执行核心音频提取与校验...")

    video_duration = _get_media_duration(video_path)
    logger.info(f"[{video_path.name}] 源视频时长: {video_duration:.2f} 秒。")

    command = [
        'ffmpeg', '-i', str(video_path), '-y', '-vn',
        '-acodec', 'mp3', '-q:a', '2', str(output_audio_path)
    ]
    _run_command(command)
    logger.info(f"[{video_path.name}] FFmpeg 音频提取命令执行完毕。")

    audio_duration = _get_media_duration(output_audio_path)
    logger.info(f"[{video_path.name}] 提取出的音频时长: {audio_duration:.2f} 秒。")

    duration_diff = abs(video_duration - audio_duration)
    if duration_diff > DURATION_THRESHOLD_SECONDS:
        output_audio_path.unlink(missing_ok=True)
        raise _AudioProcessingError("提取的音频时长与原视频严重不符，可能文件已损坏或提取过程出错。")

    logger.info(f"[{video_path.name}] 时长校验通过，差异: {duration_diff:.2f} 秒。")


# --- 公开接口 (Worker/Orchestration Layer) ---

def extract_audio_worker(av_code: str, segment_id: str, video_full_path: str, force: bool = False) -> Dict:
    """
    【工人函数】负责编排音频提取流程，并返回结果。
    【架构修正】不再接收 stat_manager，改为接收视频文件路径并返回结果字典。
    """
    logger.info(f"--- 开始处理番号 {av_code} (分段: {segment_id}) 的【核心流程：音频提取】 ---")

    video_path = Path(video_full_path)
    audio_filename = video_path.stem + ".mp3"
    output_audio_path = AUDIO_DIR / audio_filename

    # 幂等性检查
    if output_audio_path.exists() and output_audio_path.stat().st_size > 0 and not force:
        logger.info(f"音频文件 '{audio_filename}' 已存在，跳过提取任务。")
        return {'status': 'skipped', 'av_code': av_code, 'segment_id': segment_id}

    try:
        # 调用核心功能
        _extract_and_validate_audio(video_path, output_audio_path)

        # 返回成功结果
        return {'status': 'success', 'av_code': av_code, 'segment_id': segment_id}

    except Exception as e:
        # 捕获所有内部异常并统一包装成 FatalError
        error_message = f"音频提取失败: {e}"
        logger.critical(f"为 {segment_id} 处理音频时发生致命错误: {error_message}", exc_info=True)
        raise FatalError(error_message) from e