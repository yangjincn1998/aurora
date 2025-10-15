import json
import os
import sys
from pathlib import Path

import dotenv

from models.enums import TaskType
from services.translation.orchestrator import TranslateOrchestrator
from services.translation.provider import OpenaiProvider
from utils.config import Config
from utils.logger import setup_logger

dotenv.load_dotenv()

# 使用自定义日志系统
logger = setup_logger("av_translator")

if __name__ == '__main__':
    # 检查环境变量
    api_key = os.getenv("OPENROUTER_API_KEY")
    base_url = os.getenv("OPENROUTER_BASE_URL")

    if not api_key or not base_url:
        logger.error("Missing required environment variables: OPENROUTER_API_KEY or OPENROUTER_BASE_URL")
        sys.exit(1)

    config = Config()
    provider = {
        TaskType.METADATA_ACTOR: [OpenaiProvider(api_key, base_url, "deepseek/deepseek-chat-v3.1:free")],
        TaskType.METADATA_DIRECTOR: [OpenaiProvider(api_key, base_url, "deepseek/deepseek-chat-v3.1:free")],
        TaskType.METADATA_CATEGORY: [OpenaiProvider(api_key, base_url, "deepseek/deepseek-chat-v3.1:free")],
        TaskType.CORRECT_SUBTITLE: [OpenaiProvider(api_key, base_url, "google/gemini-2.5-pro")],
        TaskType.TRANSLATE_SUBTITLE: [OpenaiProvider(api_key, base_url, "google/gemini-2.5-pro")]
    }
    translator = TranslateOrchestrator(provider)

    # 检查测试文件是否存在
    test_file = Path("test_mode/PRED-726-uncensored-nyap2p.com.srt")
    if not test_file.exists():
        logger.error(f"Test file not found: {test_file}")
        sys.exit(1)

    metadata = {"director_jp":"きとるね川口", "director_zh": "基托鲁内 川口",
                "actors_jp":["星宮一花"], "actors_zh":["星宫一花"],
                "categories_jp":["單體作品","紧缚","多P","中出","深喉","女檢察官","DMM獨家", "高畫質"],
                "categories_zh":["单体作品", "紧缚", "多P", "中出", "深喉", "女检察官", "DMM独家", "高画质"]}
    try:
        with open(test_file, mode="r", encoding="utf-8") as f:
            test_srt = f.read()

        logger.info("=" * 80)
        logger.info("开始字幕校正...")
        logger.info("=" * 80)

        corrected_file = Path("test_mode/PRED-726-uncensored-nyap2p.com.corrected.1.srt")
        corrected_terms_file = Path("test_mode/PRED-726-uncensored-nyap2p.com.corrected.terms.json")
        corrected_differences_file = Path("test_mode/PRED-726-uncensored-nyap2p.com.corrected.differences.json")
        corrected_result = translator.correct_subtitle(test_srt, metadata, [])
        if corrected_result.success:
            corrected_file.write_text(corrected_result.content, encoding="utf-8")
            json.dump(corrected_result.terms, corrected_terms_file.open("w", encoding="utf-8"), ensure_ascii=False,
                      indent=2)
            json.dump(corrected_result.differences, corrected_differences_file.open("w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            logger.info(
                f"校正完成，结果已保存到 {corrected_file}, 术语库保存到 {corrected_terms_file}, 差异保存到 {corrected_differences_file}")
    except Exception as e:
        logger.error(f"Error: {e}")
