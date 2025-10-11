from dataclasses import dataclass, fields, field
from typing import List, Optional

@dataclass
class TranslateText:
    original: str
    translated: Optional[str] = None

@dataclass
class Metadata:
    title: Optional[TranslateText] = None
    release_date: Optional[str] = None
    director: Optional[TranslateText] = None

    categories: List[TranslateText] = field(default_factory=list)
    actors: List[TranslateText] = field(default_factory=list)
    actresses: List[TranslateText] = field(default_factory=list)

    @staticmethod
    def _sequence_express(value):
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
        flat_dict = {}
        for field in fields(self):
            field_name = field.name
            value = getattr(self, field_name)

            if value is None:
                continue
            flat_dict[field_name] = self._sequence_express(value)
        return flat_dict

@dataclass
class Status:
    pass

@dataclass
class Video():
    filename: str
    absolute_path: str
    status: Status
    #各阶段产物的内容或存储路径
    #by_products: ...


@dataclass
class Movie:
    code: str
    metadata: Optional[Metadata] = None
    terms: List[TranslateText] = field(default_factory=list)
    videos: List[Video] = field(default_factory=list)