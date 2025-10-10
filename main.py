import os
import sys
import json
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

        logger.info("=" * 80)
        logger.info("开始字幕校正...")
        logger.info("=" * 80)

        corrected_file = Path("test_mode/PRED-726-uncensored-nyap2p.com.corrected.srt")
        result = translator.correct_or_translate_subtitle(TaskType.CORRECT_SUBTITLE, metadata, test_srt)

        if result.success:
            logger.info(f"✓ 字幕校正成功")
            logger.info(f"  - 内容长度: {len(result.content)} 字符")
            logger.info(f"  - API 调用次数: {result.attempt_count}")
            logger.info(f"  - 总耗时: {result.time_taken} 毫秒 ({result.time_taken / 1000:.2f} 秒)")

            # 解析并保存 JSON 结果
            try:
                # 先保存原始内容，以便后续分析
                raw_file = Path("test_mode/PRED-726-corrected-raw1.txt")
                raw_file.write_text(result.content, encoding="utf-8")
                logger.info(f"  - 原始响应已保存到: {raw_file}")

                # 尝试解析JSON
                corrected_srt = None
                try:
                    result_json = json.loads(result.content)
                    corrected_srt = result_json.get("content", "")
                    logger.info(f"  - 成功解析JSON格式响应")
                except json.JSONDecodeError:
                    # 如果不是JSON，检查是否以{开头（可能是不完整的JSON）
                    content_stripped = result.content.strip()
                    if content_stripped.startswith('{'):
                        logger.warning(f"响应以{{开头但JSON解析失败，尝试提取第一个有效JSON对象...")
                        try:
                            decoder = json.JSONDecoder()
                            result_json, idx = decoder.raw_decode(result.content)
                            corrected_srt = result_json.get("content", "")
                            logger.info(f"  - 成功提取JSON对象（位置0-{idx}），忽略了后续{len(result.content)-idx}个字符")
                        except (json.JSONDecodeError, AttributeError, ValueError):
                            logger.warning(f"JSON提取失败，将整个响应视为SRT内容")
                            corrected_srt = result.content
                    else:
                        # 不是JSON格式，直接将整个响应视为SRT内容
                        logger.warning(f"响应不是JSON格式，将整个响应视为SRT内容")
                        corrected_srt = result.content

                if not corrected_srt:
                    logger.error("无法提取任何内容")
                    sys.exit(1)

                corrected_file.write_text(corrected_srt, encoding="utf-8")
                logger.info(f"  - 校正结果已保存到: {corrected_file}")

                # 如果有 differences，保存到单独文件
                if result.differences:
                    diff_file = Path("test_mode/PRED-726-corrected-differences.json")
                    diff_file.write_text(json.dumps(result.differences, ensure_ascii=False, indent=2), encoding="utf-8")
                    logger.info(f"  - 改动记录已保存到: {diff_file}")
                    logger.info(f"  - 关键改动数量: {len(result.differences)}")
            except Exception as e:
                logger.error(f"处理结果时发生错误: {e}")
                import traceback
                traceback.print_exc()
                sys.exit(1)
        else:
            logger.error(f"✗ 字幕校正失败")
            logger.error(f"  - API 调用次数: {result.attempt_count}")
            logger.error(f"  - 总耗时: {result.time_taken} 毫秒")
            sys.exit(1)

        logger.info("=" * 80)
        logger.info("开始字幕翻译...")
        logger.info("=" * 80)

        corrected_srt = corrected_file.read_text(encoding="utf-8")
        result = translator.correct_or_translate_subtitle(TaskType.TRANSLATE_SUBTITLE, metadata, corrected_srt)

        if result.success:
            logger.info(f"✓ 字幕翻译成功")
            logger.info(f"  - 内容长度: {len(result.content)} 字符")
            logger.info(f"  - API 调用次数: {result.attempt_count}")
            logger.info(f"  - 总耗时: {result.time_taken} 毫秒 ({result.time_taken / 1000:.2f} 秒)")

            # 解析并保存 JSON 结果
            try:
                # 先保存原始内容，以便后续分析
                raw_file = Path("test_mode/PRED-726-translated-raw.txt")
                raw_file.write_text(result.content, encoding="utf-8")
                logger.info(f"  - 原始响应已保存到: {raw_file}")

                # 尝试解析JSON
                translated_srt = None
                try:
                    result_json = json.loads(result.content)
                    translated_srt = result_json.get("content", "")
                    logger.info(f"  - 成功解析JSON格式响应")
                except json.JSONDecodeError:
                    # 如果不是JSON，检查是否以{开头（可能是不完整的JSON）
                    content_stripped = result.content.strip()
                    if content_stripped.startswith('{'):
                        logger.warning(f"响应以{{开头但JSON解析失败，尝试提取第一个有效JSON对象...")
                        try:
                            decoder = json.JSONDecoder()
                            result_json, idx = decoder.raw_decode(result.content)
                            translated_srt = result_json.get("content", "")
                            logger.info(f"  - 成功提取JSON对象（位置0-{idx}），忽略了后续{len(result.content)-idx}个字符")
                        except (json.JSONDecodeError, AttributeError, ValueError):
                            logger.warning(f"JSON提取失败，将整个响应视为SRT内容")
                            translated_srt = result.content
                    else:
                        # 不是JSON格式，直接将整个响应视为SRT内容
                        logger.warning(f"响应不是JSON格式，将整个响应视为SRT内容")
                        translated_srt = result.content

                if not translated_srt:
                    logger.error("无法提取任何内容")
                    sys.exit(1)

                translated_file = Path("test_mode/PRED-726-uncensored-nyap2p.com.zh.srt")
                translated_file.write_text(translated_srt, encoding="utf-8")
                logger.info(f"  - 翻译结果已保存到: {translated_file}")
            except Exception as e:
                logger.error(f"处理结果时发生错误: {e}")
                import traceback
                traceback.print_exc()
                sys.exit(1)
        else:
            logger.error(f"✗ 字幕翻译失败")
            logger.error(f"  - API 调用次数: {result.attempt_count}")
            logger.error(f"  - 总耗时: {result.time_taken} 毫秒")
            sys.exit(1)

        logger.info("=" * 80)
        logger.info("✓ 所有任务完成成功！")
        logger.info("=" * 80)

    except FileNotFoundError as e:
        logger.error(f"文件未找到: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"程序执行过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)