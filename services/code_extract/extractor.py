import re
from http.client import HTTPException
from logging import getLogger
from pathlib import Path
from typing import Set, Optional, List

from services.web_request.missav_web_service import MissavWebService
from services.web_request.web_service import WebService

logger = getLogger(__name__)

class CodeExtractor:
    """
    用于从文件名中提取番号的服务类，核心服务extract_av_code
    提取策略分三步走：
      第〇步，根据用户设置的黑名单，将文件中的噪音排出
      第一步，贪婪地选择所有符合模式的字符串作为番号候选
      第二步，根据本地存储的维护所提取过的av番号前缀的文件，在为番号候选排序，将带有识别过的前缀的字符串优先排列
      第三步，向网站发送报文，确定是否成功
    Attributes：
        web_services(List[WebService]): 发送报文服务的WebService
        prefix_path(str): 记录前缀名的文件，目前写死为service/code_extract/prefix.txt.txt
        noise_path(str): 记录噪声的文件, 目前写死为service/code_extract/noise.txt
    """

    def __init__(self, web_servers: List[WebService], prefix_path: str = str(Path(__file__).parent / "prefix.txt"),
                 noise_path: str = str(Path(__file__).parent / "noise.txt")):
        self.web_services = web_servers
        self.prefix_path = prefix_path
        self.noise_path = noise_path
        # 如果位置不存在文件，则创建文件
        Path(self.prefix_path).touch(exist_ok=True)
        Path(self.noise_path).touch(exist_ok=True)

    @staticmethod
    def _parse_text(path: str) -> Set[str]:
        """
        从txt文件中获取字符串列表的方法
        Args:
            path: .txt文件的地址
        Returns：
            List[str]: 字符串序列
        """
        path_obj = Path(path)
        if not path_obj.exists():
            return set()
        content = path_obj.read_text(encoding="utf-8")
        return {line.strip().upper() for line in content.strip().splitlines() if line.strip()}

    @staticmethod
    def _wash_noises(file_name: str, noises: Set[str]) -> str:
        """
        使用正则表达式一次性清除文件名中的所有噪音词（不区分大小写）。

        Args:
            file_name (str): 原始文件名。
            noises (Set[str]): 噪音词集合。

        Returns:
            str: 清洗后的文件名。
        """
        if not noises:
            return file_name

        # 将噪音词列表构建成一个正则表达式，例如 (noise1|noise2|...)
        # re.escape 用于转义噪音词中可能存在的特殊字符
        noise_pattern = "|".join(re.escape(n) for n in noises)

        # 使用 re.sub 进行全局、不区分大小写的替换
        # 将噪音替换为空格，以防意外拼接单词
        return re.sub(noise_pattern, ' ', file_name, flags=re.IGNORECASE)

    @staticmethod
    def _greedy_extract_codes(file_name: str) -> List[str]:
        """
        (贪婪模式) 从文件名中提取所有可能是番号的字符串。

        包含两个匹配策略：
        1. 一个通用的模式，匹配 "字母+可选分隔符+数字" 的组合。
        2. 一个专门的模式，匹配 "字母+0/00+数字" 的组合，并将其转换为连字符格式。

        Args:
            file_name (str): 待提取的文件名。

        Returns:
            List[str]: 标准化、去重后的候选番号列表。
        """
        candidates: Set[str] = set()

        # --- 策略 1: 主模式匹配 (处理常规格式) ---
        # 匹配 "字母+可选分隔符+数字" 的组合
        main_pattern = r'([A-Za-z]{2,8})\s*[-_]?\s*([0-9]{2,7})'
        matches_main = re.findall(main_pattern, file_name, re.IGNORECASE)

        for letters, numbers in matches_main:
            # 标准化并添加到候选集
            standard_code = f"{letters.upper()}-{numbers}"
            candidates.add(standard_code)

        # --- 策略 2: 特殊模式匹配 (处理 0/00 作为分隔符) ---
        # 匹配 "字母" + "0"或"00" + "数字" 的组合
        # 例如：vrkm01477, vrprd00070
        special_pattern = r'([A-Za-z]{2,8})(0*)([0-9]{2,7})'
        matches_special = re.findall(special_pattern, file_name, re.IGNORECASE)

        for letters, separator, numbers in matches_special:
            # 将 0/00 转换的格式也加入候选集
            special_code = f"{letters.upper()}-{numbers}"
            candidates.add(special_code)

        if not candidates:
            return []

        # 按长度降序排序，优先考虑更完整的番号
        return sorted(list(candidates), key=len, reverse=True)

    @staticmethod
    def _filter_by_prefix(candidates: List[str], prefixes: Set[str]) -> List[str]:
        """
        根据已知前缀（词牌名）对候选列表进行优先级排序。

        Args:
            candidates (List[str]): 候选番号列表。
            prefixes (Set[str]): 已知的前缀集合。

        Returns:
            List[str]: 排序后的列表，已知前缀的番号排在最前面。
        """
        if not prefixes:
            return candidates

        known = []
        unknown = []

        for code in candidates:
            prefix = code.split('-')[0]
            if prefix in prefixes:
                known.append(code)
            else:
                unknown.append(code)

        # 包含已知前缀的番号拥有最高优先级
        if known:
            return known
        else:
            return unknown

    def extract_av_code(self, file_name: str) -> Optional[str]:
        """
        供给外部调用的主方法，按顺序执行完整的提取和验证流程。

        Args:
            file_name (str): 待提取的文件名。

        Returns:
            Optional[str]: 成功验证的标准化番号，如果都失败则返回 None。
        """
        # 第〇步：清洗噪音
        noises = self._parse_text(str(self.noise_path))
        cleaned_name = self._wash_noises(file_name, noises)
        logger.info(f"Original name: '{file_name}' -> Cleaned name: '{cleaned_name}'")

        known_prefixes = self._parse_text(str(self.prefix_path))
        # 第一步：贪婪提取
        code_candidates = self._greedy_extract_codes(cleaned_name)
        if not code_candidates:
            logger.warning(f"No potential codes found in '{cleaned_name}'.")
            return None
        logger.info(f"Found candidates: {code_candidates}")
        if len(code_candidates) == 1:
            logger.info(f"Only one candidate '{code_candidates[0]}' found, skipping validation.")
            code = code_candidates[0]
            prefix = code.split('-')[0]
            # 将前缀写入前缀文件
            known_prefixes.add(prefix)
            Path(self.prefix_path).write_text('\n'.join(sorted(known_prefixes)), encoding="utf-8")
            logger.info(f"Successfully extract code`{code}` of file: `{file_name}`")
            return code

        # 第二步：根据前缀排序
        known_prefixes = self._parse_text(str(self.prefix_path))
        prioritized_candidates = self._filter_by_prefix(code_candidates, known_prefixes)
        logger.info(f"Prioritized candidates: {prioritized_candidates}")
        if len(prioritized_candidates) == 1:
            logger.info(f"Only one prioritized candidate '{prioritized_candidates[0]}' found, skipping validation.")
            code = prioritized_candidates[0]
            prefix = code.split('-')[0]
            # 将前缀写入前缀文件
            known_prefixes.add(prefix)
            Path(self.prefix_path).write_text('\n'.join(sorted(known_prefixes)), encoding="utf-8")
            logger.info(f"Successfully extract code`{code}` of file: `{file_name}`")
            return code


        # 第三步：在线验证
        for candidate in prioritized_candidates:
            for service in self.web_services:
                logger.debug(f"Validating '{candidate}' with service: {service.url}")
                try:
                    if service.validate_code(candidate):
                        logger.info(f"Validation successful! Final code is '{candidate}'.")
                        code = candidate
                        prefix = code.split('-')[0]
                        # 将前缀写入前缀文件
                        known_prefixes.add(prefix)
                        Path(self.prefix_path).write_text('\n'.join(sorted(known_prefixes)), encoding="utf-8")
                        logger.info(f"Successfully extract code`{code}` of file: `{file_name}`")
                        return code
                except HTTPException as e:
                    logger.warning(f"Web service {service.url} failed for code '{candidate}': {e}.")
                    continue  # 尝试下一个 service

        logger.error(f"All candidates failed online validation for file: '{file_name}'.")
        return None

