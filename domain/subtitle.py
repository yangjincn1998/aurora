from dataclasses import dataclass
from typing import Optional, List


@dataclass
class BilingualText:
    """可翻译文本数据类。

    用于存储原始文本及其翻译结果。

    Attributes:
        original (str): 原始文本。
        translated (Optional[str]): 翻译后的文本，可选。
    """
    original: str
    translated: Optional[str] = None


@dataclass
class BilingualList:
    """列表级别的双语对照数据类。

    用于存储两个对应的列表，一个是原始语言列表，一个是翻译语言列表。
    适用于类别、标签等列表数据，其中两种语言的列表项可能不完全一一对应。

    Attributes:
        original (List[str]): 原始语言的列表。
        translated (Optional[List[str]]): 翻译语言的列表，可选。
    """
    original: List[str]
    translated: Optional[List[str]] = None
