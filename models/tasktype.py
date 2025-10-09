from enum import Enum, auto

class TaskType(Enum):
    METADATA_DIRECTOR = auto()
    METADATA_ACTOR = auto()
    METADATA_CATEGORY = auto()
    CORRECT_SUBTITLE = auto()
    TRANSLATE_SUBTITLE = auto()