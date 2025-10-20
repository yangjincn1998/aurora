from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Union, TypedDict, NotRequired

from domain.subtitle import BilingualText, BilingualList, Serializable
from models.enums import StageStatus, PiplinePhase


class Term(TypedDict):
    japanese: str
    recommended_chinese: NotRequired[str]
    description: NotRequired[str]

@dataclass
class Metadata(Serializable):
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
        actors (List[BilingualText]|BilingualList): 男演员列表。
        actresses (List[BilingualText]|BilingualList): 女演员列表。
    """
    title: Optional[BilingualText] = None
    release_date: Optional[str] = None
    director: Optional[BilingualText] = None
    studio: Optional[BilingualText] = None
    synopsis: Optional[BilingualText] = None

    categories: Union[List[BilingualText], BilingualList, None] = None
    actors: List[BilingualText] | BilingualList = field(default_factory=list)
    actresses: List[BilingualText] | BilingualList = field(default_factory=list)


metadata = Metadata(
    title=BilingualText(
        original="SSIS-001 一ヶ月間の禁欲の果てに彼女のルームメイト2人と浮気SEXだけに没頭した彼女不在の3日間。 葵つかさ 乙白さやか",
        translated=None),
    # 中文页面系机翻，不提取
    release_date="2021-02-18",
    actresses=BilingualList(
        original=["葵つかさ", "乙白さやか"],
        translated=["葵司", "乙白沙也加"],
    ),
    actors=BilingualList(
        original=["平田司"],
        translated=["平田司"]
    ),
    studio=BilingualText(
        original="エスワン ナンバーワンスタイル",
        translated=None  # 同样不抽取
    ),
    categories=BilingualList(
        original=["美乳", "美少女", "寝取り・寝取られ・NTR", "ドラマ", "3P・4P", "ギリモザ", "ハイビジョン",
                  "独占配信"],
        translated=["中文字幕", "美乳", "美少女", "NTR", "剧情", "多人运动", "超薄格", "高清", "独家"]
    ),
    director=BilingualText(
        original="苺原",
        translated=None  # 不抽取
    ),
    synopsis=BilingualText(
        original="S1スリム美女優の豪華共演エモドラマ作！僕の彼女は友人2人とルームシェアをしている。僕もたまにその家に遊びにいくのだが年上でクールなルームメイト‘つかさ’に恋してしまい告白。彼女と一か月間エッチしなければイイ事してあげると言われ僕は禁欲生活の末にセックス。彼女は不在中だったがそれをもう一人の友人‘さやか’に見られ逆告白、なりゆきでエッチする。こじれた淫らな彼女不在の3日間のハメまくりNTR生活。",
        translated=None
    )
)
@dataclass
class Video:
    """视频对象数据类。

    用以储存video对象的数据。

    Attributes:
        sha256 (str): 视频文件的SHA256哈希值。
        filename (str): 文件名,不带后缀。
        suffix (str): 文件后缀名。
        absolute_path (str): 文件绝对路径。
        status (Dict[PiplinePhase, StageStatus]): 文件经过各个流水线的情况。
        by_products (Dict[PiplinePhase, Any]): 流水线各阶段的副产品的存储路径。
    """
    sha256: str
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
        terms (List[Term]): 术语库列表。
        videos (List[Video]): 关联的视频文件列表。
    """
    code: str
    metadata: Optional[Metadata] = None
    terms: List[Term] = field(default_factory=list)
    videos: List[Video] = field(default_factory=list)
