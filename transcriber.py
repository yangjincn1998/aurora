# == transcriber.py ==
import multiprocessing
import os
import logging
import config
import time
from pathlib import Path
from typing import Dict

# --- 第三方库导入 ---
try:
    import assemblyai as aai

    ASSEMBLYAI_AVAILABLE = True
except ImportError:
    ASSEMBLYAI_AVAILABLE = False
    logging.warning("AssemblyAI 库未安装。AssemblyAI 转写服务将不可用。")

try:
    from faster_whisper import WhisperModel

    WHISPER_AVAILABLE = True
    logging.info("检测到 faster-whisper，将使用它进行本地转写。")
except ImportError:
    WHISPER_AVAILABLE = False
    logging.warning("faster_whisper 库未安装。本地 Whisper 转写服务将不可用。")

# --- 从我们自己的模块导入 ---
from config import JAP_SUB_DIR, AUDIO_DIR, ASSEMBLYAI_API_KEY
from exceptions import FatalError

# StatManager 不再需要导入

logger = logging.getLogger(__name__)

# --- 模块级全局变量 ---
_whisper_model = None  # 每个进程只应加载一次


# --- 内部异常 ---
class _TranscriptionError(Exception):
    """定义一个仅在模块内部使用的特定异常，用于表示转写失败。"""
    pass


# --- 内部辅助函数 (_ 开头) ---
def _format_timestamp(seconds: float) -> str:
    """将秒数格式化为 SRT 时间戳字符串 (HH:MM:SS,mmm)。"""
    assert seconds >= 0, "non-negative timestamp expected"
    milliseconds = round(seconds * 1000.0)
    hours = milliseconds // 3_600_000
    milliseconds %= 3_600_000
    minutes = milliseconds // 60_000
    milliseconds %= 60_000
    seconds = milliseconds // 1_000
    milliseconds %= 1_000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _to_srt(transcription_result) -> str:
    """将转写结果（通常是一个字典列表）转换为SRT格式的字符串。"""
    srt_content = []
    for i, segment in enumerate(transcription_result):
        start_time = _format_timestamp(segment["start"])
        end_time = _format_timestamp(segment["end"])
        text = segment["text"].strip()
        if text:  # 确保不写入空的文本条目
            srt_content.append(f"{i + 1}\n{start_time} --> {end_time}\n{text}\n")
    return "\n".join(srt_content)


# --- 核心功能函数 (Core Function Layer) ---

def _transcribe_with_whisper(audio_path: Path, gpu_lock) -> str:
    """【核心功能 - Whisper】使用本地Whisper模型进行转写，并通过GPU锁确保资源安全。"""
    global _whisper_model
    if not WHISPER_AVAILABLE: raise _TranscriptionError("Whisper (faster-whisper) 库未安装。")

    logger.info(f"[{audio_path.name}] 正在等待GPU锁以执行Whisper转写...")
    gpu_lock.acquire()
    try:
        logger.info(f"[{audio_path.name}] 已获取GPU锁。")
        if _whisper_model is None:
            logger.info(f"[进程 PID: {os.getpid()}] 首次加载Whisper base模型到CPU...")
            _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
            logger.info(f"[进程 PID: {os.getpid()}] Whisper模型加载完成。")

        start_time = time.time()
        segments_generator, _ = _whisper_model.transcribe(str(audio_path), beam_size=5, language="ja")
        results = [{"start": s.start, "end": s.end, "text": s.text} for s in segments_generator]
        duration = time.time() - start_time
        logger.info(f"[{audio_path.name}] Whisper转写完成，耗时: {duration:.2f} 秒。")
        return _to_srt(results)
    except Exception as e:
        raise _TranscriptionError(f"本地Whisper转写失败: {e}") from e
    finally:
        gpu_lock.release()
        logger.info(f"[{audio_path.name}] 已释放GPU锁。")


