from enum import Enum, auto

class TaskType(Enum):
    """任务类型枚举。

    定义系统支持的各种任务类型，包括元数据翻译和字幕处理。

    Attributes:
        METADATA_DIRECTOR: 元数据导演信息翻译任务。
        METADATA_ACTOR: 元数据演员信息翻译任务。
        METADATA_CATEGORY: 元数据分类信息翻译任务。
        CORRECT_SUBTITLE: 字幕校正任务。
        TRANSLATE_SUBTITLE: 字幕翻译任务。
    """
    METADATA_DIRECTOR = auto()
    METADATA_ACTOR = auto()
    METADATA_CATEGORY = auto()
    CORRECT_SUBTITLE = auto()
    TRANSLATE_SUBTITLE = auto()