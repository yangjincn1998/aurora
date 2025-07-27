
import requests
from bs4 import BeautifulSoup
import re
import os
import logging
import json
import time
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# Import the translation function from text_translator
from text_translator import translate_metadata_item, actors_cache, genres_cache, directors_cache, save_cache, \
    ACTORS_CACHE_FILE, GENRES_CACHE_FILE, DIRECTORS_CACHE_FILE

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
def get_movie_html(av_code: str) -> str | Exception:
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

def is_wrong_av_code(html_content: str) -> bool:
    """
    根据HTML的<title>标签判断是否为参数错误的报文。
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    title_tag = soup.find('title')
    if title_tag and "404 Page Not Found!" in title_tag.get_text():
        return True
    return False

def parse_movie_html(html_content: str) -> dict | Exception:
    """
    Parses the HTML content of a JavBus movie page to extract specific metadata
    in the source language (without translation).
    Required metadata: title, release date, director, actors, categories.
    """
    if not html_content:
        raise ValueError("HTML content is empty")

    if is_wrong_av_code(html_content):
        raise WrongAVCodeError("Wrong AV code or movie not found.")

    soup = BeautifulSoup(html_content, 'html.parser')
    metadata = {}

    # Title
    title_tag = soup.find('h3')
    if title_tag:
        # Remove AV code from title if present
        title_text = title_tag.get_text(strip=True)
        # The regex in the example might be too specific or might not always match the AV code.
        # For this example, we'll keep the provided regex for consistency.
        match = re.match(r'^(.*?)\s*([A-Za-z]{2,}-\d{3,})$', title_text)
        if match:
            metadata['title'] = match.group(1).strip()
        else:
            metadata['title'] = title_text
    else:
        metadata['title'] = "N/A"

    # Release Date
    release_date_tag = soup.find('span', string=re.compile(r'發行日期:'))
    if release_date_tag and release_date_tag.next_sibling:
        metadata['release_date'] = release_date_tag.next_sibling.strip()
    else:
        metadata['release_date'] = "N/A"

    # Director
    director_tag = soup.find('a', href=re.compile(r'/director/'))
    if director_tag:
        metadata['director'] = director_tag.get_text(strip=True)
    else:
        metadata['director'] = "N/A"

    # Actors
    actors = []
    actor_tags = soup.find_all('a', href=re.compile(r'/star/'))
    for tag in actor_tags:
        actor_name = tag.get_text(strip=True)
        if actor_name and actor_name not in actors:
            actors.append(actor_name)
    metadata['actors'] = actors if actors else ["N/A"]

    # Categories/Genres
    categories = []
    genre_tags = soup.find_all('a', href=re.compile(r'/genre/'))
    for tag in genre_tags:
        category_name = tag.get_text(strip=True)
        if category_name and category_name not in categories:
            categories.append(category_name)
    metadata['categories'] = categories if categories else ["N/A"]

    return metadata

def extract_normalized_av_code(filename: str) -> str | None:
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

def metadata_crawler(av_code: str) -> dict | Exception:
    """
    Crawls metadata for a given AV code.
    Args:
        av_code (str): AV番号
    return:
        dict: 元数据
    """
    try:
        html_content = get_movie_html(av_code)
        if not html_content:
            raise ValueError(f"Failed to fetch HTML for AV code: {av_code}")
        metadata = parse_movie_html(html_content)
        return metadata
    except WrongAVCodeError as e:
        logging.error(f"Failed to fetch metadata for AV code: {av_code}: {e}")
        raise WrongAVCodeError(f'Wrong AV code: {av_code}.')
    except Exception as e:
        raise e

def metadata_crawler_translator(av_code: str) -> dict | Exception:
    """
    Crawls metadata for a given AV code and translates it.
    Args:
        av_code (str): AV番号
    return:
        dict: 元数据
    """
    try:
        metadata = metadata_crawler(av_code)
    except WrongAVCodeError as e:
        raise e
    except Exception as e:
        raise e
    # Translate metadata items
    title = metadata['title']
    title_zh = translate_metadata_item()


if __name__ == "__main__":
    try:
        print(metadata_crawler("SSNI-001"))
        print(metadata_crawler("SSNI-002"))
        print(metadata_crawler("SSNI-003"))
    except Exception as e:
        print(e)
    