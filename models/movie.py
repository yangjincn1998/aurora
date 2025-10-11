from dataclasses import dataclass, fields, field, Field
from typing import List, Optional, Dict, Any
from enum import Enum, auto

@dataclass
class TranslateText:
    """可翻译文本数据类。

    用于存储原始文本及其翻译结果。

    Attributes:
        original (str): 原始文本。
        translated (Optional[str]): 翻译后的文本，可选。
    """
    original: str
    translated: Optional[str] = None

@dataclass
class Metadata:
    """影片元数据数据类。

    存储影片的标题、发布日期、导演、分类、演员等元数据信息。

    Attributes:
        title (Optional[TranslateText]): 影片标题，可翻译文本。
        release_date (Optional[str]): 发布日期。
        director (Optional[TranslateText]): 导演信息，可翻译文本。
        categories (List[TranslateText]): 影片分类列表。
        actors (List[TranslateText]): 男演员列表。
        actresses (List[TranslateText]): 女演员列表。
    """
    title: Optional[TranslateText] = None
    release_date: Optional[str] = None
    director: Optional[TranslateText] = None

    categories: List[TranslateText] = field(default_factory=list)
    actors: List[TranslateText] = field(default_factory=list)
    actresses: List[TranslateText] = field(default_factory=list)

    @staticmethod
    def _sequence_express(value):
        """递归地将TranslateText转换为字典格式。

        Args:
            value (Union[list, TranslateText, Any]): 待转换的值，可以是列表、TranslateText或其他类型。

        Returns:
            Union[list, dict, Any]: 转换后的数据结构。
        """
        if isinstance(value, list):
            return [Metadata._sequence_express(v) for v in value]
        elif isinstance(value, TranslateText):
            translate_dict = {"japanese": value.original}
            if value.translated:
                translate_dict["chinese"] = value.translated
            return translate_dict
        else:
            return value

    def to_flat_dict(self) -> dict:
        """将元数据转换为扁平的字典格式。

        将所有非None字段转换为字典，其中TranslateText会被转换为包含
        japanese和chinese键的字典。

        Returns:
            dict: 扁平化的元数据字典。
        """
        flat_dict = {}
        for field in fields(self):
            field_name = field.name
            value = getattr(self, field_name)

            if value is None:
                continue
            flat_dict[field_name] = self._sequence_express(value)
        return flat_dict

class PiplineStage(Enum):
    """流水线阶段枚举。

    定义视频处理流水线中的各个阶段。

    Attributes:
        CORRECT: 字幕校正阶段。
        TRANSLATE: 字幕翻译阶段。
    """
    CORRECT = auto()
    TRANSLATE = auto()

class StageStatus(Enum):
    """流水线阶段状态枚举。

    定义流水线各阶段的执行状态。

    Attributes:
        SUCCESS: 执行成功。
        FAILED: 执行失败。
        PENDING: 待执行。
    """
    SUCCESS = auto()
    FAILED = auto()
    PENDING = auto()

@dataclass
class Video:
    """视频对象数据类。

    用以储存video对象的数据。

    Attributes:
        filename (str): 文件名,不带后缀。
        suffix (str): 文件后缀名。
        absolute_path (str): 文件绝对路径。
        status (Dict[PiplineStage, StageStatus]): 文件经过各个流水线的情况。
        by_products (Dict[PiplineStage, Any]): 流水线各阶段的副产品的存储路径。
    """
    filename: str
    suffix: str
    absolute_path: str
    status: Dict[PiplineStage, StageStatus] = field(default_factory=dict)
    by_products: Dict[PiplineStage, Any] = field(default_factory=dict)

@dataclass
class Movie:
    """电影对象数据类。

    存储电影的番号、元数据和相关视频文件。

    Attributes:
        code (str): 电影番号。
        metadata (Optional[Metadata]): 电影元数据。
        videos (List[Video]): 关联的视频文件列表。
    """
    code: str
    metadata: Optional[Metadata] = None
    videos: List[Video] = field(default_factory=list)
    #TODO:添加术语库