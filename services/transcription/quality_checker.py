import json
from typing import Tuple, Optional

from langfuse import observe, get_client
from models.results import ChatResult
from pipeline.context import PipelineContext
from services.translation.provider import Provider
from utils.logger import get_logger

logger = get_logger(__name__)


class QualityChecker:
    """字幕质量检测器。

    提供基于大模型的质量检测功能。
    """

    def __init__(self, check_provider: Provider, interval: int):
        """初始化质量检测器。

        Args:
            check_provider: 大模型服务提供者
            interval: 基于规则的质量检查中允许的最大间隔，单位为秒
        """
        self.check_provider = check_provider
        self.interval = interval

    @classmethod
    def from_config_yaml(cls, file_path: str):
        """从 YAML 配置文件创建 QualityChecker 实例。

        Args:
            file_path (str): YAML 配置文件路径

        Returns:
            QualityChecker: 质量检测器实例
        """
        with open(file_path, "r", encoding="utf-8") as f:
            config: dict = json.load(f)
            return cls.from_config(config["quality_checker"])

    @classmethod
    def from_config(cls, config: dict):
        """从配置字典创建 QualityChecker 实例。

        Args:
            config (dict): 质量检测器配置字典

        Returns:
            QualityChecker: 质量检测器实例
        """
        check_provider = Provider.from_config(config["check_provider"])
        interval = config.get("interval", 10)
        return cls(check_provider=check_provider, interval=interval)

    @observe
    def _llm_quality_check(self, text: str, context: PipelineContext) -> bool:
        """
        使用低成本的LLM对字幕质量进行检查。
        Args:
            text (str): 待检查的字幕文本。
            context(PipelineContext): 流水线执行上下文。
        Returns:
            bool: 如果字幕质量合格返回True，否则返回False。
        """
        system_prompt = """You are an ultra-fast subtitle quality check API. Your task is to determine if a subtitle file is structurally broken based on a small sample. Your response must be immediate and only in the specified JSON format.

**Analysis Criteria (Based ONLY on the sample):**
1.  **Structural Damage:** Is the file completely missing timestamps (`-->`) or is the sequence number logic broken?
2.  **Unusable Garbage:** Is the text composed of random characters (e.g., "j@#f!d$"), encoding errors (e.g., ""), or ONLY consists of meaningless, non-dialogue placeholders like "Music" or "Opening" in the entire sample?

**IMPORTANT: Do NOT fail a file for these reasons (These are ACCEPTABLE):**
- **Natural Conversation:** The presence of common conversational fillers/interjections in Japanese (e.g., 「えっと」「うん」「あの」「はい」「うーん」) is NORMAL and indicates a good transcription. DO NOT count these as errors.
- **Time Gaps:** Large gaps in timestamps between subtitle entries are NORMAL and simply mean there is no dialogue in that part of the video.
- **Advertisements:** The presence of ads at the beginning or end is acceptable.

**Output Format (Your entire response MUST be ONLY this valid JSON object):**
- If the sample appears usable for further processing: `{"qualified": true}`
- If the sample is structurally broken or pure garbage: `{"qualified": false, "reason": "A very brief, 10-word max explanation."}`
"""
        langfuse = get_client()
        langfuse.update_current_trace(session_id=context.langfuse_session_id,
                                      tags=["quality_check", "subtitle", context.movie_code])
        user_query = {
            "info": "这是一个成人影片的视频字幕",
            "text": text
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": str(user_query)}
        ]
        logger.info("Checking subtitle quality with low-cost LLM...")
        result: ChatResult = self.check_provider.chat(messages, temperature=0.0,
                                                      response_format={"type": "json_object"})
        if result.success:
            logger.info(f"Subtitle quality check completed. Spend {result.time_taken / 1000.0} seconds.")
            try:
                result_json_object = json.loads(result.content)
                logger.info(f"Subtitle quality check completed. Response is {result_json_object}")
                if result_json_object.get("qualified", True):  # 乐观估计，默认合格
                    return True
                else:
                    logger.warning(f"Subtitle quality based on llm check failed: {result_json_object.get('reason', 'No reason provided')}")
                    return False
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse quality check result as JSON: {e}")
                return True
        else:
            logger.error("Failed to check subtitle quality")
            return True

    def _rule_quality_check(self, text: str) -> bool:
        """
            使用规则对字幕质量进行检查。若前一条字幕的结束时间和后一条字幕的开始时间相差过大，则认为质量不合格。
            Args:
                text (str): 待检查的字幕文本。
            Returns:
                bool: 如果字幕质量合格返回True，否则返回False。
        """
        try:
            timestamps = self._parse_srt_timestamps(text)

            if len(timestamps) < 2:
                logger.warning("字幕条目数量不足")
                return True  # 单条字幕也视为合格

            # 计算相邻字幕之间的最大间隔
            max_gap = 0
            for i in range(1, len(timestamps)):
                gap = timestamps[i][0] - timestamps[i-1][1]  # 当前开始时间 - 前一个结束时间
                max_gap = max(max_gap, gap)

            logger.info(f"最大时间间隔: {max_gap} 秒")

            if max_gap > self.interval:
                logger.warning(f"最大时间间隔 {max_gap} 秒超过阈值 {self.interval} 秒")
                return False

            return True

        except Exception as e:
            logger.error(f"规则质量检测失败: {e}")
            return False

    def _format_quality_check(self, text: str) -> bool:
        """
            使用格式对字幕质量进行检查。若字幕文件缺少时间戳或序号逻辑错误，则认为质量不合格。
            Args:
                text (str): 待检查的字幕文本。
            Returns:
                bool: 如果字幕质量合格返回True，否则返回False。
        """
        try:
            lines = text.strip().split('\n')

            # 检查基本格式
            if not lines:
                logger.warning("字幕文件为空")
                return False

            # 检查时间戳格式
            has_timestamps = False
            has_sequence = False

            i = 0
            while i < len(lines):
                line = lines[i].strip()

                # 检查序号行
                if line.isdigit():
                    has_sequence = True
                    i += 1
                    if i >= len(lines):
                        break

                    # 检查时间轴行
                    time_line = lines[i].strip()
                    if '-->' in time_line:
                        has_timestamps = True
                        i += 2  # 跳过时间轴行和文本行
                    else:
                        i += 1
                else:
                    i += 1

            if not has_timestamps:
                logger.warning("字幕文件缺少时间戳")
                return False

            if not has_sequence:
                logger.warning("字幕文件缺少序号")
                return False

            return True

        except Exception as e:
            logger.error(f"格式质量检测失败: {e}")
            return False

    def _parse_srt_timestamps(self, srt_content: str) -> list:
        """解析SRT文件中的时间戳。

        Args:
            srt_content: SRT字幕内容

        Returns:
            时间戳列表，每个元素为 (start_time, end_time) 的秒数
        """
        timestamps = []
        lines = srt_content.strip().split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # 检查是否为序号行
            if line.isdigit():
                i += 1
                if i >= len(lines):
                    break

                # 检查是否为时间轴行
                time_line = lines[i].strip()
                if '-->' in time_line:
                    # 解析时间格式 HH:MM:SS,mmm --> HH:MM:SS,mmm
                    times = time_line.split(' --> ')
                    if len(times) == 2:
                        start_seconds = self._parse_srt_time(times[0])
                        end_seconds = self._parse_srt_time(times[1])
                        timestamps.append((start_seconds, end_seconds))
                    i += 2  # 跳过时间轴行和文本行
                else:
                    i += 1
            else:
                i += 1

        return timestamps

    def _parse_srt_time(self, time_str: str) -> float:
        """将SRT时间格式转换为秒数。

        Args:
            time_str: SRT时间字符串 (HH:MM:SS,mmm)

        Returns:
            秒数
        """
        # 处理可能的空格
        time_str = time_str.strip()

        # 分离毫秒部分
        if ',' in time_str:
            time_part, ms_part = time_str.split(',')
            milliseconds = int(ms_part)
        else:
            time_part = time_str
            milliseconds = 0

        # 解析时分秒
        parts = time_part.split(':')
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
        else:
            raise ValueError(f"Invalid time format: {time_str}")

        total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
        return total_seconds

    def quality_check(self, text: str, context: PipelineContext) -> bool:
        """
            对字幕质量进行检查。先使用规则和格式检查，若不合格则使用低成本LLM进行检查。
            Args:
                text (str): 待检查的字幕文本。
                context(PipelineContext): 流水线执行上下文。
            Returns:
                bool: 如果字幕质量合格返回True，否则返回False。
        """
        return self._format_quality_check(text) and self._rule_quality_check(text) and self._llm_quality_check(text, context)