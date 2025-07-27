import os
import logging
from main import FatalError, IgnorableError, logger
import json
import time
import re
from reprlib import recursive_repr

import httpx
import uuid
from functools import wraps


import openai
from dotenv import load_dotenv
from openai import OpenAI
# Note: google.generativeai and google.api_core are not directly used in the provided
# _call_google_api function, which uses openai client with a custom base_url.
# If direct genai calls are intended, this part needs to be revised.
# from google.api_core import exceptions
# from google.cloud import translate
# from google.generativeai.types import HarmCategory, HarmBlockThreshold

import threading
from collections import OrderedDict

# --- 配置日志 ---
# 主日志文件，记录整个程序的运行情况
logging.basicConfig(
    filename='process.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    encoding='utf-8'
)

# --- 加载环境变量 ---
load_dotenv()

# --- 全局配置变量 ---
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") # 用于通过代理访问Google API
GOOGLE_CLOUD_TRANSLATE_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS') # 用于Google Cloud Translation API
BASE_URL_GOOGLE_PROXY = "https://api.qdgf.top/v1" # 代理Google API的URL
DEEPSEEK_BASE_URL = 'https://api.deepseek.com'

# --- Google Cloud Translation API 配置 (如果需要) ---
# 注意：原代码中虽然导入了google.cloud.translate，但实际翻译逻辑未使用。
# 如果需要使用，请在此处或相关函数中实现。
# google_cloud_translate_client = None
# if GOOGLE_CLOUD_TRANSLATE_CREDENTIALS:
#     try:
#         # 确保 GOOGLE_APPLICATION_CREDENTIALS 指向你的服务账号密钥文件路径
#         google_cloud_translate_client = translate.Client()
#         logging.info("Google Cloud Translation API 已配置。")
#     except Exception as e:
#         logging.error(f"初始化 Google Cloud Translation API 失败: {e}", exc_info=True)
#         logging.warning("Google Cloud Translation API 可能无法使用。")
# else:
#     logging.warning("GOOGLE_APPLICATION_CREDENTIALS 环境变量未设置。Google Cloud Translation API 将不可用。")

# --- LLM 提示加载 ---
try:
    with open('prompt.txt', mode='r', encoding='utf-8') as f:
        prompts_content = f.read()
    PROMPTS = prompts_content.split('\n\n')
    SRT_PROMPT = PROMPTS[0] if len(PROMPTS) > 0 else ""
    META_PROMPT = PROMPTS[1] if len(PROMPTS) > 1 else ""
    TITLE_PROMPT = PROMPTS[2] if len(PROMPTS) > 2 else ""
    if not SRT_PROMPT or not META_PROMPT:
        logging.warning("prompt.txt 文件内容不完整，请确保包含SRT和元数据提示。")
except FileNotFoundError:
    logging.error("prompt.txt 文件未找到。请确保提示文件存在。")
    SRT_PROMPT = "Translate the following Japanese SRT subtitle blocks into Chinese. Maintain the SRT format (sequence number, timestamps, text). Do not add any extra text outside the SRT blocks."
    META_PROMPT = "Translate the following Japanese text into simplified Chinese. Focus on accurate translation of names, genres, and titles. If the input is 'N/A', return '不详'. Examples:\n酒井ももか: 酒井桃香\n巨乳: 巨乳\nPRED-782 絶倫すぎるボクをドスケベ肉感ポーズ淫語で慰めてくれるカレン先生… 楪カレン: 精力过于旺盛的我被用淫荡肉感姿势和淫语安慰的Karen老师… 楪花恋"
except Exception as e:
    logging.error(f"加载 prompt.txt 时出错: {e}", exc_info=True)
    # 提供默认提示作为回退
    SRT_PROMPT = "Translate the following Japanese SRT subtitle blocks into Chinese. Maintain the SRT format (sequence number, timestamps, text). Do not add any extra text outside the SRT blocks."
    META_PROMPT = "Translate the following Japanese text into simplified Chinese. Focus on accurate translation of names, genres, and titles. If the input is 'N/A', return '不详'. Examples:\n酒井ももか: 酒井桃香\n巨乳: 巨乳\nPRED-782 絶倫すぎるボクをドスケベ肉感ポーズ淫语で慰めてくれるカレン先生… 楪カレン: 精力过于旺盛的我被用淫荡肉感姿势和淫语安慰的Karen老师… 楪花恋"


