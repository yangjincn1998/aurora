from abc import ABC, abstractmethod

from domain.movie import Metadata


class WebService(ABC):
    """
    实现Web服务的方法，之所以要做一个抽象类是因为，一些网站会换网址，不能在一棵树上吊死
    """

    @property
    @abstractmethod
    def available(self) -> bool:
        pass

    @property
    @abstractmethod
    def url(self) -> str:
        pass

    @abstractmethod
    def request(self, av_code: str, *args, **kwargs) -> str:
        """
        根据av番号向指定网站发送请求报文的方法
        Args:
            av_code(str): av番号
        Returns:
            str: 该网站返回的html文本
        """
        pass

    @abstractmethod
    def get_metadata(self, av_code: str) -> Metadata:
        """
        根据av番号检索影片元数据的方法
        Args:
            av_code(str): av番号
        Returns:
            Metadata: 这部av的元数据信息
        """
        pass

    @abstractmethod
    def validate_code(self, av_code: str) -> bool:
        """
        用于判定av番号是否正确的方法
        Args：
            av_code（str): av番号
        Returns：
            bool: 该番号是否有效
        """
        pass
