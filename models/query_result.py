from dataclasses import dataclass, field
from typing import Optional, Dict, List
from enum import Enum, auto

from models.tasktype import TaskType


class ErrorType(Enum):
    LENGTH_LIMIT = auto()  # 输出因达到最大token限制而被截断
    CONTENT_FILTER = auto()  # 输出因违反内容过滤策略而被阻止
    INSUFFICIENT_RESOURCES = auto()  # 因系统资源不足请求被中断
    OTHER = auto()  # 其他错误

@dataclass
class ChatResult:
    """单次 Chat API 调用的结果"""
    success: bool
    attempt_count: int  # 调用大模型的次数（包含重试）
    time_taken: int  # 请求耗时（毫秒）
    content: Optional[str]
    error: Optional[ErrorType] = None

@dataclass
class ProcessResult:
    """策略处理的结果（文本级别）"""
    task_type: TaskType
    attempt_count: int  # 调用大模型的总次数
    time_taken: int  # 总耗时（毫秒）
    content: Optional[str]
    differences: Optional[List[Dict]] = None  # 改动列表
    success: bool = True  # 是否处理成功

class SrtBlockLinkedListNode:
    """字幕块链表节点，用于尽力而为的重试策略"""
    def __init__(self, origin: str, processed: Optional[ChatResult] = None, is_processed: bool = False, next_node=None):
        self.origin = origin  # 原始字幕文本
        self.processed = processed  # 处理结果
        self.is_processed = is_processed  # 是否已处理
        self.next = next_node  # 下一个节点

    def count_subtitles(self) -> int:
        """计算原始文本中的字幕条目数量（台词数）"""
        if not self.origin:
            return 0
        # 字幕块之间用两个换行符分隔
        blocks = self.origin.strip().split("\n\n")
        return len([b for b in blocks if b.strip()])

    def split_into_three(self) -> tuple['SrtBlockLinkedListNode', 'SrtBlockLinkedListNode', 'SrtBlockLinkedListNode']:
        """将当前节点的字幕文本三等分，返回三个新节点"""
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