# == movie_crawler.py ==
import logging
import json
import re
from pathlib import Path
from typing import Dict

import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# --- 从我们自己的模块导入 ---
try:
    from config import VIDEO_LIBRARY_DIRECTORY, JAVBUS_BASE_URL
    from exceptions import IgnorableError
    # 注意：此模块不再需要导入 StatManager
    from text_translator import translate_metadata_item, save_all_caches, translate_simple_text
except ImportError:
    # 支持独立测试时的回退定义
    class IgnorableError(Exception):
        pass


    VIDEO_LIBRARY_DIRECTORY = Path("./AV_Library")
    JAVBUS_BASE_URL = "https://www.javbus.com/"


    def translate_metadata_item(text, item_type):
        return f"{text}_zh"


    def save_all_caches():
        pass

logger = logging.getLogger(__name__)


# --- 内部异常 ---
class _CrawlError(Exception):
    """定义一个仅在模块内部使用的特定异常，用于表示可预见的爬取失败。"""
    pass


# --- 内部辅助函数 (_ 开头) ---

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=3, max=15),
    retry=retry_if_exception_type(requests.exceptions.RequestException)
)
def _get_movie_html(av_code: str) -> str:
    """[内部函数] 使用 tenacity 重试机制，从JavBus获取影片页面的HTML。"""
    url = f"{JAVBUS_BASE_URL}{av_code}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Referer': JAVBUS_BASE_URL
    }
    logger.debug(f"[{av_code}] 正在抓取HTML: {url}")

    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        if "404 Page Not Found" in response.text:
            raise _CrawlError(f"番号在JavBus上未找到 (404)。")
        return response.text
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            raise _CrawlError(f"番号在JavBus上未找到 (404)。")
        logger.warning(f"[{av_code}] 抓取时发生HTTP错误 {e.response.status_code}，将重试...")
        raise
    except requests.exceptions.RequestException as e:
        logger.warning(f"[{av_code}] 抓取时发生网络错误: {e}，将重试...")
        raise


def _parse_movie_html(html_content: str, av_code: str) -> dict:
    """[内部函数] 解析HTML内容，提取日文原文元数据。"""
    if not html_content: raise ValueError("HTML内容为空，无法解析。")
    soup = BeautifulSoup(html_content, 'html.parser')

    metadata = {'av_code': av_code}
    title_tag = soup.find('h3')
    metadata['title'] = title_tag.get_text(strip=True) if title_tag else f"{av_code} (Title not found)"

    info_header = soup.find('div', class_='movie')
    if info_header:
        date_span = info_header.find('span', string=re.compile(r'發行日期:'))
        metadata['release_date'] = date_span.next_sibling.strip() if date_span and date_span.next_sibling else "N/A"
        director_tag = info_header.find('a', href=re.compile(r'/director/'))
        metadata['director'] = director_tag.get_text(strip=True) if director_tag else "N/A"

    actors = [tag.get_text(strip=True) for tag in soup.find_all('a', href=re.compile(r'/star/'))]
    metadata['actors'] = actors if actors else ["N/A"]
    categories = [tag.get_text(strip=True) for tag in soup.find_all('a', href=re.compile(r'/genre/'))]
    metadata['categories'] = categories if categories else ["N/A"]
    cover_tag = soup.find('a', class_='bigImage')
    metadata['cover_url'] = cover_tag['href'] if cover_tag else ""
    return metadata


# --- 核心功能函数 (Core Function Layer) ---
def _get_and_translate_metadata(av_code: str) -> dict:
    """【核心功能函数】抓取、解析并翻译元数据。"""
    logger.info(f"[{av_code}] 正在执行核心元数据获取与翻译任务...")

    html = _get_movie_html(av_code)
    metadata_ja = _parse_movie_html(html, av_code)

    logger.info(f"[{av_code}] 正在翻译元数据...")

    # 【关键修正】为标题调用 translate_simple_text，为其他项调用 translate_metadata_item
    title_zh = translate_simple_text(metadata_ja.get('title', ''), 'title')
    director_zh = translate_metadata_item(metadata_ja.get('director', 'N/A'), 'director')
    actors_zh = [translate_metadata_item(actor, 'actor') for actor in metadata_ja.get('actors', [])]
    categories_zh = [translate_metadata_item(genre, 'genre') for genre in metadata_ja.get('categories', [])]

    # ... (final_metadata 的组合逻辑与之前相同)
    final_metadata = {
        "av_code": av_code,
        "title": metadata_ja.get('title'), "title_zh": title_zh,
        "release_date": metadata_ja.get('release_date'), "cover_url": metadata_ja.get('cover_url'),
        "director": {"name": metadata_ja.get('director'), "name_zh": director_zh},
        "actors": [{"name": ja, "name_zh": zh} for ja, zh in zip(metadata_ja.get('actors', []), actors_zh)],
        "categories": [{"name": ja, "name_zh": zh} for ja, zh in zip(metadata_ja.get('categories', []), categories_zh)],
    }
    return final_metadata


# --- 公开接口 (Worker/Orchestration Layer) ---
def crawl_metadata_worker(av_code: str, force: bool = False) -> Dict:
    """【工人函数】负责编排元数据处理流程，并返回结果给主进程。"""
    # ... (此函数代码与上一版完全相同，因为它只调用核心函数)
    logger.info(f"--- 开始处理番号 {av_code} 的【辅助流程：元数据】 ---")
    movie_dir = VIDEO_LIBRARY_DIRECTORY / av_code
    metadata_file_path = movie_dir / "metadata.json"
    if metadata_file_path.exists() and not force:
        with open(metadata_file_path, 'r', encoding='utf-8') as f: metadata = json.load(f)
        return {'status': 'skipped', 'av_code': av_code, 'metadata': metadata}
    try:
        final_metadata = _get_and_translate_metadata(av_code)
        movie_dir.mkdir(parents=True, exist_ok=True)
        with open(metadata_file_path, 'w', encoding='utf-8') as f:
            json.dump(final_metadata, f, indent=2, ensure_ascii=False)
        return {'status': 'success', 'av_code': av_code, 'metadata': final_metadata}
    except Exception as e:
        raise IgnorableError(f"元数据处理失败: {e}") from e
    finally:
        save_all_caches()