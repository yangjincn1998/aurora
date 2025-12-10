from logging import getLogger

import requests
from bs4 import BeautifulSoup

from domain.movie import Movie, Metadata, BilingualText, Actor
from services.web_request.web_service import WebService
from utils.singleton import singleton

logger = getLogger(__name__)


@singleton
class JavBusWebService(WebService):
    """
    JavBus网站的Web服务实现。

    提供番号查询、HTML获取、元数据解析和番号验证功能。
    """

    def __init__(self):
        """初始化JavBus Web服务"""
        self._base_url = "https://www.javbus.com/"
        self._available = True
        self._headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        self._timeout = 15  # 请求超时时间(秒)
        self._session = requests.Session()  # 使用session保持cookie
        # 设置年龄验证cookie
        self._session.cookies.set("existmag", "all", domain=".javbus.com")

    @property
    def url(self) -> str:
        """返回基础URL"""
        return self._base_url

    @property
    def available(self) -> bool:
        """返回服务是否可用"""
        return self._available

    def request(self, av_code: str, *args, **kwargs) -> str:
        """
        根据av番号向JavBus网站发送请求并获取HTML文本。

        Args:
            av_code (str): av番号，例如 "NACX-141"
            *args: 额外的位置参数
            **kwargs: 额外的关键字参数，可以包括:
                - timeout: 请求超时时间(秒)，默认使用实例的_timeout
                - headers: 自定义请求头，默认使用实例的_headers

        Returns:
            str: 网站返回的HTML文本

        Raises:
            requests.exceptions.RequestException: 网络请求失败
            ValueError: 番号为空或无效
        """
        if not av_code or not av_code.strip():
            raise ValueError("av_code 不能为空")

        av_code = av_code.strip()
        url = self._base_url + av_code

        timeout = kwargs.get("timeout", self._timeout)
        headers = kwargs.get("headers", self._headers)

        logger.info("向 JavBus 请求番号: %s, URL: %s", av_code, url)

        try:
            response = self._session.get(url, headers=headers, timeout=timeout)

            # 检查404错误
            if response.status_code == 404:
                logger.warning("番号 %s 不存在 (404 Not Found)", av_code)
                raise requests.exceptions.HTTPError(
                    f"番号 {av_code} 不存在 (404 Not Found)"
                )

            # 检查是否包含404标识（有些网站可能返回200但内容是404页面）
            if "404" in response.text and "Not Found" in response.text:
                logger.warning("番号 %s 不存在 (页面显示404)", av_code)
                raise requests.exceptions.HTTPError(
                    f"番号 {av_code} 不存在 (页面显示404)"
                )

            response.raise_for_status()

            logger.info(
                "成功获取番号 %s 的HTML内容，长度: %d 字符", av_code, len(response.text)
            )
            return response.text

        except requests.exceptions.Timeout:
            logger.exception("请求番号 %s 超时", av_code)
            raise
        except requests.exceptions.ConnectionError:
            logger.exception("请求番号 %s 连接错误", av_code)
            raise
        except requests.exceptions.HTTPError:
            logger.exception("请求番号 %s HTTP错误", av_code)
            raise
        except requests.exceptions.RequestException:
            logger.exception("请求番号 %s 发生未知网络错误", av_code)
            raise

    def fetch_metadata(self, av_code: str) -> Metadata:
        """
        根据av番号检索并解析影片元数据。

        Args:
            av_code (str): av番号，例如 "NACX-141"

        Returns:
            Metadata: 影片的元数据信息

        Raises:
            ValueError: 番号无效
            requests.exceptions.RequestException: 网络请求失败
            Exception: 解析失败
        """
        if not av_code or not av_code.strip():
            raise ValueError("av_code 不能为空")

        av_code = av_code.strip()
        logger.info("开始获取番号 %s 的元数据", av_code)

        try:
            # 获取HTML内容
            html_content = self.request(av_code)

            # 解析HTML
            metadata = self._parse_html(html_content, av_code)

            logger.info("成功解析番号 %s 的元数据", av_code)
            return metadata

        except Exception as e:
            logger.exception("获取番号 %s 元数据失败", av_code)
            raise

    def validate_code(self, av_code: str) -> bool:
        """
        验证av番号是否有效（即是否能成功从网站获取数据）。

        通过发送请求并检查响应来判断番号是否存在:
        - 如果返回404或页面包含404字样，则番号无效
        - 如果发生网络错误，则番号无效
        - 否则番号有效

        Args:
            av_code (str): av番号，例如 "NACX-141"

        Returns:
            bool: 番号是否有效
        """
        if not av_code or not av_code.strip():
            logger.warning("番号为空，验证失败")
            return False

        av_code = av_code.strip()
        logger.info("验证番号: %s", av_code)

        try:
            # 尝试请求HTML
            html_content = self.request(av_code)

            # 如果成功获取HTML且不包含404标识，则认为番号有效
            if html_content:
                logger.info("番号 %s 验证成功", av_code)
                return True
            else:
                logger.warning("番号 %s 验证失败: HTML内容为空", av_code)
                return False

        except requests.exceptions.HTTPError as e:
            # HTTP错误（包括404）表示番号无效
            logger.warning("番号 %s 验证失败: %s", av_code, e)
            return False
        except requests.exceptions.RequestException as e:
            # 网络错误表示番号无效（无法验证）
            logger.warning("番号 %s 验证失败（网络错误）: %s", av_code, e)
            return False
        except Exception:
            # 其他错误也认为番号无效
            logger.exception("番号 %s 验证失败（未知错误）", av_code)
            return False

    @staticmethod
    def _parse_html(html_content: str, code: str) -> Metadata:
        """
        解析HTML内容并提取元数据。

        Args:
            html_content (str): HTML页面内容
            code (str): 影片番号

        Returns:
            Movie: 包含元数据的Movie对象
        """
        soup = BeautifulSoup(html_content, "html.parser")
        metadata = Metadata()

        # 提取标题 (h3标签)
        title_tag = soup.find("h3")
        if title_tag:
            title_text = title_tag.text.strip()
            # 标题格式通常为 "CODE 标题"，去除番号部分
            title_without_code = title_text.replace(code, "").strip()
            metadata.title = BilingualText(original=title_without_code)
            logger.debug("提取标题: %s", title_without_code)

        # 查找info区域
        container = soup.find("div", class_="container")
        if not container:
            logger.warning("未找到 container div")
            return metadata

        info_div = container.find("div", class_="info")
        if not info_div:
            logger.warning("未找到 info div")
            return metadata

        # 提取信息字段
        for p_tag in info_div.find_all("p"):
            header_tag = p_tag.find("span", class_="header")
            if not header_tag:
                continue

            key = header_tag.text.strip().replace(":", "")

            # 根据不同的字段提取不同的值
            if key == "識別碼":
                # 番号已经有了，跳过
                pass
            elif key == "發行日期":
                date_text = p_tag.get_text().replace(header_tag.text, "").strip()
                metadata.release_date = date_text
                logger.debug("提取发行日期: %s", date_text)
            elif key == "長度":
                # 长度信息暂时不保存到metadata中
                length_text = p_tag.get_text().replace(header_tag.text, "").strip()
                logger.debug("提取时长: %s", length_text)
            elif key == "導演":
                director_link = p_tag.find("a")
                if director_link:
                    director_name = director_link.text.strip()
                    metadata.director = BilingualText(original=director_name)
                    logger.debug("提取导演: %s", director_name)
            elif key == "製作商":
                studio_link = p_tag.find("a")
                if studio_link:
                    studio_name = studio_link.text.strip()
                    metadata.studio = BilingualText(original=studio_name)
                    logger.debug("提取制作商: %s", studio_name)
            elif key == "發行商":
                # 发行商信息
                publisher_link = p_tag.find("a")
                if publisher_link:
                    publisher_name = publisher_link.text.strip()
                    logger.debug("提取发行商: %s", publisher_name)

        # 提取类别 (genres)
        # 类别在包含class="genre"的p标签中，且该p标签前有一个包含"類別:"或class="header"的p标签
        all_p_tags = info_div.find_all("p")
        for i, p_tag in enumerate(all_p_tags):
            # 查找包含"類別"、"类别"或class="header"且内容简短的标签（类别的标题行）
            p_text = p_tag.get_text().strip()
            if p_tag.get("class") == ["header"] and len(p_text) < 10:
                # 下一个p标签可能包含类别信息
                if i + 1 < len(all_p_tags):
                    genre_p = all_p_tags[i + 1]
                    genre_spans = genre_p.find_all("span", class_="genre")
                    if genre_spans and len(genre_spans) > 1:  # 类别通常有多个
                        categories = []
                        for genre_span in genre_spans:
                            genre_link = genre_span.find("a")
                            # 过滤掉按钮等非类别元素
                            if genre_link and not genre_span.find("button"):
                                category_name = genre_link.text.strip()
                                if category_name:
                                    categories.append(
                                        BilingualText(original=category_name)
                                    )
                        if categories:
                            metadata.categories = categories
                            logger.debug(
                                "提取类别: %s", [c.original for c in categories]
                            )
                            break

        # 提取演员
        # 演员在包含class="star-show"的p标签后面的p标签中
        from utils.actor_parser import parse_actor_string

        for i, p_tag in enumerate(all_p_tags):
            # 查找包含"演員"或"star-show"的header标签
            if p_tag.get("class") == ["star-show"] or (
                "演" in p_tag.get_text() and "header" in str(p_tag.get("class"))
            ):
                # 下一个p标签包含演员信息
                if i + 1 < len(all_p_tags):
                    actress_p = all_p_tags[i + 1]
                    actress_spans = actress_p.find_all("span", class_="genre")
                    actresses = []
                    for actress_span in actress_spans:
                        actress_link = actress_span.find("a")
                        if actress_link:
                            actress_name = actress_link.text.strip()
                            if actress_name:
                                # 使用新的Actor解析器
                                actor = parse_actor_string(actress_name)
                                if actor:
                                    actresses.append(actor)
                                    logger.debug(
                                        "提取演员: %s (别名: %s)",
                                        actor.current_name,
                                        [name.original for name in actor.all_names[1:]],
                                    )
                                else:
                                    # 如果解析失败，创建一个简单的Actor对象
                                    simple_actor = Actor(
                                        current_name=actress_name,
                                        all_names=[
                                            BilingualText(original=actress_name)
                                        ],
                                    )
                                    actresses.append(simple_actor)
                                    logger.debug("提取演员(简单): %s", actress_name)
                    if actresses:
                        metadata.actresses = actresses
                break

        return metadata
