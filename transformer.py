import os
import logging
import subprocess
import shlex
import time
import re  # Import re module for sanitize_filename
from pathlib import Path  # Import Path for filename operations

# Try to import AssemblyAI, if not available, log a warning
try:
    import assemblyai as aai

    ASSEMBLYAI_AVAILABLE = True
except ImportError:
    logging.warning("AssemblyAI library not found. AssemblyAI transcription service will not be available.")
    ASSEMBLYAI_AVAILABLE = False

# Try to import Whisper, if not available, log a warning
try:
    # Prefer faster-whisper if installed, otherwise fallback to openai-whisper
    try:
        from faster_whisper import WhisperModel

        WHISPER_TYPE = "faster-whisper"
        logging.info("Using faster-whisper for local transcription.")
    except ImportError:
        import whisper

        WHISPER_TYPE = "openai-whisper"
        logging.info("Using openai-whisper for local transcription.")
    WHISPER_AVAILABLE = True
except ImportError:
    logging.warning(
        "Whisper library (openai-whisper or faster-whisper) not found. Local Whisper transcription service will not be available.")
    WHISPER_AVAILABLE = False

# --- Configuration ---
# Load API keys from environment variables
from dotenv import load_dotenv

load_dotenv()

# AssemblyAI API Key
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
if ASSEMBLYAI_AVAILABLE and not ASSEMBLYAI_API_KEY:
    logging.warning("AssemblyAI API Key not set. AssemblyAI transcription service might not work.")

# --- Logging Configuration (if this file runs as a standalone module, configure separately) ---
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s %(module)s %(levelname)s: %(message)s',
#     encoding='utf-8'
# )

# --- Global Variables ---
# Whisper model loading (only load once)
_whisper_model = None


