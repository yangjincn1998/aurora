import os
import logging
import subprocess
import shlex
import json
import math
import shutil  # Import shutil for deleting non-empty directories
from pydub import AudioSegment  # Import pydub
from pydub.silence import \
    split_on_silence  # Import pydub's silence splitting functionality, though mainly using duration here
from pathlib import Path  # Import Path for filename operations
import re  # Import re module for sanitize_filename


# --- Custom Exception ---
class AudioExtractionError(Exception):
    """
    音频提取异常。
    """
    pass


# --- Configuration ---
DURATION_THRESHOLD_SECONDS = 180  # Duration difference threshold, in seconds (3 minutes)
AUDIO_SEGMENT_DURATION_MINUTES = 5  # Duration of audio segments for Demucs processing, in minutes
AUDIO_SEGMENT_DURATION_MS = AUDIO_SEGMENT_DURATION_MINUTES * 60 * 1000  # Convert to milliseconds


# --- Helper Function: Run Command Line ---
def run_command(cmd_args: list, log_prefix: str) -> tuple[bool, str]:
    """
    执行外部命令并捕获输出。

    args:
        cmd_args (list): 命令参数列表。
        log_prefix (str): 日志前缀。

    return:
        tuple[bool, str]: (是否成功, 输出或错误信息)
    """
    full_cmd = cmd_args
    logging.info(f"{log_prefix} Executing command: {' '.join(shlex.quote(arg) for arg in full_cmd)}")
    try:
        result = subprocess.run(
            full_cmd,
            check=True,  # Raise CalledProcessError if return code is non-zero
            capture_output=True,  # Capture stdout and stderr
            text=True,  # Capture output in text mode
            encoding='utf-8'  # Specify encoding
        )
        logging.info(f"{log_prefix} Command completed successfully.")
        if result.stdout:
            logging.debug(f"{log_prefix} stdout:\n{result.stdout}")
        if result.stderr:
            logging.debug(f"{log_prefix} stderr:\n{result.stderr}")
        return True, result.stdout.strip()
    except subprocess.CalledProcessError as e:
        error_msg = f"Command failed, exit code: {e.returncode}\nstdout:\n{e.stdout}\nstderr:\n{e.stderr}"
        logging.error(f"{log_prefix} {error_msg}")
        return False, error_msg
    except FileNotFoundError:
        error_msg = f"Command '{cmd_args[0]}' not found. Please ensure the tool is installed and configured in PATH."
        logging.error(f"{log_prefix} {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"An unexpected error occurred while executing command: {e}"
        logging.error(f"{log_prefix} {error_msg}", exc_info=True)
        return False, error_msg


def get_media_duration(file_path: str) -> float | None:
    """
    Uses ffprobe to get the duration of a media file (in seconds).
    """
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        file_path
    ]

    success, output = run_command(cmd, f"Getting duration of {os.path.basename(file_path)}")
    if success and output.strip():
        try:
            return float(output.strip())
        except ValueError:
            logging.error(f"Could not parse duration '{output.strip()}' as float.")
            return None
    logging.error(f"Failed to get duration of {os.path.basename(file_path)}, output: '{output}'")
    return None


# --- Helper Functions (Copied from main.py for consistency) ---
def sanitize_filename(name: str) -> str:
    """
    Cleans a string to make it suitable for use as a filename or directory name.
    Removes characters disallowed in Windows and replaces some special characters.
    """
    cleaned_name = re.sub(r'[<>:"/\\|?*]', '_', name)
    cleaned_name = cleaned_name.rstrip('.')
    cleaned_name = cleaned_name.replace('...', '…')
    cleaned_name = cleaned_name.replace('?', '')
    cleaned_name = cleaned_name.strip()
    return cleaned_name


def get_sanitized_segment_stem(original_filename: str) -> str:
    """
    Extracts a clean, filename-safe "segment stem" from the original filename.
    E.g., "AUKS-083-1 女女同志 早川.mp4" -> "AUKS-083-1 女女同志 早川"
    Then applies filename sanitization.
    """
    stem = Path(original_filename).stem  # Get filename without extension
    return sanitize_filename(stem)