if __name__ == "__main__":
    # ==================== 只需添加下面这部分代码 ====================
    import logging

    logging.basicConfig(
        level=logging.INFO,  # 设置日志级别为 INFO
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # 定义日志输出格式
        datefmt='%Y-%m-%d %H:%M:%S'  # 定义日期格式
    )
    # ===============================================================

    test_dir = r"D:\4. Collections\6.Adult Videos\raw"
    video_suffixes = [
        '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mpg', '.mpeg'
    ]
    all_videos = [
        video.name
        for suffix in video_suffixes
        for video in Path(test_dir).rglob(f"*{suffix}")
    ]

    print(f"Found {len(all_videos)} videos")
    extractor = CodeExtractor(web_servers=[MissavWebService()])
    for video in all_videos:
        print(f"video name: {video}, extracted code: {extractor.extract_av_code(video)}")
"""
video name: sivr00315vrv18khia1.mp4, extracted code: expected:SIVR-315
video name: sivr00315vrv18khia2.mp4, extracted code: expected:SIVR-315
video name: sivr00315vrv18khia3.mp4, extracted code: expected:SIVR-315
video name: hhd800.com@DOKS-641.mp4, extracted code: HHD-800 expected: DOKS-641
video name: kfa55.com@300MIUM-1068.mp4, extracted code: KFA-055 expected: MIUM-1068
video name: 4k2.com@vrkm01477_1_4k.mp4, extracted code: expected:VRKM-1477
video name: 4k2.com@vrkm01477_2_4k.mp4, extracted code: expected:VRKM-1477
video name: 4k2.com@vrprd00070_1_4k.mp4, extracted code: expected:VRPRD-070
video name: 4k2.com@vrprd00070_2_4k.mp4, extracted code: expected:VRPRD-070
video name: NADE-979C.avi, extracted code: expected: NADE-979
"""