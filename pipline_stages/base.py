from abc import ABC, abstractmethod
from typing import Union

from models.movie import Movie, Video

Entity = Union[Movie, Video]

class PiplineStage(ABC):
    """流水线阶段抽象基类。

    定义流水线阶段的通用接口，所有具体的流水线阶段都需要继承此类。
    """
    @property
    @abstractmethod
    def name(self):
        """获取流水线阶段名称。

        Returns:
            str: 阶段名称。
        """
        pass

    @abstractmethod
    def should_execute(self, *args, **kwargs) -> bool:
        """判断当前阶段是否应该执行。

        Args:
            *args: 可变位置参数。
            **kwargs: 可变关键字参数。

        Returns:
            bool: 如果应该执行返回True，否则返回False。
        """
        pass

    @abstractmethod
    def execute(self, *args, **kwargs) -> Entity:
        """执行流水线阶段的处理逻辑。

        Args:
            *args: 可变位置参数。
            **kwargs: 可变关键字参数。

        Returns:
            Entity: 处理后的实体对象（Movie或Video）。
        """
        pass

class MoviePipelineStage(PiplineStage, ABC):
    """电影级流水线阶段抽象基类。

    处理整个电影对象的流水线阶段。
    """
    @abstractmethod
    def execute(self, movie: Movie) -> Entity:
        """执行电影级流水线阶段的处理逻辑。

        Args:
            movie (Movie): 待处理的电影对象。

        Returns:
            Entity: 处理后的实体对象。
        """
        pass

class VideoPipelineStage(PiplineStage, ABC):
    """视频级流水线阶段抽象基类。

    处理单个视频文件的流水线阶段。
    """
    @abstractmethod
    def execute(self, movie: Movie, video: Video) -> Entity:
        """执行视频级流水线阶段的处理逻辑。

        Args:
            movie (Movie): 视频所属的电影对象。
            video (Video): 待处理的视频对象。

        Returns:
            Entity: 处理后的实体对象。
        """
        pass