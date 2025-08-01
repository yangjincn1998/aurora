# == text_translator.py ==
"""
一个功能强大的文本翻译模块，集成DeepSeek和Google Gemini API。

主要功能:
- 支持翻译SRT字幕文件、元数据（演员、类型等）和普通文本（如标题）。
- 实现了智能API回退机制，当一个模型失败时自动尝试下一个。
- 精确处理API的各种错误，特别是对速率限制（每分钟/每日）有专门的应对策略。
- 内置多层缓存机制，避免对相同元数据进行重复翻译，节省成本和时间。
- 使用并发处理来加速SRT文件的分块翻译。
"""

import os
import logging
import json
import time
import re
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 第三方库导入 ---
import openai
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv
from google.api_core import exceptions as google_exceptions

# --- 从我们自己的模块导入 ---
from config import (DEEPSEEK_API_KEY, GEMINI_API_KEY, DEEPSEEK_BASE_URL,
                    METADATA_CACHE_DIR, SCH_SUB_DIR, JAP_SUB_DIR, VIDEO_LIBRARY_DIRECTORY,
                    SRT_PROMPT, META_PROMPT, TITLE_PROMPT)
from exceptions import FatalError

logger = logging.getLogger(__name__)
load_dotenv()

# --- 模块级常量与配置 ---
_INTERNAL_CONCURRENCY_LEVEL = 4
_SRT_CHUNK_SIZE = 100
_RATE_LIMIT_WAIT_SECONDS = 65

# 定义默认的模型调用优先级
# 用于元数据和标题等短文本，优先考虑成本效益
_DEFAULT_METADATA_MODELS: List[str] = ['deepseek', 'gemini-flash']
# 用于SRT等长文本，优先考虑质量
_DEFAULT_SRT_MODELS: List[str] = ['deepseek', 'gemini-pro']

# --- Few-shot 示例 ---
# Few-shot示例与逻辑紧密耦合，因此保留在此模块内部
EXAMPLES_META: Dict[str, str] = {
    "天晴乃愛": "天晴乃爱", "木野々葉え": "木野野叶绘", "美園和花": "美园和花",
    "葵": "葵", "羽咲みはる": "羽咲美晴", "湊莉久": "凑莉久", "辻本杏": "辻本杏",
    "水卜さくら": "水卜樱", "和香なつき": "和香夏树", "滝口シルヴィア": "泷口西尔维娅",
    "らくだ": "骆驼", "薄刃紫翠": "薄刃紫翠", "毒丸": "毒丸", "TOHJIRO": "TOHJIRO",
    "96★": "96★", "麒麟": "麒麟", "N/A": "不详", "きとるね川口": "基托鲁内·川口",
    "ひょん": "Hyon", "HAM.the MC": "HAM.the MC", "WAKAHORI": "若堀", "X": "X",
    "豆沢豆太郎": "豆泽豆太郎", "苺原": "莓原", "キョウセイ": "Kyousei", "紋℃": "纹℃"
}
EXAMPLES_TITLE: Dict[str, str] = {
    "FRED-382 絶倫すぎるボクをドスケベ肉感ポーズ淫語で慰めてくれるカレン先生…": "用淫荡肉感姿势和淫语安慰精力过于旺盛的我的花恋老师…",
    "FSDSS-149 彼女の妹は僕の性欲処理係。": "女友的妹妹是我的性欲处理员。",
    "(Dogma)(DDT-475)解禁フィスト レズ 樹花凜 美咲結衣": "解禁 拳交女同性恋 樱花凛 美咲结衣",
}


# --- 内部异常 ---
class _APITranslationError(Exception):
    """API翻译过程中发生的通用错误。"""
    pass


class _LengthLimitError(Exception):
    """表示翻译文本长度超过限制的异常。"""
    pass


class _RequestPerMinuteLimitError(Exception):
    """表示已达到每分钟请求速率限制的异常。"""
    pass


class _RequestPerDayLimitError(Exception):
    """表示已达到每日请求配额限制的异常。"""
    pass


class _InsufficientResourcesError(Exception):
    """表示后端资源不足的异常。"""
    pass


