from dataclasses import dataclass
from typing import Optional, Dict, List, Set

from domain.enums import TaskType, ErrorType
from domain.movie import Term


@dataclass
class ChatResult:
    """单次Chat API调用的结果数据类。

    记录单次大模型API调用的结果信息。

    Attributes:
        success (bool): 调用是否成功。
        attempt_count (int): 调用大模型的次数（包含重试）。
        time_taken (int): 请求耗时（毫秒）。
        content (Optional[str]): 返回的文本内容。
        error (Optional[domains.enums.ErrorType]): 错误类型（如果失败）。
    """

    success: bool
    attempt_count: int  # 调用大模型的次数（包含重试）
    time_taken: int  # 请求耗时（毫秒）
    content: Optional[str]
    error: Optional[ErrorType] = None


@dataclass
class ProcessResult:
    """策略处理的结果数据类（文本级别）。

    记录文本处理任务的完整结果信息。

    Attributes:
        task_type (TaskType): 任务类别。
        attempt_count (int): 调用大模型的总次数。
        time_taken (int): 总耗时（毫秒）。
        content (Optional[str]): 经过处理后的文本内容。
        terms(Optional[Set[Dict]]): 术语提取与翻译结果列表。
        differences (Optional[List[Dict]]): 校正任务中的改动列表。
        terms(Optional[List[Term]]): 术语库列表。
        success (bool): 是否处理成功。
    """

    task_type: TaskType
    attempt_count: int  # 调用大模型的总次数
    time_taken: int  # 总耗时（毫秒）
    content: Optional[str]
    differences: Optional[List[Dict]] = None  # 改动列表
    terms: Optional[List[Term]] = None
    success: bool = True  # 是否处理成功
