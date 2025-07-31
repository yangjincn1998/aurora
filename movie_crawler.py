from pathlib import Path
from typing import Union, Optional, Dict, Any, List

import requests
from bs4 import BeautifulSoup
import re
import os
import logging
import json
import time
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from exceptions import IgnorableError, FatalError
# Import the translation function from text_translator
from text_translator import translate_simple_text, translate_metadata_item, save_all_caches
from config import METADATA_PATH, METADATA_CACHE_DIR

# Load environment variables
load_dotenv()

# Configure logging for movie_crawler.py
logging.basicConfig(
    filename='process.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s',
    encoding='utf-8'
)

JAVBUS_BASE_URL = "https://www.javbus.com/"  # Use CN site for easier parsing if available

# --- Retry Decorator for HTTP Requests ---
# Retry strategy for network errors when fetching HTML
HTTP_RETRY_STRATEGY = retry(
    stop=stop_after_attempt(5),  # Try up to 5 times
    wait=wait_exponential(multiplier=1, min=2, max=8),  # Wait 2s, 4s, 8s
    retry=retry_if_exception_type(requests.exceptions.RequestException)  # Retry on any requests-related exception
)

class WrongAVCodeError(Exception):
    pass



@HTTP_RETRY_STRATEGY
def _get_movie_html(av_code: str) -> str | Exception:
    """
    Fetches the HTML content of a movie page from JavBus.
    Includes retry logic for network errors.
    """
    url = f"{JAVBUS_BASE_URL}{av_code}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': JAVBUS_BASE_URL  # Add Referer header
    }

    print(f"Attempting to fetch HTML for AV code: {av_code} from {url}...")
    logging.info(f"Attempting to fetch HTML for AV code: {av_code} from {url}...")

    try:
        response = requests.get(url, headers=headers, timeout=30)  # Add timeout
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)
        logging.info(f"Successfully fetched HTML for AV code: {av_code}")
        with open('程序运行时收到的html.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        return response.text
    except requests.exceptions.Timeout:
        logging.error(f"Request to {url} 超时。", exc_info=True)
        raise  # 这里的 raise 会重新抛出捕获到的 Timeout 异常
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP Error {e.response.status_code} for {url}: {e.response.text}", exc_info=True)
        if e.response.status_code == 404:
            logging.warning(f"Movie with AV code {av_code} 404.")
            raise ValueError("Movie not found")  # Do not retry on 404, it's a valid "not found" state
        raise  # Re-raise for other HTTP errors to trigger tenacity retry
    except requests.exceptions.RequestException as e:
        logging.error(f"Network error fetching {url}: {e}", exc_info=True)
        raise  # Re-raise to trigger tenacity retry
    except Exception as e:
        logging.error(f"An unexpected error occurred while fetching {url}: {e}", exc_info=True)
        raise  # Do not retry on unexpected errors, just return None

def _is_wrong_av_code(html_content: str) -> bool:
    """
    根据HTML的<title>标签判断是否为参数错误的报文。
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    title_tag = soup.find('title')
    if title_tag and "404 Page Not Found!" in title_tag.get_text():
        return True
    return False


def _parse_movie_html(html_content: str, av_code: str) -> dict:
    """
    解析 JavBus 电影页面的 HTML 内容以提取元数据。
    【已修正】演员提取逻辑，以解决重复和截断的问题。
    """
    if not html_content:
        raise ValueError("HTML content is empty")

    if _is_wrong_av_code(html_content):
        raise WrongAVCodeError("Wrong AV code or movie not found.")

    soup = BeautifulSoup(html_content, 'html.parser')
    metadata = {}

    # 获取包含所有核心信息的右侧栏
    info_box = soup.find('div', class_='info')
    if not info_box:
        # 如果连信息框都找不到，直接返回空元数据，避免后续出错
        logging.error(f"[{av_code}] 在页面上找不到 class='info' 的核心信息框。")
        return {
            'title': 'N/A', 'release_date': 'N/A', 'director': 'N/A',
            'actors': ['N/A'], 'categories': ['N/A']
        }

    # --- Title ---
    # 标题在信息框外部，单独处理
    title_tag = soup.find('h3')
    metadata['title'] = title_tag.get_text(strip=True) if title_tag else "N/A"

    # --- Release Date ---
    date_tag = info_box.find('span', string=re.compile(r'發行日期:'))
    metadata['release_date'] = date_tag.next_sibling.strip() if date_tag and date_tag.next_sibling else "N/A"

    # --- Director ---
    director_tag = info_box.find('a', href=re.compile(r'/director/'))
    metadata['director'] = director_tag.get_text(strip=True) if director_tag else "N/A"

    # --- Actors (【关键修正】) ---
    actors = []
    # 1. 首先定位到 "演員" 那个标题所在的 <p> 标签
    star_header_p = info_box.find('p', class_='star-show')
    if star_header_p:
        # 2. 找到紧随其后的兄弟 <p> 标签，这里面才是真正的演员列表
        actor_list_p = star_header_p.find_next_sibling('p')
        if actor_list_p:
            # 3. 只在这个精确的区域内查找所有演员链接
            actor_tags = actor_list_p.find_all('a', href=re.compile(r'/star/'))
            for tag in actor_tags:
                actor_name = tag.get_text(strip=True)
                if actor_name and actor_name not in actors:
                    actors.append(actor_name)

    metadata['actors'] = actors if actors else ["N/A"]

    # --- Categories/Genres ---
    categories = []
    # 类别信息通常分布在多个 <span class="genre"> 中
    genre_spans = info_box.find_all('span', class_='genre')
    for span in genre_spans:
        # 找到span中的链接a
        genre_link = span.find('a', href=re.compile(r'/genre/'))
        if genre_link:
            category_name = genre_link.get_text(strip=True)
            if category_name and category_name not in categories:
                categories.append(category_name)

    metadata['categories'] = categories if categories else ["N/A"]

    return metadata

def _extract_normalized_av_code(filename: str) -> str | None:
    """
    Extracts a normalized AV code (e.g., 'SSNI-001') from a filename.
    Handles common variations like 'SSNI001', 'SSNI_001', 'SSNI-001'.
    """
    # Regex to find patterns like XXX-DDD, XXX_DDD, XXXDDD, where X is letter, D is digit
    # Prioritize patterns with hyphens or underscores
    patterns = [
        r'([A-Za-z]{2,}-\d{3,})',  # e.g., SSNI-001
        r'([A-Za-z]{2,}_\d{3,})',  # e.g., SSNI_001
        r'([A-Za-z]{2,}\d{3,})'  # e.g., SSNI001
    ]

    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            # Normalize to XXX-DDD format
            code = match.group(1).upper()
            code = code.replace('_', '-')
            # If it's XXXDDD format, try to insert hyphen after letters
            if re.match(r'^[A-Z]{2,}\d{3,}$', code):
                alpha_part = re.match(r'^([A-Z]+)', code).group(1)
                num_part = code[len(alpha_part):]
                code = f"{alpha_part}-{num_part}"
            return code
    return None

def _metadata_crawler(av_code: str) -> dict | Exception:
    """
    Crawls metadata for a given AV code.
    Args:
        av_code (str): AV番号
    return:
        dict: 元数据
    """
    try:
        html_content = _get_movie_html(av_code)
        if not html_content:
            raise ValueError(f"Failed to fetch HTML for AV code: {av_code}")
        metadata = _parse_movie_html(html_content)
        return metadata
    except WrongAVCodeError as e:
        logging.error(f"Failed to fetch metadata for AV code: {av_code}: {e}")
        raise WrongAVCodeError(f'Wrong AV code: {av_code}.')
    except Exception as e:
        raise e


def _ensure_japanese_metadata(movie_data: Dict[str, Any], av_code: str) -> bool:
    """【逻辑步骤1】确保影片的日文元数据是完整的。如果不完整，则从网络抓取。"""
    required_keys = ['title', 'director', 'actors', 'categories', 'release_date']
    is_missing_data = any(not movie_data.get(key) for key in required_keys)

    if is_missing_data:
        logging.info(f"[{av_code}] 日文元数据不完整，开始从网络抓取...")
        try:
            crawled_data = _metadata_crawler(av_code)
            movie_data.update(crawled_data)
            logging.info(f"[{av_code}] 日文元数据抓取并更新成功。")
            return True  # 返回True表示数据已更新
        except Exception as e:
            logging.error(f"[{av_code}] 抓取元数据失败: {e}", exc_info=True)
            raise  # 将爬取错误向上抛出
    return False  # 无需抓取


def _translate_list_items(ja_list: List[str], item_type: str) -> List[str]:
    """【辅助翻译逻辑】翻译一个列表（演员或类别），严格使用缓存优先策略。"""
    zh_list = []
    for item_ja in ja_list:
        # 调用 text_translator，它内部已经封装了“缓存优先，API其次”的逻辑
        item_zh = translate_metadata_item(item_ja, item_type)
        zh_list.append(item_zh)
    return zh_list


def _process_translations(movie_data: Dict[str, Any]) -> bool:
    """【逻辑步骤2】翻译所有元数据，并严格遵循您的缓存/覆盖规则。"""
    was_changed = False

    # --- 翻译标题 ---
    if not movie_data.get('title_zh'):
        title_ja = movie_data.get('title')
        if title_ja:
            movie_data['title_zh'] = translate_simple_text(title_ja, 'title')
            was_changed = True

    # --- 翻译导演 (规则: 1.缓存 -> 2.已有数据 -> 3.API) ---
    if not movie_data.get('director_zh'):  # 规则2: 如果metadata中已有，则不更改
        director_ja = movie_data.get('director')
        if director_ja:
            # 规则1和3由 translate_metadata_item 自动处理
            movie_data['director_zh'] = translate_metadata_item(director_ja, 'director')
            was_changed = True

    # --- 翻译演员 (规则: 1.缓存 -> 2.已有数据 -> 3.API) ---
    actors_ja = movie_data.get('actors', [])
    new_actors_zh = _translate_list_items(actors_ja, 'actor')
    # 规则2: 仅当新生成的列表与旧列表不同时才更新
    if new_actors_zh != movie_data.get('actors_zh', []):
        movie_data['actors_zh'] = new_actors_zh
        was_changed = True

    # --- 翻译类别 (逻辑同演员) ---
    categories_ja = movie_data.get('categories', [])
    new_categories_zh = _translate_list_items(categories_ja, 'genre')
    if new_categories_zh != movie_data.get('categories_zh', []):
        movie_data['categories_zh'] = new_categories_zh
        was_changed = True

    return was_changed


# --- 重构后的核心功能函数 ---

def process_movie_metadata(av_code: str, force_refetch: bool = False):
    """
    【重构后的核心函数】
    为一个AV番号，执行完整的“加载->抓取->翻译->保存”流程。
    """
    logging.info(f"--- 开始处理番号 {av_code} 的元数据流程 ---")

    metadata_file_path = METADATA_PATH

    try:
        # 步骤 0: 加载现有元数据
        movies_data = json.loads(metadata_file_path.read_text(encoding='utf-8')) if metadata_file_path.exists() else {}
        movie_data = movies_data.get(av_code, {})
        original_movie_data_str = json.dumps(movie_data)  # 保存原始状态用于比对

        # 步骤 1: 确保日文元数据完整
        _ensure_japanese_metadata(movie_data, av_code)

        # 步骤 2: 翻译所有元数据
        _process_translations(movie_data)

        # 步骤 3: 如果数据有任何变动，则一次性保存
        final_movie_data_str = json.dumps(movie_data)
        if original_movie_data_str != final_movie_data_str or not metadata_file_path.exists():
            logging.info(f"[{av_code}] 元数据有更新，正在保存到 {metadata_file_path}")
            movies_data[av_code] = movie_data
            metadata_file_path.write_text(json.dumps(movies_data, indent=4, ensure_ascii=False), encoding='utf-8')
        else:
            logging.info(f"[{av_code}] 元数据已是最新，无需保存。")

        # 步骤 4 (重要): 保存可能已更新的缓存文件
        save_all_caches()

    except Exception as e:
        # 将所有错误统一向上层抛出
        logging.error(f"为 {av_code} 处理元数据时发生错误。", exc_info=True)
        raise IgnorableError(f"元数据处理失败: {e}") from e
