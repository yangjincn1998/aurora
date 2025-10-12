from dataclasses import dataclass, field, fields
from typing import Optional, List, Dict, Any, Union

from models.enums import StageStatus, PiplinePhase
from domain.subtitle import BilingualText, BilingualList


@dataclass
class Metadata:
    """影片元数据数据类。

    存储影片的标题、发布日期、导演、分类、演员等元数据信息。

    Attributes:
        title (Optional[BilingualText]): 影片标题，可翻译文本。
        release_date (Optional[str]): 发布日期。
        director (Optional[BilingualText]): 导演信息，可翻译文本。
        studio (Optional[BilingualText]): 发行商
        synopsis (Optional[BilingualText]): 简介内容
        categories (Union[List[BilingualText], BilingualList, None]): 影片分类列表，
            可以是逐项对应的BilingualText列表，也可以是列表级别对应的BilingualList。
        actors (List[BilingualText]): 男演员列表。
        actresses (List[BilingualText]): 女演员列表。
    """
    title: Optional[BilingualText] = None
    release_date: Optional[str] = None
    director: Optional[BilingualText] = None
    studio: Optional[BilingualText] = None
    synopsis: Optional[BilingualText] = None

    categories: Union[List[BilingualText], BilingualList, None] = None
    actors: List[BilingualText] = field(default_factory=list)
    actresses: List[BilingualText] = field(default_factory=list)

    @staticmethod
    def _to_serializable_structure_recursive(value):
        """递归地将BilingualText和BilingualList转换为序列化的结构。

        Args:
            value (Union[list, BilingualText, BilingualList, Any]): 待转换的值。

        Returns:
            Union[list, dict, Any]: 转换后的数据结构。
        """
        if isinstance(value, list):
            return [Metadata._to_serializable_structure_recursive(v) for v in value]
        elif isinstance(value, BilingualText):
            translate_dict = {"japanese": value.original}
            if value.translated:
                translate_dict["chinese"] = value.translated
            return translate_dict
        elif isinstance(value, BilingualList):
            translate_dict = {"japanese": value.original}
            if value.translated:
                translate_dict["chinese"] = value.translated
            return translate_dict
        else:
            return value

    def to_serializable_dict(self) -> dict:
        """将元数据转换为序列化的字典格式。

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
            flat_dict[field_name] = self._to_serializable_structure_recursive(value)
        return flat_dict


@dataclass
class Video:
    """视频对象数据类。

    用以储存video对象的数据。

    Attributes:
        filename (str): 文件名,不带后缀。
        suffix (str): 文件后缀名。
        absolute_path (str): 文件绝对路径。
        status (Dict[PiplinePhase, StageStatus]): 文件经过各个流水线的情况。
        by_products (Dict[PiplinePhase, Any]): 流水线各阶段的副产品的存储路径。
    """
    filename: str
    suffix: str
    absolute_path: str
    status: Dict[PiplinePhase, StageStatus] = field(default_factory=dict)
    by_products: Dict[PiplinePhase, Any] = field(default_factory=dict)


@dataclass
class Movie:
    """电影对象数据类。

    存储电影的番号、元数据和相关视频文件。

    Attributes:
        code (str): 电影番号。
        metadata (Optional[domain.movie.Metadata]): 电影元数据。
        videos (List[Video]): 关联的视频文件列表。
    """
    code: str
    metadata: Optional[Metadata] = None
    videos: List[Video] = field(default_factory=list)
    #TODO:添加术语库
