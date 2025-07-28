# == text_translator.py ==

import logging
import json
import time
import re
import uuid
from pathlib import Path
from typing import Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 第三方库导入 ---
import openai
import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential

# --- 从我们自己的模块导入 ---
from config import (DEEPSEEK_API_KEY, GEMINI_API_KEY, DEEPSEEK_BASE_URL,
                    METADATA_CACHE_DIR, SCH_SUB_DIR, JAP_SUB_DIR, VIDEO_LIBRARY_DIRECTORY,
                    SRT_PROMPT, META_PROMPT, TITLE_PROMPT)
from exceptions import FatalError

logger = logging.getLogger(__name__)

# --- 模块级常量与配置 ---
INTERNAL_CONCURRENCY_LEVEL = 4
SRT_CHUNK_SIZE = 250


# Few-shot示例与逻辑紧密耦合，因此保留在此模块内部
EXAMPLES_META = {
    "天晴乃愛": "天晴乃爱",
    "木野々葉え": "木野野叶绘",
    "美園和花": "美园和花",
    "葵": "葵",
    "羽咲みはる": "羽咲美晴",
    "湊莉久": "凑莉久",
    "辻本杏": "辻本杏",
    "水卜さくら": "水卜樱",
    "和香なつき": "和香夏树",
    "滝口シルヴィア": "泷口西尔维娅",
    "らくだ": "骆驼",
    "薄刃紫翠": "薄刃紫翠",
    "毒丸": "毒丸",
    "TOHJIRO": "TOHJIRO",
    "96★": "96★",
    "麒麟": "麒麟",
    "N/A": "不详",
    "きとるね川口": "基托鲁内·川口",
    "ひょん": "Hyon",
    "HAM.the MC": "HAM.the MC",
    "WAKAHORI": "若堀",
    "X": "X",
    "豆沢豆太郎": "豆泽豆太郎",
    "苺原": "莓原",
    "キョウセイ": "Kyousei",
    "紋℃": "纹℃"
}
EXAMPLES_TITLE = {
    "FRED-382 絶倫すぎるボクをドスケベ肉感ポーズ淫語で慰めてくれるカレン先生…": "用淫荡肉感姿势和淫语安慰精力过于旺盛的我的花恋老师…",
    "FSDSS-149 彼女の妹は僕の性欲処理係。": "女友的妹妹是我的性欲处理员。",
    "(Dogma)(DDT-475)解禁フィスト レズ 樹花凜 美咲結衣": "解禁 拳交女同性恋 樱花凛 美咲结衣",
}


# --- 内部异常 ---
class _APITranslationError(Exception):
    pass


# --- API客户端初始化 ---
deepseek_client = openai.OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL) if DEEPSEEK_API_KEY else None
gemini_model_pro, gemini_model_flash = None, None
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        gemini_model_pro = genai.GenerativeModel('gemini-1.5-pro-latest')
        gemini_model_flash = genai.GenerativeModel('gemini-1.5-flash-latest')
        logger.info("Gemini API 客户端初始化成功。")
    except Exception as e:
        logger.error(f"Gemini API 初始化失败: {e}")

# --- 缓存管理 ---
CACHES = {
    "actor": {"data": {}, "file": METADATA_CACHE_DIR / "actors_cache.json"},
    "genre": {"data": {}, "file": METADATA_CACHE_DIR / "genres_cache.json"},
    "director": {"data": {}, "file": METADATA_CACHE_DIR / "directors_cache.json"},
}


def _load_caches():
    for cache_info in CACHES.values():
        if cache_info["file"].exists():
            try:
                with open(cache_info["file"], 'r', encoding='utf-8') as f:
                    cache_info["data"].update(json.load(f))
            except json.JSONDecodeError:
                logger.warning(f"缓存文件 {cache_info['file']} 已损坏，将忽略。")


_load_caches()


def save_all_caches():
    for cache_info in CACHES.values():
        try:
            with open(cache_info["file"], 'w', encoding='utf-8') as f:
                json.dump(cache_info["data"], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存缓存到 {cache_info['file']} 时出错: {e}", exc_info=True)


# --- 内部API调用辅助函数 ---
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=3, max=10))
def _call_deepseek_api(system_prompt: str, user_prompt: str) -> str:
    # ... (代码与上一版相同)
    if not deepseek_client: raise _APITranslationError("DeepSeek API客户端未初始化。")
    final_user_prompt = f"{uuid.uuid4()}\n{user_prompt}"
    response = deepseek_client.chat.completions.create(model="deepseek-chat",
                                                       messages=[{"role": "system", "content": system_prompt},
                                                                 {"role": "user", "content": final_user_prompt}],
                                                       temperature=0.1, stream=False)
    content = response.choices[0].message.content
    if content: return content
    raise _APITranslationError("DeepSeek API返回了空内容。")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=3, max=10))
def _call_gemini_api(system_prompt: str, user_prompt: str, model_name: str) -> str:
    # ... (代码与上一版相同)
    model_instance = gemini_model_pro if model_name == 'gemini-pro' else gemini_model_flash
    if not model_instance: raise _APITranslationError(f"Gemini模型 '{model_name}' 未初始化。")
    model_with_prompt = genai.GenerativeModel(model_instance.model_name, system_instruction=system_prompt)
    final_user_prompt = f"{uuid.uuid4()}\n{user_prompt}"
    response = model_with_prompt.generate_content(final_user_prompt,
                                                  generation_config=genai.types.GenerationConfig(temperature=0.1))
    if response.parts: return response.text
    raise _APITranslationError(f"Gemini API返回空内容, 可能原因: {response.prompt_feedback}")