# --- Helper Functions (Copied from main.py for consistency) ---
def sanitize_filename(name: str) -> str:
    """
    清理字符串，使其适合作为文件名或目录名。
    移除 Windows 不允许的字符，并替换部分特殊字符。

    args:
        name (str): 原始字符串。

    return:
        str: 清理后的字符串。
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


def load_whisper_model() -> object:
    """
    加载 Whisper 模型（faster-whisper 或 openai-whisper）。

    return:
        object: Whisper 模型实例。
    """
    global _whisper_model
    if _whisper_model is None and WHISPER_AVAILABLE:
        logging.info("Loading Whisper model...")
        if WHISPER_TYPE == "faster-whisper":
            # faster-whisper defaults to CPU; specify device="cuda" for GPU
            # Ensure CUDA environment is correctly set up
            _whisper_model = WhisperModel("base", device="cpu", compute_type="int8")  # Or "cuda" if GPU is available
        elif WHISPER_TYPE == "openai-whisper":
            _whisper_model = whisper.load_model("base")  # "tiny", "base", "small", "medium", "large"
        logging.info("Whisper model loaded.")
    return _whisper_model


def transcribe_audio_to_srt(base_av_code: str, segment_id: str, audio_path: str, output_srt_dir: str, service: str = "whisper") -> bool:
    """
    将音频文件转录为 SRT 字幕文件。

    args:
        base_av_code (str): 基础 AV 番号。
        segment_id (str): 分段标识符。
        audio_path (str): 音频文件路径。
        output_srt_dir (str): SRT 输出目录。
        service (str): 使用的转录服务（"whisper" 或 "assemblyai"）。

    return:
        bool: 转录成功返回 True，否则返回 False。
    """
    # Build the unique output SRT filename using sanitized_segment_stem
    sanitized_segment_stem = get_sanitized_segment_stem(segment_id)
    output_srt_path = os.path.join(output_srt_dir, f"{sanitized_segment_stem}.srt")

    logging.info(
        f"[Transcriber] Starting audio transcription: {audio_path} (AV: {base_av_code}, Segment: {segment_id}) using service: {service}")

    # Ensure output directory exists
    if not os.path.exists(output_srt_dir):
        os.makedirs(output_srt_dir)

    try:
        if service.lower() == "whisper":
            if not WHISPER_AVAILABLE:
                logging.error("Whisper library not installed, cannot use Whisper transcription service.")
                return False

            model = load_whisper_model()
            if model is None:
                logging.error("Whisper model failed to load, cannot perform transcription.")
                return False

            logging.info(f"Using local Whisper model for transcription: {audio_path}")

            if WHISPER_TYPE == "faster-whisper":
                segments, info = model.transcribe(audio_path, beam_size=5, language="ja")  # Specify Japanese
                # faster-whisper returns a generator, needs iteration
                results = []
                for segment in segments:
                    results.append({
                        "start": segment.start,
                        "end": segment.end,
                        "text": segment.text
                    })
            elif WHISPER_TYPE == "openai-whisper":
                result = model.transcribe(audio_path, language="ja")  # Specify Japanese
                results = result["segments"]

            with open(output_srt_path, "w", encoding="utf-8") as f:
                for i, segment in enumerate(results):
                    start_time = _format_timestamp(segment["start"])
                    end_time = _format_timestamp(segment["end"])
                    f.write(f"{i + 1}\n")
                    f.write(f"{start_time} --> {end_time}\n")
                    f.write(f"{segment['text'].strip()}\n\n")
            logging.info(f"Whisper transcription successful, SRT file saved to: {output_srt_path}")
            return True

        elif service.lower() == "assemblyai":
            if not ASSEMBLYAI_AVAILABLE:
                logging.error("AssemblyAI library not installed, cannot use AssemblyAI transcription service.")
                return False
            if not ASSEMBLYAI_API_KEY:
                logging.error("AssemblyAI API Key not set, cannot use AssemblyAI transcription service.")
                return False

            aai.settings.api_key = ASSEMBLYAI_API_KEY
            transcriber = aai.Transcriber()

            logging.info(f"Using AssemblyAI for transcription: {audio_path}")
            config = aai.TranscriptionConfig(language_code="ja")  # Specify Japanese
            transcript = transcriber.transcribe(audio_path, config=config)

            if transcript.status == aai.TranscriptStatus.error:
                logging.error(f"AssemblyAI transcription failed: {transcript.error}")
                return False

            with open(output_srt_path, "w", encoding="utf-8") as f:
                for i, utterance in enumerate(transcript.utterances):
                    start_time = _format_timestamp(utterance.start / 1000)  # AssemblyAI returns milliseconds
                    end_time = _format_timestamp(utterance.end / 1000)
                    f.write(f"{i + 1}\n")
                    f.write(f"{start_time} --> {end_time}\n")
                    f.write(f"{utterance.text.strip()}\n\n")
            logging.info(f"AssemblyAI transcription successful, SRT file saved to: {output_srt_path}")
            return True

        else:
            logging.error(f"Unsupported transcription service: {service}")
            return False

    except Exception as e:
        logging.error(f"Transcription of audio {audio_path} (AV: {base_av_code}, Segment: {segment_id}) failed: {e}",
                      exc_info=True)
        return False


def _format_timestamp(seconds: float) -> str:
    """
    Formats seconds into SRT timestamp format (HH:MM:SS,mmm).
    """
    milliseconds = int(seconds * 1000.0)

    hours = milliseconds // 3_600_000
    milliseconds %= 3_600_000

    minutes = milliseconds // 60_000
    milliseconds %= 60_000

    seconds = milliseconds // 1_000
    milliseconds %= 1_000

    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


# --- Example Usage (for testing this module independently) ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(module)s %(levelname)s: %(message)s',
                        encoding='utf-8')

    # Create a dummy audio file for testing (requires a valid audio file)
    test_audio_path = "test_audio_for_transformer.mp3"
    test_srt_output_dir = "test_srt_outputs"
    os.makedirs(test_srt_output_dir, exist_ok=True)

    test_base_av_code = "TEST-001"
    test_segment_id = "TEST-001-PartA.mp4"  # Simulate original filename as segment_id

    if not os.path.exists(test_audio_path):
        print(f"Please place a valid MP3 audio file at '{test_audio_path}' for actual testing.")
        print("File does not exist, testing cannot proceed normally.")
        exit()

    print("\n--- Testing Whisper Transcription ---")
    if transcribe_audio_to_srt(test_base_av_code, test_segment_id, test_audio_path, test_srt_output_dir,
                               service="whisper"):
        sanitized_stem = get_sanitized_segment_stem(test_segment_id)
        print(
            f"Whisper transcription test successful, SRT file: {os.path.join(test_srt_output_dir, f'{sanitized_stem}.srt')}")
    else:
        print("Whisper transcription test failed.")

    print("\n--- Testing AssemblyAI Transcription ---")
    if ASSEMBLYAI_AVAILABLE and ASSEMBLYAI_API_KEY:
        if transcribe_audio_to_srt(test_base_av_code, test_segment_id, test_audio_path, test_srt_output_dir,
                                   service="assemblyai"):
            sanitized_stem = get_sanitized_segment_stem(test_segment_id)
            print(
                f"AssemblyAI transcription test successful, SRT file: {os.path.join(test_srt_output_dir, f'{sanitized_stem}.srt')}")
        else:
            print("AssemblyAI transcription test failed.")
    else:
        print("Skipping AssemblyAI test, as library is not installed or API key is not configured.")

    # Clean up test files
    for f in os.listdir(test_srt_output_dir):
        os.remove(os.path.join(test_srt_output_dir, f))
    os.rmdir(test_srt_output_dir)
    print("\nTest cleanup completed.")
