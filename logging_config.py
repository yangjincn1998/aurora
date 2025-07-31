# == logging_config.py ==
import logging
import sys
from config import BASE_DIR


class LevelFilter(logging.Filter):
    def __init__(self, level):
        super().__init__()
        self.level = level

    def filter(self, record):
        return record.levelno == self.level


def setup_logging():
    """配置全局的、分级的日志系统。"""
    LOG_DIR = BASE_DIR / "logs"
    LOG_DIR.mkdir(exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    formatter = logging.Formatter('%(asctime)s - %(process)d - %(levelname)s - %(name)s - %(message)s')

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    info_handler = logging.FileHandler(LOG_DIR / 'info.log', mode='w', encoding='utf-8')
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(formatter)
    info_handler.addFilter(LevelFilter(logging.INFO))
    root_logger.addHandler(info_handler)

    error_handler = logging.FileHandler(LOG_DIR / 'error.log', mode='w', encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    root_logger.addHandler(error_handler)

    root_logger.info("分级日志系统配置完成。")