# --- API客户端初始化 ---
deepseek_client = openai.OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL) if DEEPSEEK_API_KEY else None
gemini_model_pro, gemini_model_flash = None, None
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model_pro = genai.GenerativeModel('gemini-1.5-pro')
        gemini_model_flash = genai.GenerativeModel('gemini-1.5-flash')
        logger.info("Gemini API 客户端初始化成功。")
    except Exception as e:
        logger.error(f"Gemini API 初始化失败: {e}")

# --- 缓存管理 ---
CACHES: Dict[str, Dict[str, Any]] = {
    "actor": {"data": {}, "file": METADATA_CACHE_DIR / "actors_cache.json"},
    "genre": {"data": {}, "file": METADATA_CACHE_DIR / "genres_cache.json"},
    "director": {"data": {}, "file": METADATA_CACHE_DIR / "directors_cache.json"},
}


def _load_caches() -> None:
    """从JSON文件加载所有缓存到内存中。"""
    for cache_info in CACHES.values():
        if cache_info["file"].exists():
            try:
                with open(cache_info["file"], 'r', encoding='utf-8') as f:
                    cache_info["data"].update(json.load(f))
            except json.JSONDecodeError:
                logger.warning(f"缓存文件 {cache_info['file']} 已损坏，将忽略。")


_load_caches()


def save_all_caches() -> None:
    """将内存中的所有缓存保存到各自的JSON文件中。"""
    for cache_info in CACHES.values():
        try:
            with open(cache_info["file"], 'w', encoding='utf-8') as f:
                json.dump(cache_info["data"], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存缓存到 {cache_info['file']} 时出错: {e}", exc_info=True)


# --- 内部API调用辅助函数 ---
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=3, max=10))
def _call_deepseek_api(system_prompt: str, user_prompt: str) -> str:
    """
    使用流式请求调用DeepSeek API，并在结束后统一处理响应。

    Raises:
        _APITranslationError: API客户端未初始化或发生API错误。
        _LengthLimitError: 响应因长度限制被截断。
        _InsufficientResourcesError: 后端资源不足。
    """
    if not deepseek_client:
        raise _APITranslationError("DeepSeek API客户端未初始化。")

    final_user_prompt = f"{uuid.uuid4()}\n{user_prompt}"
    try:
        stream = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": f'{uuid}\n{system_prompt}'},
                {"role": "user", "content": final_user_prompt}
            ],
            temperature=0.1,
            stream=True
        )

        collected_content, finish_reason = [], None
        for chunk in stream:
            if chunk.choices:
                if chunk.choices[0].delta.content:
                    collected_content.append(chunk.choices[0].delta.content)
                if chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason

        # 在接收完所有数据后处理 'finish_reason'
        if finish_reason == 'length':
            logger.warning("DeepSeek API 流传输因长度限制中断。")
            raise _LengthLimitError("翻译文本长度超过限制。")
        elif finish_reason == 'content_filter':
            logger.warning("DeepSeek API 流传输因内容安全策略中断。")
            raise _APITranslationError("内容被安全策略拦截。")
        elif finish_reason == 'insufficient_funds':
            logger.warning("DeepSeek API 后端推理资源不足。")
            raise _InsufficientResourcesError("后端资源不足。")
        elif finish_reason not in ['stop', None]:
            logger.error(f"DeepSeek API 流传输因未知原因中断: {finish_reason}")
            raise _APITranslationError(f"未知的流传输中断原因: {finish_reason}")

        full_response = "".join(collected_content)
        if not full_response and finish_reason == 'stop':
            raise _APITranslationError("API 返回了 'stop' 但内容为空。")
        return full_response

    except openai.APIError as e:
        raise _APITranslationError(f"DeepSeek API错误: {e}") from e


