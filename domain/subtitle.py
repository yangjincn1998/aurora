from dataclasses import dataclass, fields
from typing import Optional, List

@dataclass
class Serializable:
    """可序列化接口。

    定义一个接口，要求实现to_serializable_dict方法，
    以便将对象转换为可序列化的字典格式。
    """
    def _to_serializable_structure_recursive(self, value):
        """递归地将Serializable子类转换为序列化的结构。

        Args:
            value (Union[list, set, Serializable, Any]): 待转换的值。

        Returns:
            Union[list, dict, Any]: 转换后的数据结构。
        """
        if isinstance(value, list):
            return [self._to_serializable_structure_recursive(v) for v in value]
        elif isinstance(value, set):
            return {self._to_serializable_structure_recursive(v) for v in value}
        elif isinstance(value, dict):
            return {k: self._to_serializable_structure_recursive(v) for k, v in value.items()}
        elif isinstance(value, tuple):
            return tuple(self._to_serializable_structure_recursive(v) for v in value)
        elif isinstance(value, Serializable):
            return value.to_serializable_dict()
        else:
            return value

    def to_serializable_dict(self) -> dict:
        """将对象转换为可序列化的字典格式。"""
        serial_dict = {}
        for field in fields(self):
            field_name = field.name
            value = getattr(self, field_name)
            serial_dict[field_name] = self._to_serializable_structure_recursive(value)
        return serial_dict

@dataclass
class BilingualText(Serializable):
    """可翻译文本数据类。

    用于存储原始文本及其翻译结果。

    Attributes:
        original (str): 原始文本。
        translated (Optional[str]): 翻译后的文本，可选。
    """
    original: str
    translated: Optional[str] = None


@dataclass
class BilingualList(Serializable):
    """列表级别的双语对照数据类。

    用于存储两个对应的列表，一个是原始语言列表，一个是翻译语言列表。
    适用于类别、标签等列表数据，其中两种语言的列表项可能不完全一一对应。

    Attributes:
        original (List[str]): 原始语言的列表。
        translated (Optional[List[str]]): 翻译语言的列表，可选。
    """
    original: List[str]
    translated: Optional[List[str]] = None
