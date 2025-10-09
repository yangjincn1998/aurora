import os


class Config:
    default_config = {
        "SLICE_MODELS": {"deepseek/deepseek-chat-v3.1:free", "deepseek-chat"},
    }
    @classmethod
    def get_config(cls, key: str, default=None):
        return os.environ.get(key, cls.default_config.get(key, default))