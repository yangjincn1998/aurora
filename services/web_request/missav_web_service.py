import re
import time

import cloudscraper
from bs4 import BeautifulSoup

from domain.movie import Metadata
from domain.subtitle import BilingualText, BilingualList
from services.web_request.web_service import WebService
from utils.logger import get_logger
from utils.singleton import singleton

logger = get_logger(__name__)


@singleton
class MissAvWebService(WebService):
    """
    MissAV 网站的服务实现（多语言版）。
    通过请求日文页面获取原始数据，再请求中文页面补充翻译，以确保数据质量。
    """

    def __init__(self, base_url: str = "https://missav.live"):
        self._url = base_url
        self._available = True
        # 使用 cloudscraper 来绕过 Cloudflare 保护
        self.scraper = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "mobile": False}
        )
        self._last_request_time = 0  # 用于请求限流

    @property
    def url(self) -> str:
        return self._url

    @property
    def available(self) -> bool:
        return self._available

    def request(self, av_code: str, lang: str) -> str:
        """根据 AV 番号和语言，向指定网站发送请求。

        URL 格式: https://missav.live/dm31/{lang}/{av_code}
        例如: https://missav.live/dm31/ja/ssis-001
        """
        if not self.available:
            raise ConnectionError(f"服务 {self.url} 因先前的错误而不可用。")
        request_url = f"{self._url}/dm31/{lang}/{av_code.lower()}"
        for attempt in range(5):
            try:
                current_time = time.time()
                time_since_last_request = current_time - self._last_request_time
                if time_since_last_request < 2.0:
                    sleep_time = 2.0 - time_since_last_request
                    logger.info(f"请求限流，请等待{sleep_time:.2f}s...")
                    time.sleep(sleep_time)
                logger.info(f"正在向{self.url}请求，第{attempt + 1}/5次尝试...")
                response = self.scraper.get(self._url, timeout=8)
                self._last_request_time = time.time()
                logger.info(f"请求成功，状态码：{response.status_code}")
                return response.text
            except Exception as e:
                self._last_request_time = time.time()
                logger.warning(f"请求{request_url}失败, 错误：{e}.")
                if attempt < 5:
                    sleep_duration = 2 * (attempt + 1)
                    logger.info(f"将在{sleep_duration:.2f}s后重试...")
                    time.sleep(sleep_duration)
                else:
                    if (
                            response
                            and hasattr(response, "status_code")
                            and response.status_code not in [403, 404]
                    ):
                        logger.error(f"所有请求均失败，服务{self.url}可能出现问题。")
                        raise ConnectionError(f"HTTP请求失败：{e}.")
        raise ConnectionError("未知错误导致失败.")

    def _parse_ja_page(self, soup: BeautifulSoup, metadata: Metadata):
        """解析日文页面并填充原始数据"""
        # 解析标题
        h1_tag = soup.find("h1")
        if h1_tag:
            metadata.title = BilingualText(original=h1_tag.text.strip())

        # 解析日文简介 - 简介是标题h1标签的下一个div兄弟节点
        synopsis_div = h1_tag.find_next_sibling("div") if h1_tag else None
        if synopsis_div:
            metadata.synopsis = BilingualText(original=synopsis_div.text.strip())

        # 解析所有信息块
        info_divs = soup.find_all("div", class_="text-secondary")
        for div in info_divs:
            label_span = div.find("span")
            if not label_span:
                continue
            label = label_span.text.strip()

            if "配信開始日:" in label or "発売日:" in label:
                time_tag = div.find("time")
                if time_tag:
                    metadata.release_date = time_tag.text.strip()

            elif "監督:" in label:
                director_tag = div.find("a")
                if director_tag:
                    metadata.director = BilingualText(
                        original=director_tag.text.strip()
                    )

            elif "女優:" in label:
                metadata.actresses.original = [
                    a.text.strip() for a in div.find_all("a") if a.text.strip()
                ]

            elif "男優:" in label:
                metadata.actors.original = [
                    a.text.strip() for a in div.find_all("a") if a.text.strip()
                ]

            elif "ジャンル:" in label:
                metadata.categories = BilingualList(
                    original=[
                        a.text.strip() for a in div.find_all("a") if a.text.strip()
                    ]
                )

            elif "メーカー:" in label:
                maker_tag = div.find("a")
                if maker_tag:
                    metadata.studio = BilingualText(original=maker_tag.text.strip())

    def _parse_cn_page(self, soup: BeautifulSoup, metadata: Metadata):
        """解析中文页面以补充翻译"""
        # 创建一个从日文名到中文名的映射
        ja_to_cn_map = {}

        info_divs_cn = soup.find_all("div", class_="text-secondary")
        for div in info_divs_cn:
            label_span = div.find("span")
            if not label_span:
                continue
            label = label_span.text.strip()

            # 通用解析逻辑
            if "女优:" in label or "导演:" in label or "男优:" in label:
                for tag in div.find_all("a"):
                    text = tag.text.strip()
                    # 匹配 "中文名 (日文名)" 格式
                    match = re.match(r"(.+?)\s*\((.+?)\)", text)
                    if match:
                        name_zh, name_ja = (
                            match.group(1).strip(),
                            match.group(2).strip(),
                        )
                        ja_to_cn_map[name_ja] = name_zh
                    # 对于没有括号的（如男优），直接使用
                    elif "男优:" in label and text:
                        ja_to_cn_map[text] = text

        # 填充女优翻译
        if metadata.actresses and metadata.actresses.original:
            metadata.actresses.translated = [
                ja_to_cn_map.get(name, name) for name in metadata.actresses.original
            ]

        # 填充男优翻译
        if metadata.actors and metadata.actors.original:
            metadata.actors.translated = [
                ja_to_cn_map.get(name, name) for name in metadata.actors.original
            ]

        # 填充导演翻译
        if metadata.director and metadata.director.original in ja_to_cn_map:
            metadata.director.translated = ja_to_cn_map[metadata.director.original]

        # 填充类型和发行商（根据您的要求，注释掉不提取）
        for div in info_divs_cn:
            label_span = div.find("span")
            if not label_span:
                continue
            label = label_span.text.strip()

            if "类型:" in label and metadata.categories:
                metadata.categories.translated = [
                    a.text.strip() for a in div.find_all("a")
                ]

            # elif "发行商:" in label and metadata.studio:
            #     # 中文页面通常只显示简称，这里我们不提取，以日文为准
            #     pass

    def get_metadata(self, av_code: str) -> Metadata | None:
        """
        通过请求日文和中文两个页面，来获取最完整的元数据。
        """
        metadata = Metadata()

        # --- 步骤 1: 请求日文页面，获取所有高质量的原始信息 ---
        logger.info(f"正在为 {av_code} 获取原始（日文）元数据...")
        try:
            html_ja = self.request(av_code, lang="ja")
            soup_ja = BeautifulSoup(html_ja, "html.parser")
            self._parse_ja_page(soup_ja, metadata)
        except ConnectionError as e:
            logger.error(f"无法获取 {av_code} 的日文页面。元数据可能不完整。错误: {e}")

        # --- 步骤 2: 请求中文页面，补充人名等的翻译 ---
        # 仅在获取到日文信息后才尝试补充翻译
        if metadata.title:
            logger.info(f"正在为 {av_code} 补充翻译（中文）元数据...")
            try:
                html_cn = self.request(av_code, lang="cn")
                soup_cn = BeautifulSoup(html_cn, "html.parser")
                self._parse_cn_page(soup_cn, metadata)
            except ConnectionError as e:
                logger.warning(
                    f"无法获取 {av_code} 的中文页面。部分翻译可能缺失。错误: {e}"
                )

        # 根据您的要求，清除不想要的翻译
        if metadata.title:
            metadata.title.translated = None
        else:
            return None
        if metadata.studio:
            metadata.studio.translated = None
        if metadata.synopsis:
            metadata.synopsis.translated = None
        if metadata.director:
            metadata.director.translated = None
        return metadata

    def validate_code(self, av_code: str) -> bool:
        """通过请求中文页面并检查特定文本，来判定 AV 番号是否有效。"""
        try:
            html = self.request(av_code, lang="cn")
            is_404_page = "404" in html and "找不到页面" in html
            return not is_404_page
        except ConnectionError:
            # 任何网络错误（包括HTTP 404）都意味着这个番号无法访问，视为无效
            return False


if __name__ == "__main__":
    import dotenv

    dotenv.load_dotenv()
    server = MissAvWebService()

    metadata = server.get_metadata("SSIS-001")
    if metadata:
        print(metadata.to_serializable_dict())
    else:
        print("None")
