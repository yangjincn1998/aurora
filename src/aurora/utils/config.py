import os


class Config:
    """配置管理类。

    提供应用配置的读取功能，支持从环境变量和默认配置中获取值。

    Attributes:
        default_config (dict): 默认配置字典。
    """

    default_config = {
        "SLICE_MODELS": {"deepseek/deepseek-chat-v3.1:free", "deepseek-chat"},
    }

    @classmethod
    def get_config(cls, key: str, default=None):
        """获取配置值。

        优先从环境变量获取，若不存在则从默认配置获取。

        Args:
            key (str): 配置键名。
            default (Any): 默认值，当配置键不存在时返回。

        Returns:
            Any: 配置值。
        """
        return os.environ.get(key, cls.default_config.get(key, default))