def _transcribe_with_assemblyai(audio_path: Path) -> str:
    """【核心功能 - AssemblyAI】使用AssemblyAI的云服务进行转写。"""
    if not ASSEMBLYAI_AVAILABLE: raise _TranscriptionError("AssemblyAI 库未安装。")
    if not ASSEMBLYAI_API_KEY: raise _TranscriptionError("ASSEMBLYAI_API_KEY 未在.env中配置。")
    try:
        aai.settings.api_key = ASSEMBLYAI_API_KEY
        config = aai.TranscriptionConfig(language_code="ja")
        transcriber = aai.Transcriber()
        logger.info(f"[{audio_path.name}] 正在上传到AssemblyAI并开始转写...")
        transcript = transcriber.transcribe(str(audio_path), config=config)
        if transcript.status == aai.TranscriptStatus.error:
            raise _TranscriptionError(f"AssemblyAI API返回错误: {transcript.error}")
        results = [{"start": p.start / 1000.0, "end": p.end / 1000.0, "text": p.text} for p in transcript.paragraphs]
        return _to_srt(results)
    except Exception as e:
        raise _TranscriptionError(f"AssemblyAI服务调用失败: {e}") from e


# --- 公开接口 (Worker/Orchestration Layer) ---
def transcribe_audio_worker(av_code: str, segment_id: str, audio_path_str: str,
                            gpu_lock, shared_status: Dict, force: bool = False) -> Dict:
    """【工人函数】负责编排音频转写流程，实现服务动态切换和GPU安全锁。"""
    logger.info(f"--- 开始处理番号 {av_code} (分段: {segment_id}) 的【核心流程：音频转写】 ---")

    audio_path = Path(audio_path_str)
    output_srt_path = config.JAP_SUB_DIR / (Path(segment_id).stem + ".srt")

    if output_srt_path.exists() and not force:
        logger.info(f"日文字幕 '{output_srt_path.name}' 已存在，跳过。")
        return {'status': 'skipped', 'av_code': av_code, 'segment_id': segment_id}

    try:
        if not audio_path.exists():
            raise _TranscriptionError(f"依赖的音频文件不存在: {audio_path}")

        srt_content = None
        current_service = shared_status.get('transcription_service', 'assemblyai')

        if current_service == 'assemblyai':
            try:
                srt_content = _transcribe_with_assemblyai(audio_path)
            except _TranscriptionError as e:
                logger.warning(f"AssemblyAI服务失败 (错误: {e})，熔断并切换到Whisper...")
                shared_status['transcription_service'] = 'whisper'

        if srt_content is None:
            srt_content = _transcribe_with_whisper(audio_path, gpu_lock)

        output_srt_path.parent.mkdir(parents=True, exist_ok=True)
        output_srt_path.write_text(srt_content, encoding='utf-8')

        return {'status': 'success', 'av_code': av_code, 'segment_id': segment_id}

    except Exception as e:
        raise FatalError(f"音频转写失败: {e}") from e


# --- 测试主函数 ---
def run_whisper_test():
    """执行完整的测试流程。"""

    # --- 请在这里配置您要测试的音频文件路径 ---
    # 【重要】请将 'path/to/your/audio.mp3' 替换为一个真实存在的、较短的音频文件路径（例如1-5分钟）
    # 以便快速看到结果。
    audio_file_to_test = Path(r".\_temp\audio\AUKS-083-3 女女同志 早川.mp3")
    # ----------------------------------------------------

    logger.info("========== Whisper 单独测试开始 ==========")

    if not audio_file_to_test.exists():
        logger.error(f"测试失败：音频文件不存在！请确保路径正确: {audio_file_to_test.resolve()}")
        return

    # 模拟主进程创建的共享锁
    mock_gpu_lock = multiprocessing.Lock()

    try:
        logger.info(f"准备测试文件: {audio_file_to_test.name}")
        overall_start_time = time.time()

        # 调用被测试的函数
        srt_result = _transcribe_with_whisper(audio_file_to_test, mock_gpu_lock)

        overall_duration = time.time() - overall_start_time
        logger.info(f"函数调用成功！总耗时: {overall_duration:.2f} 秒。")

        print("\n--- 转写结果 (前500个字符) ---")
        print(srt_result[:500])
        print("...")
        print("--- 测试结束 ---")

    except Exception as e:
        logger.critical("测试过程中发生严重错误！", exc_info=True)


if __name__ == '__main__':
    run_whisper_test()