# --- 缓存目录和文件 ---
METADATA_CACHE_DIR = "metadata_cache"
os.makedirs(METADATA_CACHE_DIR, exist_ok=True)

ACTORS_CACHE_FILE = os.path.join(METADATA_CACHE_DIR, "actors_cache.json")
GENRES_CACHE_FILE = os.path.join(METADATA_CACHE_DIR, "genres_cache.json")
DIRECTORS_CACHE_FILE = os.path.join(METADATA_CACHE_DIR, "directors_cache.json")

# --- 全局缓存字典 ---
actors_cache = {}
genres_cache = {}
directors_cache = {}



def _load_cache(cache_file: str, cache_dict: dict):
    """
    从JSON文件加载缓存到字典。

    args:
        cache_file (str): 缓存文件路径。
        cache_dict (dict): 需要填充的缓存字典。
    """
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                cache_dict.update(data)
            logging.info(f"已从 {cache_file} 加载缓存。")
        except json.JSONDecodeError:
            logging.warning(f"缓存文件 {cache_file} 已损坏，正在初始化为空缓存。")
            cache_dict.clear() # 清空字典以确保从空状态开始
        except Exception as e:
            logging.error(f"加载缓存文件 {cache_file} 时出错: {e}", exc_info=True)
            cache_dict.clear() # 出现其他错误也清空缓存

def _save_cache(cache_dict: dict, cache_file: str):
    """
    将缓存字典保存到JSON文件。

    args:
        cache_dict (dict): 要保存的缓存字典。
        cache_file (str): 缓存文件路径。
    """
    try:
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(cache_dict, f, ensure_ascii=False, indent=4)
        logging.info(f"已将缓存保存到 {cache_file}。")
    except Exception as e:
        logging.error(f"保存缓存到 {cache_file} 时出错: {e}", exc_info=True)

# 程序启动时加载所有缓存
_load_cache(ACTORS_CACHE_FILE, actors_cache)
_load_cache(GENRES_CACHE_FILE, genres_cache)
_load_cache(DIRECTORS_CACHE_FILE, directors_cache)



