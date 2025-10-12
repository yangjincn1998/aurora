from dataclasses import dataclass
from typing import Optional

from models.enums import TaskType


@dataclass
class TranslateContext:
    """处理上下文数据类。

    封装任务处理所需的上下文信息，包括任务类型、元数据和待处理文本。

    Attributes:
        task_type (TaskType): 任务类别。
        metadata (Optional[dict]): 任务相关的元数据。
        text_to_process (Optional[str]): 待处理的文本内容。
    """
    task_type: TaskType
    metadata: Optional[dict] = None
    text_to_process: Optional[str] = None