# --- 核心功能函数 (文本级接口) ---
def _translate_text_chunk(text_chunk: str, system_prompt: str, context: str = "", model_list: List[str] = None) -> str:
    # ... (代码与上一版相同)
    user_prompt = f"【上文回顾 (仅供参考)】:\n{context}\n\n【请翻译以下核心内容】:\n{text_chunk}" if context else text_chunk
    last_exception = None
    for model in model_list:
        try:
            if model.startswith('gemini-pro'):
                return _call_gemini_api(system_prompt, user_prompt, 'gemini-pro')
            elif model.startswith('gemini-flash'):
                return _call_gemini_api(system_prompt, user_prompt, 'gemini-flash')
            elif model == 'deepseek':
                return _call_deepseek_api(system_prompt, user_prompt)
        except Exception as e:
            last_exception = e
            logger.warning(f"模型 '{model}' 翻译失败，尝试下一个模型... 错误: {e}")
            continue
    raise _APITranslationError(f"所有翻译模型均失败。最后错误: {last_exception}") from last_exception


def _translate_srt_text(japanese_srt_text: str, movie_metadata: dict) -> str:
    # ... (代码与上一版相同)
    metadata_str = json.dumps(movie_metadata, ensure_ascii=False, indent=2)
    system_prompt = SRT_PROMPT.format(movie_metadata=metadata_str)
    srt_blocks = re.split(r'\n\n(?=\d+\n)', japanese_srt_text.strip())
    chunks = ["\n\n".join(srt_blocks[i:i + SRT_CHUNK_SIZE]) for i in range(0, len(srt_blocks), SRT_CHUNK_SIZE)]
    translated_chunks = [""] * len(chunks)
    with ThreadPoolExecutor(max_workers=INTERNAL_CONCURRENCY_LEVEL) as executor:
        future_map = {executor.submit(_translate_text_chunk, chunks[i], system_prompt, chunks[i - 1] if i > 0 else "",
                                      ['gemini-pro', 'deepseek']): i for i in range(len(chunks))}
        for future in as_completed(future_map):
            index = future_map[future]
            try:
                translated_chunks[index] = future.result()
            except Exception as e:
                raise _APITranslationError(f"SRT切片 {index + 1} 翻译失败") from e
    return "\n\n".join(translated_chunks)


# --- 公开接口 ---

def translate_simple_text(text: str, content_type: str) -> str:
    """
    【新增公用功能】翻译无需缓存的简单文本（例如标题）。
    """
    if not text or text == "N/A": return "不详"
    prompt = TITLE_PROMPT if content_type == 'title' else META_PROMPT
    examples = EXAMPLES_TITLE if content_type == 'title' else EXAMPLES_META
    user_prompt_with_examples = "\n".join(
        [f"原文: {k}\n译文: {v}" for k, v in examples.items()]) + f"\n\n原文: {text}\n译文:"
    try:
        # 简单文本翻译优先使用更经济的Flash模型
        return _translate_text_chunk(user_prompt_with_examples, system_prompt=prompt,
                                     model_list=['gemini-flash', 'deepseek'])
    except _APITranslationError:
        logger.warning(f"文本项 '{text}' ({content_type}) 翻译失败，将返回原文。")
        return text


def translate_metadata_item(text: str, item_type: str) -> str:
    """【核心/公用功能】翻译【需要缓存】的单个元数据项（如演员、类别）。"""
    if not text or text == "N/A": return "不详"
    if item_type not in CACHES: raise ValueError(f"未知的元数据缓存类型: {item_type}")

    cache_info = CACHES[item_type]
    if text in cache_info["data"]: return cache_info["data"][text]

    # 调用 translate_simple_text 来执行翻译，实现逻辑复用
    translated_text = translate_simple_text(text, 'general')

    # 存入缓存
    if translated_text != text:  # 仅在翻译成功时缓存
        cache_info["data"][text] = translated_text
    return translated_text


def translate_srt_worker(av_code: str, segment_id: str, jap_srt_path_str: str, metadata_path_str: str,
                         force: bool = False) -> Dict:
    """【工人函数】负责编排单个SRT文件的翻译流程。"""
    # ... (代码与上一版相同)
    logger.info(f"--- 开始处理番号 {av_code} (分段: {segment_id}) 的【核心流程：SRT翻译】 ---")
    jap_srt_path = Path(jap_srt_path_str)
    metadata_path = Path(metadata_path_str)
    sch_srt_path = SCH_SUB_DIR / (Path(segment_id).stem + ".srt")
    if sch_srt_path.exists() and not force:
        return {'status': 'skipped', 'av_code': av_code, 'segment_id': segment_id}
    try:
        if not jap_srt_path.exists(): raise FatalError(f"依赖文件缺失：{jap_srt_path}")
        movie_metadata = json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.exists() else {}
        japanese_text = jap_srt_path.read_text(encoding='utf-8')
        translated_text = _translate_srt_text(japanese_text, movie_metadata)
        sch_srt_path.parent.mkdir(parents=True, exist_ok=True)
        sch_srt_path.write_text(translated_text, encoding='utf-8')
        return {'status': 'success', 'av_code': av_code, 'segment_id': segment_id}
    except Exception as e:
        raise FatalError(f"SRT翻译失败: {e}") from e
    finally:
        save_all_caches()