# --- 全局 HTTP 客户端和 OpenAI 客户端初始化 ---
# 创建一个不验证SSL证书的 httpx 客户端，用于代理访问
custom_http_client = httpx.Client(
    headers={
"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    },
    http1=True,
    verify=False
)# 禁用SSL验证

# 初始化 DeepSeek OpenAI 客户端
deepseek_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

# 初始化 Google OpenAI 客户端 (通过代理访问)
google_client = OpenAI(
    api_key=GOOGLE_API_KEY,
    base_url=BASE_URL_GOOGLE_PROXY,
    http_client=custom_http_client
)

def _extract_srt(text: str) -> str:
    """
    从文本中提取并标准化 SRT 字幕信息。

    args:
        text (str): 包含 SRT 字幕的文本。

    return:
        str: 提取出的所有符合 SRT 格式的字幕块。
    """
    # 匹配 SRT 字幕块的正则表达式
    # (\d+)\s* - 字幕序号（数字），后面可能有空格
    # (\d{2}:\d{2}:\d{2},\d{3})\s* - 开始时间（HH:MM:SS,mmm），后面可能有空格
    # -->\s* - 时间分隔符，后面可能有空格
    # (\d{2}:\d{2}:\d{2},\d{3})\s* - 结束时间（HH:MM:SS,mmm），后面可能有空格
    # ([\s\S]*?) - 字幕文本内容，非贪婪匹配，[\s\S] 匹配所有字符包括换行符
    # (?=\n*\s*\d+\s*\n\s*\d{2}:\d{2}:|\Z) - 正向先行断言，表示直到下一个字幕块的序号和时间开始，
    #                                      或者直到文本结束（\Z）
    # re.DOTALL 使 . 匹配包括换行符在内的所有字符
    srt_pattern = r'(\d+)\s*\n\s*(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n([\s\S]*?)(?=\n*\s*\d+\s*\n\s*\d{2}:\d{2}:|\Z)'

    matches = re.findall(srt_pattern, text, re.DOTALL)

    if not matches:
        logger.warning(f"在文本中未找到匹配的 SRT 块。原始文本可能不包含有效的 SRT 格式。")
        logger.debug(f"未能提取 SRT 的原始文本: \n{text[:500]}...") # 记录前500字符
        return ""

    extracted_srt_blocks = []
    for match in matches:
        # match 的顺序是 (序号, 开始时间, 结束时间, 字幕文本)
        # 确保块内容被去除多余空白并格式正确
        # strip() 用于去除文本开头和结尾的空白，包括换行符
        block = f"{match[0]}\n{match[1]} --> {match[2]}\n{match[3].strip()}"
        extracted_srt_blocks.append(block)

    # 用双换行符连接以符合 SRT 块之间的标准格式
    return "\n\n".join(extracted_srt_blocks).strip()

def _prepare_messages(system_message: str, examples: dict[str, str], user_message: str,content_type: str) -> list[dict]:
    """
    构造用于API调用的消息列表。

    args:
        system_message (str): 系统提示词。
        examples (dict): 示例对话。
        user_message (str): 用户输入内容。

    return:
        list: 消息字典列表。
    """
    if content_type == 'srt':
        messages = [{"role": "system", "content": f"{system_message}"}]
        for query, ans in examples.items():
            messages.append({"role": "user", "content": f"{uuid.uuid4()}\n{query}"})
            messages.append({"role": "assistant", "content": ans})
        messages.append({"role": "user", "content": f"{uuid.uuid4()}\n{user_message.strip()}"})
    else:
        messages = [{"role": "system", "content": f"{system_message}"}]
        for query, ans in examples.items():
            messages.append({"role": "user", "content": f"{query}"})
            messages.append({"role": "assistant", "content": ans})
        messages.append({"role": "user", "content": f"{user_message.strip()}"})
    return messages

def _api_call_with_retry(api_client: OpenAI, model_name: str, messages: list[dict], temperature: float, max_tokens: int, frequency_penalty: float, retry_limit: int = 3) -> tuple[int, str | None]:
    """
    通用API调用函数，带重试机制。

    args:
        api_client (OpenAI): OpenAI客户端。
        model_name (str): 模型名称。
        messages (list): 消息内容。
        temperature (float): 采样温度。
        max_tokens (int): 最大token数。
        frequency_penalty (float): 频率惩罚。
        retry_limit (int): 最大重试次数。

    return:
        tuple: (状态码, 返回内容)
    """

    for retry_count in range(retry_limit + 1):
        try:
            start_time = time.time()
            response = api_client.chat.completions.create(
                model=model_name,
                messages=messages,
                stream=False,
                temperature=temperature,
                max_tokens=max_tokens,
                frequency_penalty=frequency_penalty
            )
            end_time = time.time()

            finish_reason = response.choices[0].finish_reason
            content = response.choices[0].message.content

            if finish_reason == 'stop':
                log_msg = f'API 调用成功 ({model_name})，输入文本长度 {len(messages[-1]["content"])}，耗时: {end_time - start_time:.2f} 秒'
                logger.info(log_msg)
                print(log_msg)
                return 0, content
            elif finish_reason == 'length':
                logger.warning(f"API 调用 ({model_name}) 因长度限制而失败。建议截断/分割输入。")
                return 1, None # 返回可重试状态
            elif finish_reason == 'insufficient_system_resources':
                logger.error(f"API 调用 ({model_name}) 因系统资源不足而失败。正在重试 ({retry_count + 1}/{retry_limit})...")
                if retry_count < retry_limit:
                    sleep_time = 5 * (2 ** retry_count)
                    time.sleep(sleep_time)
                    continue
                else:
                    logger.error(f"API 调用 ({model_name}) 达到最大重试次数，放弃请求。")
                    return 2, None
            else:
                logger.error(f"API 调用 ({model_name}) 以未处理的原因结束: {finish_reason}, 内容: {content}")
                return 2, None

        except openai.BadRequestError as e:
            logger.error(f"API 请求参数错误 ({model_name})： {e}", exc_info=True)
            print(f"API 请求参数错误 ({model_name})： {e}")
            return 2, None
        except openai.AuthenticationError as e:
            logger.error(f"API 身份验证错误 ({model_name})： {e}", exc_info=True)
            print(f"API 身份验证错误 ({model_name})： {e}")
            return 2, None
        except openai.PermissionDeniedError as e:
            logger.error(f"API 权限被拒绝 ({model_name})： {e}", exc_info=True)
            print(f"API 权限被拒绝 ({model_name})： {e}")
            return 2, None
        except openai.RateLimitError as e:
            logger.warning(f"API 请求过于频繁 ({model_name})： {e}. 正在重试 ({retry_count + 1}/{retry_limit})...", exc_info=True)
            print(f"API 请求过于频繁 ({model_name})： {e}")
            if retry_count < retry_limit:
                sleep_time = 5 * (2 ** retry_count)
                time.sleep(sleep_time)
                continue
            else:
                logger.error(f"API 调用 ({model_name}) 达到最大重试次数，放弃请求。")
                return 2, None
        except openai.NotFoundError as e:
            logger.error(f"API 模型未找到 ({model_name})： {e}", exc_info=True)
            print(f"API 模型未找到 ({model_name})： {e}")
            return 2, None
        except Exception as e:
            logger.error(f"API 调用 ({model_name}) 发生意外错误: {e}", exc_info=True)
            print(f"API 调用 ({model_name}) 发生意外错误: {e}")
            if retry_count < retry_limit:
                sleep_time = 5 * (2 ** retry_count)
                logger.info(f"发生未知错误，将在 {sleep_time} 秒后重试 ({retry_count + 1}/{retry_limit})...")
                time.sleep(sleep_time)
                continue
            else:
                logger.error(f"API 调用 ({model_name}) 达到最大重试次数，放弃请求。")
                return 2, None
    return 2, None # 如果循环结束仍未成功

def translate_text(
        japanese_text: str,
        translator_model_list: list[str] = None,  # 动态根据content_type决定默认模型
        content_type: str = 'general',  # 'general', 'srt'或‘title’
        movie_metadata: dict = None,  # 可选的电影元数据，用于 SRT 翻译
        recursive_depth: int = 0
) -> str | Exception:
    """
    使用指定的 LLM 将日文文本翻译成中文，支持通用文本和SRT字幕。

    args:
        japanese_text (str): 日文原文。
        translator_model_list (list[str]): 翻译模型名列表。
        content_type (str): 翻译内容类型（'general' 或 'srt'）。
        movie_metadata (dict): 影片元数据。
        recursive_depth (int): 递归深度，用于避免无限递归。

    return:
        str | None: 翻译结果，失败返回None。
    """
    if recursive_depth > 2:
        logging.error('递归深度过深，重新设置切片长度')
        if content_type == 'srt':
            raise FatalError('递归深度过深，重新设置切片长度')
        else:
            raise IgnorableError('递归深度过深，重新设置切片长度')

    if not japanese_text or not japanese_text.strip():
        return ""

    # 根据内容类型动态选择默认翻译模型
    if translator_model_list is None:
        if content_type == 'srt':
            translator_model_list = ['gemini-2.5-pro', 'deepseek-chat']
        elif content_type == 'general':
            translator_model_list = ['deepseek-chat', 'gemini-2.5-pro']
        elif content_type == 'title':
            translator_model_list = ['gemini-2.5-pro', 'deepseek-chat']
        else:
            translator_model_list = ['deepseek-chat', 'gemini-2.5-pro']
            logger.warning('Wrong Args content_type, using default models: deepseek-chat, gemini-2.5-pro')



    # 定义不同翻译内容的示例和模型参数
    translation_configs = {
        'general': {
            'prompt': META_PROMPT,
            'examples': {
                "酒井ももか": "酒井桃香",
                "二宮和香": "二宫和香",
                "早川瀬里奈": "早川濑里奈",
                "森沢かな（飯岡かなこ）": "森泽佳奈（饭冈佳奈子）",
                "波多野結衣": "波多野结衣",
                "竹内夏希": "竹内夏希",
                "みづなれい（みずなれい）": "水菜丽",
                "美咲結衣": "美咲结衣",
                "Maiko Satomi": "里美真衣子",
                "PornStars": "PornStars",
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
                "單體作品": "单体作品",
                "妓女": "妓女",
                "巨乳": "巨乳",
                "高畫質": "高画质",
                "DMM獨家": "DMM独家",
                "合集": "合集",
                "女同性戀": "女同性恋",
                "花癡": "花痴",
                "蕩婦": "荡妇",
                "ノーパン": "不穿内裤",
                "中出": "内射",
                "戀腿癖": "恋腿癖",
                "連褲襪": "连裤袜",
                "M女": "M女",
                "女教師": "女教师",
                "監禁": "监禁",
                "紧缚": "紧缚",
                "4K": "4K",
                "妄想": "妄想",
                "姐姐": "姐姐",
                "娃娃": "娃娃",
                "胖女人": "胖女人",
                "多P": "多人",
                "深喉": "深喉",
                "空中小姐": "空中小姐",
                "拘束": "拘束",
                "拳交": "拳交",
                "M男": "M男",
                "护士": "护士",
                "放尿": "放尿",
                "飲尿": "饮尿",
                "口交": "口交",
                "吞精": "吞精",
                "戲劇": "戏剧",
                "數位馬賽克": "数码马赛克",
                "通姦": "通奸",
                "潮吹": "潮吹",
                "女同接吻": "女同接吻",
                "高清": "高清",
                "字幕": "字幕",
                "女檢察官": "女检察官",
                "乳交": "乳交",
                "戀乳癖": "恋乳癖",
                "妄想族": "妄想族",
                "屁股": "臀部",
                "ハーレム": "后宫",
                "顏面騎乘": "顏面騎乘"
            },
            'deepseek_params': {'model': 'deepseek-chat', 'temperature': 1.3, 'frequency_penalty': -2.0},
            'google_params': {'model': 'gemini-2.5-pro', 'temperature': 0.2, 'frequency_penalty': 0.0}
        },
        'title':{
          'prompt': TITLE_PROMPT,
          'examples':{
                "PRED-782 絶倫すぎるボクをドスケベ肉感ポーズ淫語で慰めてくれるカレン先生… 楪カレン": "精力过于旺盛的我被用淫荡肉感姿势和淫语安慰的Karen老师… 楪花恋",
                "MFYD-030 夢実かなえの超プライベート映像！すっぴん丸出し本性剥き出しザーメンモロ出し8連発ー。生々しすぎ1泊2日の温泉不倫デートドキュメント（ALL 1on1": "梦实鼎的超私密影像！素颜全露，本性毕现，精液大放出8连发——过于真实的1晚2天温泉不伦约会纪录片（全程一对一）",
                "MUKD-545 二股クズ彼氏と修羅場ハーレム。 目の前で彼女同士が鉢合わせ。どっちが本当の彼女か言い争う女同士の喧嘩がウザ過ぎたので、どっちが俺を気持ちよくできるか、勝負させることにした。": "脚踏两条船的渣男与修罗场后宫。女友们在我面前正面相遇。因为她们争吵谁才是真正的女友实在太烦人了，所以我决定让她们比试一下，看谁能让我更舒服。",
                '300MIUM-1205 超美顔で、超スケベ。【滲み出るエロス、誰もが惚れるイイ女】吸いまれそうになる瞳に、ポッテリむしゃぶりつきたくなる唇。「リラックスしたくて」利用したらしいけど、気づけばスケベなアヘ顔を惜しみもなく晒して没頭イキしてますww#女風#女性用風俗#覗き：file.23': "超美颜且超淫荡。【渗透出性感，任谁都会爱上的好女人】仿佛要被吸进去的瞳孔，让人想狠狠咬住的丰满嘴唇。\"本想放松一下\"似乎是来体验的，回过神来却已毫不吝啬地展露淫荡的痴态投入高潮中ww #女装风俗 #女性风俗店 #窥视：file.23"
            },
            'deepseek_params': {'model': 'deepseek-chat', 'temperature': 1.3, 'frequency_penalty': -2.0},
            'google_params': {'model': 'gemini-2.5-pro', 'temperature': 0.2, 'frequency_penalty': 0.0}
        },
        'srt': {
            'prompt': SRT_PROMPT,
            'examples': {}, # SRT 翻译通常不需要示例
            'deepseek_params': {'model': 'deepseek-chat', 'temperature': 1.3, 'frequency_penalty': -2.0},
            'google_params': {'model': 'gemini-2.5-pro', 'temperature': 0.2, 'frequency_penalty': 0.0}
        }
    }

    if content_type not in translation_configs:
        logger.error(f"不支持的内容类型: {content_type}")
        raise ValueError(f"不支持的内容类型: {content_type}")

    config = translation_configs[content_type]
    system_message = config['prompt']
    examples = config['examples']

    # 如果是 SRT 翻译，并且提供了电影元数据，则将其添加到系统消息中
    if content_type == 'srt' and movie_metadata:
        system_message += "\n" + json.dumps(movie_metadata, ensure_ascii=False) + "\n"

    # 遍历模型列表，尝试每个模型
    for model_index, current_model in enumerate(translator_model_list):
        api_client = None
        model_params = None

        if current_model == 'deepseek-chat':
            if not DEEPSEEK_API_KEY:
                logger.error("DeepSeek API 密钥未配置。无法调用 DeepSeek API。")
                continue
            api_client = deepseek_client
            model_params = config['deepseek_params']
        elif current_model == 'gemini-2.5-pro':
            if not GOOGLE_API_KEY:
                logger.error("Google API 密钥未配置。无法调用 Google API。")
                continue
            api_client = google_client
            model_params = config['google_params']
        else:
            logger.error(f"不支持的翻译模型: {current_model}")
            continue

        logger.info(f"尝试使用模型 {current_model} 进行翻译 (第 {model_index + 1}/{len(translator_model_list)} 个模型)")

        messages = _prepare_messages(system_message, examples, japanese_text, content_type)
        status, translated_text = _api_call_with_retry(
            api_client,
            model_params['model'],
            messages,
            model_params['temperature'],
            8192, # max_tokens
            model_params['frequency_penalty']
        )

        if status == 0:
            if content_type == 'srt':
                extracted_srt = _extract_srt(translated_text)
                return extracted_srt
            else:
                return translated_text
        elif status == 1: # 可重试，通常是长度限制
            logger.warning(f"{content_type.upper()} 翻译因长度限制而失败。正在尝试分割并重试。")

            if content_type == 'general':
                # 对于通用文本，简单地按字符长度分割
                total_length = len(japanese_text)
                middle = total_length // 2
                first_half = japanese_text[:middle]
                second_half = japanese_text[middle:]
            elif content_type == 'srt':
                # 对于 SRT，按块分割以保持格式完整性
                original_parsed_blocks = _extract_srt(japanese_text).split('\n\n')
                if not original_parsed_blocks or len(original_parsed_blocks) < 2:
                    logger.error("原始 SRT 文本无法解析为足够多的块以进行分割和重试。")
                    raise FatalError('原始 SRT 文本无法解析为足够多的块以进行分割和重试')
                middle_block_idx = len(original_parsed_blocks) // 2
                first_half = "\n\n".join(original_parsed_blocks[:middle_block_idx])
                second_half = "\n\n".join(original_parsed_blocks[middle_block_idx:])
            elif content_type == 'title':
                if model_index < len(translator_model_list):
                    continue
                else:
                    raise FatalError('标题翻译失败，无法分割重试')
            else:
                raise FatalError('未知类型错误') # 不应该发生，因为上面已经检查过 content_type

            # 递归调用翻译函数处理分割后的两部分
            first_part_translated = translate_text(first_half, translator_model_list, content_type, movie_metadata, recursive_depth=1)
            second_part_translated = translate_text(second_half, translator_model_list, content_type, movie_metadata, recursive_depth=1)

            if first_part_translated is not None and second_part_translated is not None:
                if content_type == 'srt':
                    # 重新提取 SRT 确保格式正确，并合并
                    return _extract_srt(first_part_translated) + '\n\n' + _extract_srt(second_part_translated)
                else:
                    return first_part_translated + second_part_translated
            else:
                logger.error(f"{content_type.upper()} 翻译重试失败，一半或两半都失败了。")
                continue  # 尝试下一个模型
        else: # 不可重试错误
            logger.error(f"{content_type.upper()} 翻译失败，状态不可重试: {status}")
            continue  # 尝试下一个模型

    # 所有模型都失败了
    error_msg = f"所有翻译模型都失败了: {translator_model_list}"
    if content_type == 'srt':
        logger.critical(error_msg)
        raise FatalError(error_msg)
    else:
        logger.error(error_msg)
        raise IgnorableError(error_msg)


def translate_metadata_item(japanese_text: str, cache_dict: dict, cache_file: str, translator_model_list: list[str]) -> str:
    """
    翻译单个元数据项（演员、流派、导演）并进行缓存。

    args:
        japanese_text (str): 日文原文。
        cache_dict (dict): 缓存字典。
        cache_file (str): 缓存文件路径。
        translator_model_list (list[str]): 翻译模型列表。

    return:
        str: 翻译结果。
    """
    if not japanese_text or not japanese_text.strip():
        return "不详"

    # 首先检查缓存
    if japanese_text in cache_dict:
        return cache_dict[japanese_text]

    # 如果不在缓存中，则进行翻译
    try:
        translated = translate_text(japanese_text, translator_model_list=translator_model_list, content_type='general')
        cache_dict[japanese_text] = translated
        _save_cache(cache_dict, cache_file)
        return translated
    except IgnorableError as e:
        # 记录日志并返回原始文本，如果翻译失败
        logger.warning(f"翻译元数据项 '{japanese_text}' 失败: {e}。返回原始值。")
        return japanese_text


if __name__ == "__main__":
    logging.info("--- 示例用法开始 ---")

    # 示例 SRT 文本
    sample_srt = '''32
00:02:56,420 --> 00:03:03,420
あんな、えずセック始めたのに、すごい前は。

33
00:03:03,420 --> 00:03:06,420
私のことを攻めて。

34
00:03:06,420 --> 00:03:10,420
いいの?あなたどうなって見せめるの?

35
00:03:10,420 --> 00:03:12,420
私の好きにせめていいの?

36
00:03:12,420 --> 00:03:14,420
好きにせめて。

37
00:03:56,420 --> 00:03:58,420
advice your stress?

38
00:04:04,420 --> 00:04:08,420
あんなの、、、

39
00:04:08,420 --> 00:04:11,420
ファーポウ

40
00:04:12,420 --> 00:04:13,420
ファンバッター

41
00:04:13,420 --> 00:04:15,420
ふへーん

42
00:04:15,420 --> 00:04:18,419
もう1試合か BuzzSun?

43
00:04:24,419 --> 00:04:25,419
3 tablet?

44
00:04:25,420 --> 00:04:30,420
あそこは私のチクリームで石くちゃんだよ
'''

    # 用于 SRT 翻译示例的虚拟电影元数据
    dummy_metadata = {
        "title": "PRED-782 絶倫すぎるボクをドスケベ肉感ポーズ淫語で慰めてくれるカレン先生… 楪カレン",
        "actor": "楪カレン",
        "genre": "女教师"
    }

    model_to_use = "gemini-2.5-pro" # 你的代理将 OpenAI 格式映射到的 Gemini 模型名称
    messages_payload = [
        {"role": "user", "content": "你好，请用中文介绍一下你自己。"}
    ]
    temperature_setting = 0.7
    max_tokens_setting = 150
    frequency_penalty_setting = 0.0

    print(f"\n尝试调用模型: {model_to_use}...")
    status, response_content = _api_call_with_retry(
        google_client,
        model_to_use,
        messages_payload,
        temperature_setting,
        max_tokens_setting,
        frequency_penalty_setting
    )

    if status == 0:
        print(f"\n成功获取回复:\n{response_content}")
    else:
        print(f"\nAPI 调用失败，状态码: {status}")
    # print("\n--- SRT 翻译 (DeepSeek) ---")
    # try:
    #     translated_srt_deepseek = translate_text(sample_srt, translator_model='deepseek-chat', content_type='srt', movie_metadata=dummy_metadata)
    #     if translated_srt_deepseek:
    #         print(translated_srt_deepseek)
    #     else:
    #         print("DeepSeek SRT 翻译失败。")
    # except Exception as e:
    #     print(f"DeepSeek SRT 翻译过程中发生错误: {e}")
    #     logging.error(f"DeepSeek SRT 翻译过程中发生错误: {e}", exc_info=True)

    print("\n--- SRT 翻译 (Gemini) ---")
    try:
        translated_srt_gemini = translate_text(sample_srt, translator_model_list=['gemini-2.5-pro'], content_type='srt', movie_metadata=dummy_metadata)
        print(translated_srt_gemini)
    except FatalError as e:
        print(f"Gemini SRT 翻译致命错误: {e}")
        logging.error(f"Gemini SRT 翻译致命错误: {e}", exc_info=True)
    except Exception as e:
        print(f"Gemini SRT 翻译过程中发生其他错误: {e}")
        logging.error(f"Gemini SRT 翻译过程中发生其他错误: {e}", exc_info=True)

    # 示例元数据
    sample_title = 'PRED-783 転職女子アナNTR 栄転先の頼れる社長に身も心も奪われ、何度も避妊具なしの中出しを受け入れたワタシ… 和香なつき'
    sample_actor = '和香なつき'
    sample_genre = '巨乳'

    print("\n--- 通用文本翻译 (DeepSeek) ---")
    translated_title_deepseek = translate_text(sample_title, ['deepseek-chat'], 'title')
    translated_actor_deepseek = translate_text(sample_actor, ['deepseek-chat'], 'general')
    translated_genre_deepseek = translate_text(sample_genre, ['deepseek-chat'], 'general')
    print(f"DeepSeek 标题: {translated_title_deepseek}")
    print(f"DeepSeek 演员: {translated_actor_deepseek}")
    print(f"DeepSeek 类型: {translated_genre_deepseek}")

    print("\n--- 通用文本翻译 (Gemini) ---")
    translated_title_gemini = translate_text(sample_title, ['gemini-2.5-pro'], 'title')
    translated_actor_gemini = translate_text(sample_actor, ['gemini-2.5-pro'], 'general')
    translated_genre_gemini = translate_text(sample_genre, ['gemini-2.5-pro'], 'general')
    print(f"Gemini 标题: {translated_title_gemini}")
    print(f"Gemini 演员: {translated_actor_gemini}")
    print(f"Gemini 类型: {translated_genre_gemini}")

    # 测试元数据项的缓存
    print("\n--- 缓存测试 ---")
    # 在测试前确保缓存为空或特定项不在缓存中，以便观察缓存生效
    if '和香なつき' in actors_cache:
        del actors_cache['和香なつき']
        _save_cache(actors_cache, ACTORS_CACHE_FILE) # 保存清空后的缓存
    if '巨乳' in genres_cache:
        del genres_cache['巨乳']
        _save_cache(genres_cache, GENRES_CACHE_FILE) # 保存清空后的缓存

    print(f"正在翻译演员 '和香なつき' (第一次调用应触发API，后续应命中缓存):")
    cached_actor = translate_metadata_item('和香なつき', actors_cache, ACTORS_CACHE_FILE, ['deepseek-chat'])
    print(f"缓存演员: {cached_actor}")
    # 第二次调用应该命中缓存，不会再记录API调用日志
    print(f"再次翻译演员 '和香なつき' (应命中缓存):")
    cached_actor_again = translate_metadata_item('和香なつき', actors_cache, ACTORS_CACHE_FILE, ['deepseek-chat'])
    print(f"缓存演员 (再次): {cached_actor_again}")

    print("\n--- 示例用法结束 ---")