def _call_gemini_api(system_prompt: str, user_prompt: str, model_name: str) -> str:
    """
    调用Gemini API，并能精确捕获、记录和抛出不同类型的错误。

    Raises:
        _APITranslationError: API客户端未初始化或发生通用API错误。
        _RequestPerDayLimitError: 达到每日配额上限。
        _RequestPerMinuteLimitError: 达到每分钟速率限制。
    """
    model_instance = gemini_model_pro if model_name == 'gemini-pro' else gemini_model_flash
    if not model_instance:
        raise _APITranslationError(f"Gemini模型 '{model_name}' 未初始化。")

    model_with_prompt = genai.GenerativeModel(model_instance.model_name, system_instruction=system_prompt)
    final_user_prompt = f"{uuid.uuid4()}\n{user_prompt}"

    try:
        response = model_with_prompt.generate_content(
            final_user_prompt,
            generation_config=genai.types.GenerationConfig(temperature=0.1)
        )
        if response.parts:
            return response.text

        if response.prompt_feedback.block_reason:
            reason = response.prompt_feedback.block_reason.name
            logger.error(f"Gemini API 请求被安全策略拦截，原因: {reason}")
            raise _APITranslationError(f"内容被安全策略拦截: {reason}")

        raise _APITranslationError("Gemini API返回了未知原因的空内容。")

    except google_exceptions.ResourceExhausted as e:
        error_str = str(e).lower()
        if "per_project_per_day" in error_str:
            logger.error("Gemini API 错误：已达到【每日】请求配额上限。")
            raise _RequestPerDayLimitError("已达到每日请求配额上限。") from e
        elif "per_minute" in error_str:
            logger.warning("Gemini API 错误：已达到【每分钟】请求速率限制。")
            raise _RequestPerMinuteLimitError("已达到每分钟请求速率限制。") from e
        else:
            logger.warning(f"Gemini API 错误：资源耗尽 (429)。{e}")
            raise _APITranslationError("账户资源耗尽或达到未知速率限制。") from e

    except google_exceptions.InvalidArgument as e:
        logger.error(f"Gemini API 错误：无效的参数 (400)。可能输入文本块过长或格式错误。详情: {e}")
        raise _APITranslationError(f"无效的参数: {e}") from e

    except google_exceptions.PermissionDenied as e:
        logger.critical(f"Gemini API 错误：权限被拒绝 (403)。请检查API密钥是否正确或已启用。")
        raise _APITranslationError(f"权限被拒绝/API密钥无效: {e}") from e

    except Exception as e:
        logger.error(f"Gemini API 发生未知错误: {e}", exc_info=True)
        raise _APITranslationError(f"Gemini API发生未知错误: {e}") from e


# --- 核心功能函数 ---
def _translate_text_chunk(
        text_chunk: str,
        system_prompt: str,
        context: Optional[str] = None,
        model_list: Optional[List[str]] = None
) -> str | _APITranslationError:
    """
    使用模型列表翻译单个文本块，带回退和重试逻辑。
    """
    user_prompt = f"【上文回顾 (仅供参考)】:\n{context}\n\n【请翻译以下核心内容】:\n{text_chunk}" if context else text_chunk

    active_model_list = model_list if model_list is not None else _DEFAULT_SRT_MODELS
    last_exception: Optional[Exception] = None

    for model in active_model_list:
        try:
            if model.startswith('gemini'):
                model_type = 'gemini-pro' if 'pro' in model else 'gemini-flash'
                return _call_gemini_api(system_prompt, user_prompt, model_type)
            elif model == 'deepseek':
                return _call_deepseek_api(system_prompt, user_prompt)

        except _RequestPerDayLimitError as e:
            logger.error(f"模型 '{model}' 每日配额已满: {e}。尝试下一个模型。")
            last_exception = e
            continue

        except _RequestPerMinuteLimitError as e:
            logger.warning(f"模型 '{model}' 达到每分钟速率限制。等待 {_RATE_LIMIT_WAIT_SECONDS}秒后重试该模型。")
            last_exception = e
            time.sleep(_RATE_LIMIT_WAIT_SECONDS)
            try:
                # 重试当前模型
                if model.startswith('gemini'):
                    model_type = 'gemini-pro' if 'pro' in model else 'gemini-flash'
                    return _call_gemini_api(system_prompt, user_prompt, model_type)
                elif model == 'deepseek':
                    return _call_deepseek_api(system_prompt, user_prompt)
            except Exception as retry_e:
                logger.error(f"模型 '{model}' 重试后仍然失败: {retry_e}")
                last_exception = retry_e
                continue  # 重试失败，尝试下一个模型

        except Exception as e:
            logger.error(f"模型 '{model}' 翻译时发生错误: {e}。尝试下一个模型。")
            last_exception = e
            continue

    raise _APITranslationError(f"所有翻译模型均失败。最后错误: {last_exception}") from last_exception


