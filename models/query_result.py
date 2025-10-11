from dataclasses import dataclass, field
from typing import Optional, Dict, List
from enum import Enum, auto

from models.tasktype import TaskType


class ErrorType(Enum):
    """错误类型枚举。

    定义各种API调用可能出现的错误类型，分为不可恢复错误、请求相关错误、可重试错误等。

    Attributes:
        AUTHENTICATION_ERROR: 认证失败（API密钥无效），不可恢复。
        PERMISSION_DENIED: 权限不足，不可恢复。
        INSUFFICIENT_QUOTA: 额度不足，不可恢复。
        NOT_FOUND: 资源不存在（如模型不存在），不可恢复。
        CONTENT_FILTER: 内容违规被过滤，不可恢复。
        UNPROCESSABLE_ENTITY: 请求格式/参数错误，不可恢复。
        PAYLOAD_TOO_LARGE: 请求体过大，不可恢复。
        LENGTH_LIMIT: 输出因达到最大token限制而被截断，请求相关错误。
        RATE_LIMIT: 速率限制（可等待后重试），可重试错误。
        CONNECTION_ERROR: 网络连接错误，可重试错误。
        TIMEOUT: 请求超时，可重试错误。
        OTHER: 其他未分类错误。
    """
    # === 不可恢复错误（应触发熔断）===
    AUTHENTICATION_ERROR = auto()  # 认证失败（API密钥无效）
    PERMISSION_DENIED = auto()  # 权限不足
    INSUFFICIENT_QUOTA = auto()  # 额度不足
    NOT_FOUND = auto()  # 资源不存在（如模型不存在）
    CONTENT_FILTER = auto()  # 内容违规被过滤
    UNPROCESSABLE_ENTITY = auto()  # 请求格式/参数错误
    PAYLOAD_TOO_LARGE = auto()  # 请求体过大

    # === 请求相关错误（可能需要调整请求，目前只支持一种）===
    LENGTH_LIMIT = auto()  # 输出因达到最大token限制而被截断


    # === 可重试错误 ===
    RATE_LIMIT = auto()  # 速率限制（可等待后重试）
    CONNECTION_ERROR = auto()  # 网络连接错误
    TIMEOUT = auto()  # 请求超时

    # === 其他 ===
    OTHER = auto()  # 其他未分类错误

@dataclass
class ChatResult:
    """单次Chat API调用的结果数据类。

    记录单次大模型API调用的结果信息。

    Attributes:
        success (bool): 调用是否成功。
        attempt_count (int): 调用大模型的次数（包含重试）。
        time_taken (int): 请求耗时（毫秒）。
        content (Optional[str]): 返回的文本内容。
        error (Optional[ErrorType]): 错误类型（如果失败）。
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
        differences (Optional[List[Dict]]): 校正任务中的改动列表。
        success (bool): 是否处理成功。
    """
    task_type: TaskType
    attempt_count: int  # 调用大模型的总次数
    time_taken: int  # 总耗时（毫秒）
    content: Optional[str]
    differences: Optional[List[Dict]] = None  # 改动列表
    success: bool = True  # 是否处理成功

class SrtBlockLinkedListNode:
    """字幕块链表节点类。

    用于尽力而为的重试策略，将字幕文本组织成链表结构以支持动态分片和重试。

    Attributes:
        origin (str): 原始字幕文本。
        processed (Optional[ChatResult]): 处理结果。
        is_processed (bool): 是否已处理。
        next (Optional[SrtBlockLinkedListNode]): 下一个节点。
    """
    def __init__(self, origin: str, processed: Optional[ChatResult] = None, is_processed: bool = False, next_node=None):
        """初始化字幕块链表节点。

        Args:
            origin (str): 原始字幕文本。
            processed (Optional[ChatResult]): 处理结果。
            is_processed (bool): 是否已处理。
            next_node (Optional[SrtBlockLinkedListNode]): 下一个节点。
        """
        self.origin = origin  # 原始字幕文本
        self.processed = processed  # 处理结果
        self.is_processed = is_processed  # 是否已处理
        self.next = next_node  # 下一个节点

    def count_subtitles(self) -> int:
        """计算原始文本中的字幕条目数量（台词数）。

        字幕块之间用两个换行符分隔。

        Returns:
            int: 字幕条目数量。
        """
        if not self.origin:
            return 0
        # 字幕块之间用两个换行符分隔
        blocks = self.origin.strip().split("\n\n")
        return len([b for b in blocks if b.strip()])

    def split_into_three(self) -> tuple['SrtBlockLinkedListNode', 'SrtBlockLinkedListNode', 'SrtBlockLinkedListNode']:
        """将当前节点的字幕文本三等分，返回三个新节点。

        将字幕块按台词数量三等分，创建三个新的链表节点并连接。

        Returns:
            tuple[SrtBlockLinkedListNode, SrtBlockLinkedListNode, SrtBlockLinkedListNode]:
                三个新创建的节点，按顺序连接。
        """
        blocks = self.origin.strip().split("\n\n")
        blocks = [b for b in blocks if b.strip()]  # 过滤空块

        total = len(blocks)
        third = total // 3

        # 三等分
        part1 = blocks[:third]
        part2 = blocks[third:2*third]
        part3 = blocks[2*third:]

        # 创建三个新节点
        node1 = SrtBlockLinkedListNode(origin="\n\n".join(part1) + "\n\n", is_processed=False)
        node2 = SrtBlockLinkedListNode(origin="\n\n".join(part2) + "\n\n", is_processed=False)
        node3 = SrtBlockLinkedListNode(origin="\n\n".join(part3) + "\n\n", is_processed=False)

        # 连接节点
        node1.next = node2
        node2.next = node3
        node3.next = self.next  # 保持与原链表的连接

        return node1, node2, node3