def preprocess_video_for_vocal_extraction(video_path: str, output_audio_path: str, temp_process_dir: str) -> bool:
    """
    对视频进行预处理，仅提取音频，不做降噪。

    args:
        video_path (str): 视频文件路径。
        output_audio_path (str): 输出音频文件路径。
        temp_process_dir (str): 临时目录路径（保留参数以兼容调用）。
    """
    logging.info(f"Starting video processing for audio extraction: {video_path}")
    print(f"[Audio Extractor] Starting video processing for audio extraction: {video_path}")

    # 确保输出目录存在
    output_audio_parent_dir = os.path.dirname(output_audio_path)
    if not os.path.exists(output_audio_parent_dir):
        os.makedirs(output_audio_parent_dir)
        logging.info(f"Created audio output directory: {output_audio_parent_dir}")

    # 仅用ffmpeg提取音频为mp3
    extract_audio_cmd = [
        'ffmpeg',
        '-i', video_path,
        '-vn',  # Disable video stream
        '-acodec', 'mp3',  # 输出为mp3
        '-ar', '44100',
        '-ac', '2',
        '-y',
        output_audio_path
    ]
    logging.info(f"Audio extraction command: {extract_audio_cmd}")
    success, error_msg = run_command(extract_audio_cmd, f"Extracting audio from {os.path.basename(video_path)}")
    if not success:
        raise AudioExtractionError(f"Audio extraction failed: {error_msg}")

    logging.info(f"Audio extraction successful, file saved to: {output_audio_path}")
    print(f"[Audio Extractor] Audio saved to: {output_audio_path}")
    return True


# --- Helper function for cleaning up temporary files and directories ---
def cleanup_temp_files(temp_dir: str, temp_wav: str) -> None:
    """
    清理临时目录和临时音频文件（降噪已移除，此处仅保留接口）。

    args:
        temp_dir (str): 临时目录路径。
        temp_wav (str): 临时wav文件路径。
    """
    # 兼容旧接口，实际不再产生临时文件
    pass


# --- Example Usage (for testing this module independently) ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(module)s %(levelname)s: %(message)s',
                        encoding='utf-8')

    # --- WARNING: For actual testing, you need to place a valid MP4 file at test_video_for_preprocessor.mp4 path ---
    test_video_path = "test_video_for_preprocessor.mp4"
    test_audio_output_path = "test_output_denoised_vocals.mp3"
    test_temp_dir = "test_temp_processing_dir"  # Temporary processing directory

    # Ensure test directory exists
    if not os.path.exists(os.path.dirname(test_audio_output_path)):
        os.makedirs(os.path.dirname(test_audio_output_path))

    # Simulate a simple video file (actual testing requires a valid video file)
    if not os.path.exists(test_video_path):
        print(f"Please place a valid MP4 video file at '{test_video_path}' for actual testing.")
        print("File does not exist, testing cannot proceed normally.")
        exit()  # Exit, as no actual file means no proper testing

    print(f"Starting test for vocal extraction, duration check, and denoising...")

    # Define outside try-finally block to ensure accessibility in finally
    temp_wav_for_cleanup = os.path.join(test_temp_dir, "temp_full_audio.wav")

    try:
        if preprocess_video_for_vocal_extraction(test_video_path, test_audio_output_path, test_temp_dir):
            print(f"Test successful, denoised vocal file: {test_audio_output_path}")
        else:
            print("Test failed (function returned False, but should raise an exception).")
    except AudioExtractionError as e:
        print(f"Test failed, caught AudioExtractionError: {e}")
    except Exception as e:
        print(f"Test failed, caught unknown error: {e}")
    finally:
        print("Performing test cleanup...")
        cleanup_temp_files(test_temp_dir, temp_wav_for_cleanup)
        if os.path.exists(test_audio_output_path):
            os.remove(test_audio_output_path)
            print(f"Deleted final output file: {test_audio_output_path}")
    print("Test cleanup completed.")