def _translate_srt_text(japanese_srt_text: str, movie_metadata: Dict[str, Any]) -> str:
    """将完整的SRT文本分块并并发翻译。"""
    metadata_str = json.dumps(movie_metadata, ensure_ascii=False, indent=2)
    system_prompt = SRT_PROMPT.format(movie_metadata=metadata_str)

    srt_blocks = re.split(r'\n\n(?=\d+\n)', japanese_srt_text.strip())
    chunks = ["\n\n".join(srt_blocks[i:i + _SRT_CHUNK_SIZE]) for i in range(0, len(srt_blocks), _SRT_CHUNK_SIZE)]
    translated_chunks = [""] * len(chunks)

    with ThreadPoolExecutor(max_workers=_INTERNAL_CONCURRENCY_LEVEL) as executor:
        future_map = {
            executor.submit(
                _translate_text_chunk,
                chunks[i],
                system_prompt,
                chunks[i - 1] if i > 0 else "",
                _DEFAULT_SRT_MODELS
            ): i for i in range(len(chunks))
        }
        for future in as_completed(future_map):
            index = future_map[future]
            try:
                translated_chunks[index] = future.result()
            except Exception as e:
                raise _APITranslationError(f"SRT切片 {index + 1} 翻译失败") from e

    return "\n\n".join(translated_chunks)


# --- 公开接口 ---

def translate_simple_text(text: str, content_type: str) -> str | _APITranslationError:
    """
    翻译无需缓存的简单文本（如标题或通用元数据）。

    Args:
        text: 待翻译的原文。
        content_type: 内容类型，'title' 或 'general'。

    Returns:
        翻译后的文本，失败则返回原文。
    """
    if not text or text == "N/A":
        return "不详"


    prompt = TITLE_PROMPT if content_type == 'title' else META_PROMPT
    examples = EXAMPLES_TITLE if content_type == 'title' else EXAMPLES_META

    user_prompt_with_examples = "\n".join(
        [f"原文: {k}\n译文: {v}" for k, v in examples.items()]
    ) + f"\n\n原文: {text}\n译文:"

    try:
        return _translate_text_chunk(
            user_prompt_with_examples,
            system_prompt=prompt,
            model_list=_DEFAULT_METADATA_MODELS
        )
    except _APITranslationError as e:
        logger.warning(f"文本项 '{text}' ({content_type}) 翻译失败: {e}。将返回原文。")
        raise e


def translate_metadata_item(text: str, item_type: str) -> str:
    """
    翻译需要缓存的单个元数据项（如演员、类别），并管理缓存。

    Args:
        text: 待翻译的原文。
        item_type: 元数据类型 ('actor', 'genre', 'director')。

    Returns:
        翻译后的文本，或从缓存中获取的结果。
    """
    if not text or text == "N/A":
        return "不详"
    if item_type not in CACHES:
        raise ValueError(f"未知的元数据缓存类型: {item_type}")

    cache_info = CACHES[item_type]
    if text in cache_info["data"]:
        logging.info(f"缓存命中{text}:{cache_info['data'][text]}")
        return cache_info["data"][text]

    # 复用 simple_text 的翻译逻辑
    translated_text = translate_simple_text(text, 'general')

    # 仅在翻译成功时（即译文与原文不同）存入缓存
    if translated_text != text:
        cache_info["data"][text] = translated_text
    logging.info(f'翻译成功{text} -> {translated_text}')
    return translated_text


