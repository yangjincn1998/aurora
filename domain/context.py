from dataclasses import dataclass
from typing import Optional, List, Dict

from domain.enums import TaskType
from domain.movie import Term


@dataclass
class TranslateContext:
    """处理上下文数据类。

    封装任务处理所需的上下文信息，包括任务类型、元数据和待处理文本。

    Attributes:
        task_type (TaskType): 任务类别。
        metadata (Optional[dict]): 任务相关的元数据。
        terms (Optional[List[Term]]): 术语库集合。
        text_to_process (Optional[str]): 待处理的文本内容。
        actors (Optional[List[Dict]]): 相关演员列表。
        actress (Optional[List[Dict]]): 相关女优列表。
    """

    task_type: TaskType
    metadata: Optional[dict] = None
    terms: Optional[List[Term]] = None
    text_to_process: Optional[str] = None
    actors: Optional[List[Dict]] = None
    actress: Optional[List[Dict]] = None
