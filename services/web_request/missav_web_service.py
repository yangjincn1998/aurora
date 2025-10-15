import re
import time
from logging import getLogger

import cloudscraper
from bs4 import BeautifulSoup

from domain.movie import Metadata
from domain.subtitle import BilingualText, BilingualList
from services.web_request.web_service import WebService

logger = getLogger(__name__)


class MissavWebService(WebService):
    """
    MissAV 网站的服务实现（多语言版）。
    通过请求日文页面获取原始数据，再请求中文页面补充翻译，以确保数据质量。
    """

    def __init__(self, base_url: str = "https://missav.live"):
        self._url = base_url
        self._available = True
        # 使用 cloudscraper 来绕过 Cloudflare 保护
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False
            }
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

        # 请求限流：确保请求间隔至少2秒
        current_time = time.time()
        time_since_last_request = current_time - self._last_request_time
        if time_since_last_request < 2.0:
            sleep_time = 2.0 - time_since_last_request
            logger.debug(f"请求限流，等待 {sleep_time:.2f} 秒...")
            time.sleep(sleep_time)

        # 构建 URL: /dm31/{lang}/{av_code}
        request_url = f"{self._url}/dm31/{lang}/{av_code.lower()}"

        logger.info(f"正在请求 URL: {request_url}")
        try:
            response = self.scraper.get(request_url, timeout=30)
            self._last_request_time = time.time()
            response.raise_for_status()
            logger.info(f"请求成功，状态码: {response.status_code}")
            return response.text
        except Exception as e:
            self._last_request_time = time.time()
            logger.warning(f"请求 {request_url} 失败。错误: {e}")
            # 只有在非403/404错误时才标记服务不可用
            if "403" not in str(e) and "404" not in str(e):
                self._available = False
                logger.error(f"服务将被标记为不可用")
            raise ConnectionError(f"HTTP 请求失败: {e}") from e

    def validate_code(self, av_code: str) -> bool:
        """通过请求中文页面并检查特定文本，来判定 AV 番号是否有效。"""
        try:
            html = self.request(av_code, lang='cn')
            is_404_page = "404" in html and "找不到页面" in html
            return not is_404_page
        except ConnectionError:
            # 任何网络错误（包括HTTP 404）都意味着这个番号无法访问，视为无效
            return False

    def get_metadata(self, av_code: str) -> Metadata:
        """
        通过请求日文和中文两个页面，来获取最完整的元数据。
        """
        metadata = Metadata()

        # 用于后续补充翻译的临时映射字典
        actress_map = {}
        actor_map = {}
        director_map = {}

        # 用于存储类型列表
        categories_ja = []
        categories_cn = []

        # --- 步骤 1: 请求日文页面，获取所有高质量的原始信息 ---
        logger.info(f"正在为 {av_code} 获取原始（日文）元数据...")
        try:
            html_ja = self.request(av_code, lang='ja')
            soup_ja = BeautifulSoup(html_ja, "html.parser")

            # 解析标题
            h1_tag = soup_ja.find("h1")
            if h1_tag:
                metadata.title = BilingualText(original=h1_tag.text.strip())

            # 解析日文简介 - 使用 class="mb-1" 的div
            synopsis_div = soup_ja.find("div", class_="mb-1")
            if synopsis_div:
                metadata.synopsis = BilingualText(original=synopsis_div.text.strip())

            # 解析所有信息块
            info_divs_ja = soup_ja.find_all("div", class_="text-secondary")
            for div in info_divs_ja:
                label_span = div.find("span")
                if not label_span: continue
                label = label_span.text.strip()

                if "配信開始日:" in label or "発売日:" in label:  # 发行日期
                    time_tag = div.find("time")
                    if time_tag:
                        metadata.release_date = time_tag.text.strip()

                elif "品番:" in label:  # 品番（番号）
                    code_span = div.find("span", class_="font-medium")
                    if code_span:
                        # 品番信息，通常不需要存储，因为已经有av_code
                        pass

                elif "監督:" in label:  # 导演
                    director_tag = div.find("a")
                    if director_tag:
                        name = director_tag.text.strip()
                        bt = BilingualText(original=name)
                        metadata.director = bt
                        director_map[name] = bt

                elif "女優:" in label:  # 女优
                    for tag in div.find_all("a"):
                        name = tag.text.strip()
                        if name:
                            bt = BilingualText(original=name)
                            metadata.actresses.append(bt)
                            actress_map[name] = bt

                elif "男優:" in label:  # 男优
                    for tag in div.find_all("a"):
                        name = tag.text.strip()
                        if name:
                            bt = BilingualText(original=name)
                            metadata.actors.append(bt)
                            actor_map[name] = bt

                elif "ジャンル:" in label:  # 类型
                    for tag in div.find_all("a"):
                        name = tag.text.strip()
                        if name:
                            categories_ja.append(name)

                elif "メーカー:" in label:  # 制作商
                    maker_tag = div.find("a")
                    if maker_tag:
                        metadata.studio = BilingualText(original=maker_tag.text.strip())

                elif "レーベル:" in label:  # 厂牌/标签
                    # 可以选择存储或忽略
                    pass

        except ConnectionError as e:
            logger.error(f"无法获取 {av_code} 的日文页面。元数据可能不完整。错误: {e}")

        # --- 步骤 2: 请求中文页面，补充人名等的翻译 ---
        # 注意：标题和简介将使用项目的翻译服务翻译，不从中文页面获取
        logger.info(f"正在为 {av_code} 补充翻译（中文）元数据...")
        try:
            html_cn = self.request(av_code, lang='cn')
            soup_cn = BeautifulSoup(html_cn, "html.parser")

            info_divs_cn = soup_cn.find_all("div", class_="text-secondary")
            for div in info_divs_cn:
                label_span = div.find("span")
                if not label_span: continue
                label = label_span.text.strip()

                # 定义一个辅助函数来解析和补充翻译
                def supplement_translation(parser_map, entity_list):
                    for tag in div.find_all("a"):
                        match = re.match(r'(.+?)\s*\((.+?)\)', tag.text.strip())
                        if match:
                            name_zh, name_ja = match.group(1).strip(), match.group(2).strip()
                            if name_ja in parser_map:
                                parser_map[name_ja].translated = name_zh
                        else:
                            name = tag.text.strip()
                            if name in parser_map:
                                parser_map[name].translated = name

                # 只补充人名、类型、制作商等的翻译
                if "女优:" in label:
                    supplement_translation(actress_map, metadata.actresses)
                elif "男优:" in label:
                    supplement_translation(actor_map, metadata.actors)
                elif "导演:" in label:
                    if metadata.director:
                        supplement_translation(director_map, [metadata.director])
                elif "类型:" in label:
                    # 获取中文类型列表
                    categories_cn = [a.text.strip() for a in div.find_all("a")]

                elif "发行商:" in label:
                    # 获取发行商中文名称
                    if metadata.studio:
                        # 中文页面通常只显示简称，需要拼接完整名称
                        maker_link = div.find("a")
                        if maker_link:
                            cn_name = maker_link.text.strip()
                            # 根据简称拼接完整名称
                            if cn_name == "S1":
                                metadata.studio.translated = "S1 NO.1 STYLE"
                            else:
                                metadata.studio.translated = cn_name

        except ConnectionError as e:
            logger.warning(f"无法获取 {av_code} 的中文页面。翻译可能缺失。错误: {e}")

        # 组装类型数据为 BilingualList
        if categories_ja:
            metadata.categories = BilingualList(
                original=categories_ja,
                translated=categories_cn if categories_cn else None
            )

        return metadata

if __name__ == '__main__':
    import json
    server = MissavWebService()

    # 先获取HTML响应并保存
    print("正在获取日文页面...")
    html_ja = server.request("ssis-001", lang='ja')
    with open('test_response_ja.html', 'w', encoding='utf-8') as f:
        f.write(html_ja)
    print(f"日文页面已保存到 test_response_ja.html (长度: {len(html_ja)})")

    print("\n正在获取中文页面...")
    html_cn = server.request("ssis-001", lang='cn')
    with open('test_response_cn.html', 'w', encoding='utf-8') as f:
        f.write(html_cn)
    print(f"中文页面已保存到 test_response_cn.html (长度: {len(html_cn)})")

    # 然后获取元数据
    print("\n正在解析元数据...")
    metadata = server.get_metadata("ssis-001")
    result = metadata.to_serializable_dict()

    with open('test_metadata_output.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n元数据已成功获取并保存到 test_metadata_output.json")
    print(f"获取的数据项: {list(result.keys())}")