def translate_srt_worker(
        av_code: str,
        segment_id: str,
        jap_srt_path_str: str,
        metadata_path_str: str,
        force: bool = False
) -> Dict[str, str]:
    """
    【工人函数】负责编排单个SRT文件的完整翻译流程。

    这是一个独立的任务单元，负责文件I/O、调用翻译核心并保存结果。

    Args:
        av_code: 影片番号。
        segment_id: 分段ID。
        jap_srt_path_str: 日语SRT文件路径。
        metadata_path_str: 元数据JSON文件路径。
        force: 是否强制重新翻译。

    Returns:
        一个包含任务状态的字典。

    Raises:
        FatalError: 当发生无法恢复的错误时（如文件缺失、翻译核心失败）。
    """
    logger.info(f"--- 开始处理番号 {av_code} (分段: {segment_id}) 的【核心流程：SRT翻译】 ---")
    jap_srt_path = Path(jap_srt_path_str)
    metadata_path = Path(metadata_path_str)
    sch_srt_path = SCH_SUB_DIR / (Path(segment_id).stem + ".srt")

    if sch_srt_path.exists() and not force:
        logger.info(f"目标文件 {sch_srt_path} 已存在，跳过翻译。")
        return {'status': 'skipped', 'av_code': av_code, 'segment_id': segment_id}

    try:
        if not jap_srt_path.exists():
            raise FatalError(f"依赖文件缺失：{jap_srt_path}")

        movie_metadata = json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.exists() else {}
        japanese_text = jap_srt_path.read_text(encoding='utf-8')

        translated_text = _translate_srt_text(japanese_text, movie_metadata)

        sch_srt_path.parent.mkdir(parents=True, exist_ok=True)
        sch_srt_path.write_text(translated_text, encoding='utf-8')

        logger.info(f"成功翻译并保存 SRT 文件到: {sch_srt_path}")
        return {'status': 'success', 'av_code': av_code, 'segment_id': segment_id}

    except Exception as e:
        # 将所有未捕获的异常包装成 FatalError，以便上层统一处理
        logger.critical(f"为 {av_code} ({segment_id}) 进行SRT翻译时发生致命错误: {e}", exc_info=True)
        raise FatalError(f"SRT翻译失败: {e}") from e
    finally:
        # 确保每次任务执行后都尝试保存缓存
        save_all_caches()


# --- 测试入口 ---
if __name__ == '__main__':
    # 配置一个简单的日志记录器用于测试
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # 创建一个临时的测试文件
    temp_dir = Path('_temp/sub_jap')
    temp_dir.mkdir(parents=True, exist_ok=True)
    test_srt_path = temp_dir / 'test_srt.srt'

    # 写入一些简单的 SRT 内容
    test_srt_content = (
        "1\n00:00:01,000 --> 00:00:03,000\nこんにちは、世界！\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\nこれはテストです。"
    )
    test_srt_path.write_text(test_srt_content, encoding='utf-8')

    print("--- 开始测试 DeepSeek API 调用 ---")
    try:
        if deepseek_client:
            with open(test_srt_path, mode='r', encoding='utf-8') as f:
                srt_content = f.read()
            translated = _call_deepseek_api(SRT_PROMPT, srt_content)
            print("DeepSeek API 测试翻译结果:")
            print(translated)
        else:
            print("DeepSeek API 客户端未配置，跳过测试。")
    except Exception as e:
        print(f"DeepSeek API 测试失败: {e}")
    try:
        if gemini_model_pro:
            with open(test_srt_path, mode='r', encoding='utf-8') as f:
                srt_content = f.read()
            translated = _call_gemini_api(SRT_PROMPT, srt_content, 'gemini-pro')
            print("DeepSeek API 测试翻译结果:")
            print(translated)
        else:
            print("Gemini API 客户端未配置，跳过测试。")
    except Exception as e:
        print(f"Gemini API 测试失败: {e}")

    print("\n--- 开始测试元数据翻译 ---")
    try:
        actor_name = "天晴乃愛"
        translated_actor = translate_metadata_item(actor_name, "actor")
        print(f"原文: {actor_name} -> 译文: {translated_actor}")
        # 第二次调用应该命中缓存
        translated_actor_cached = translate_metadata_item(actor_name, "actor")
        print(f"第二次调用 (应命中缓存): {actor_name} -> 译文: {translated_actor_cached}")
    except Exception as e:
        print(f"元数据翻译测试失败: {e}")