from dataclasses import dataclass, field
from typing import Optional
from enum import Enum, auto

class ErrorType(Enum):
    LENGTH_LIMIT = auto()  # 输出因达到最大token限制而被截断
    CONTENT_FILTER = auto()  # 输出因违反内容过滤策略而被阻止
    INSUFFICIENT_RESOURCES = auto()  # 因系统资源不足请求被中断
    OTHER = auto()  # 其他错误

@dataclass
class QueryResult:
    success: bool
    content: Optional[str]
    error: Optional[ErrorType]=None