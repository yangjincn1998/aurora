# == config.py ==
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件中的环境变量
load_dotenv()

# --- 核心路径配置 ---
BASE_DIR = Path(__file__).resolve().parent
VIDEO_SOURCE_DIRECTORY = Path(os.getenv("VIDEO_SOURCE_DIRECTORY", "./_source_videos")).resolve()
VIDEO_LIBRARY_DIRECTORY = Path(os.getenv("VIDEO_LIBRARY_DIRECTORY", "./AV_Library")).resolve()
STATUS_FILE_PATH = BASE_DIR / "status.json"
METADATA_CACHE_DIR = BASE_DIR / "metadata_cache"
TEMP_DIR = BASE_DIR / "_temp"
AUDIO_DIR = TEMP_DIR / "audio"
JAP_SUB_DIR = TEMP_DIR / "sub_jap"
SCH_SUB_DIR = TEMP_DIR / "sub_sch"
BILINGUAL_SUB_DIR = TEMP_DIR / "sub_bilingual"
INDEX_DIR = VIDEO_LIBRARY_DIRECTORY / "_Organized_Index"

# --- API密钥配置 ---
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
ASSEMBLYAI_API_KEY = os.getenv('ASSEMBLYAI_API_KEY')

# --- 爬虫与LLM URL配置 ---
JAVBUS_BASE_URL = os.getenv("JAVBUS_BASE_URL", "https://www.javbus.com/")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", 'https://api.deepseek.com/v1')

# --- LLM 提示词配置 ---
try:
    PROMPT_FILE = BASE_DIR / "prompt.txt"
    PROMPT_SEPARATOR = "\n\n---!PROMPT_SEPARATOR!---\n\n"
    prompts_content = PROMPT_FILE.read_text(encoding='utf-8')
    PROMPTS = prompts_content.split(PROMPT_SEPARATOR)
    SRT_PROMPT, META_PROMPT, TITLE_PROMPT = [p.strip() for p in PROMPTS]
except Exception as e:
    print(f"[CRITICAL] prompt.txt 加载或解析失败: {e}。将使用默认提示词。")
    SRT_PROMPT, META_PROMPT, TITLE_PROMPT = "请翻译", "请翻译", "请翻译"

# --- 创建所有必要的目录 ---
def initialize_directories():
    """创建项目中所有需要用到的目录"""
    for d in [VIDEO_SOURCE_DIRECTORY, VIDEO_LIBRARY_DIRECTORY, METADATA_CACHE_DIR, AUDIO_DIR, JAP_SUB_DIR, SCH_SUB_DIR, BILINGUAL_SUB_DIR]:
        d.mkdir(parents=True, exist_ok=True)

initialize_directories()