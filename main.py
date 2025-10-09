import os
import sys
from pathlib import Path

import dotenv
import logging
from services.translate.orchestractor import TranslateOrchestrator
from models.tasktype import TaskType
from services.translate.provider import Provider, OpenaiProvider
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

        logger.info("Starting subtitle correction...")
        corrected_file = Path("test_mode/PRED-726-uncensored-nyap2p.com.corrected.srt")
        result = translator.correct_or_translate_subtitle(TaskType.CORRECT_SUBTITLE, metadata, test_srt)
        if result.success:
            logger.info(f"字幕校正成功，内容长度: {len(result.content)}")
            corrected_file.write_text(result.content, encoding="utf-8")
            logger.info(f"校正结果已保存到: {corrected_file}")
        else:
            logger.error(f"字幕校正失败: {result.error}")
            sys.exit(1)

        logger.info("Starting subtitle translation...")
        corrected_srt = corrected_file.read_text(encoding="utf-8")
        result = translator.correct_or_translate_subtitle(TaskType.TRANSLATE_SUBTITLE,metadata, corrected_srt)
        if result.success:
            logger.info(f"字幕翻译成功，内容长度: {len(result.content)}")
            translated_file = Path("test_mode/PRED-726-uncensored-nyap2p.com.zh.srt")
            translated_file.write_text(result.content, encoding="utf-8")
            logger.info(f"翻译结果已保存到: {translated_file}")
        else:
            logger.error(f"字幕翻译失败: {result.error}")
            sys.exit(1)

        logger.info("所有任务完成成功！")

    except FileNotFoundError as e:
        logger.error(f"文件未找到: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"程序执行过程中发生错误: {e}")
        sys.exit(1)