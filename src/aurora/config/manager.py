"""
负责加载 yaml 并实例化 Config 对象
"""
from pathlib import Path

import yaml

from aurora.config.settings import GlobalConfig
from aurora.utils.logger import get_logger

logger = get_logger(__name__)


def get_config_dir() -> Path:
    return Path(__file__).parent.parent.parent.parent


class ConfigManager:
    _instance: GlobalConfig | None = None
    _config_path: Path = get_config_dir() / "config.yaml"

    @classmethod
    def load(cls) -> GlobalConfig:
        if cls._instance:
            return cls._instance

        if not cls._config_path.exists():
            raise FileNotFoundError(f"Config file not found at {cls._config_path}")

        try:
            with open(cls._config_path, "r", encoding="utf-8") as f:
                raw_dict = yaml.safe_load(f) or {}
            cls._instance = GlobalConfig.model_validate(raw_dict)
            logger.info("Config loaded from %s", cls._config_path)
            return cls._instance
        except Exception as e:
            logger.exception("Config load failed")
            raise e

    @classmethod
    def get(cls) -> GlobalConfig:
        if cls._instance is None:
            return cls.load()
        return cls._instance


config = ConfigManager.get()
