import logging
import os
from datetime import datetime
from typing import Optional

class CustomFormatter(logging.Formatter):
    """自定义日志格式化器，包含模块名、行数、日期时间"""

    def format(self, record):
        # 获取调用者的文件名（去除路径）
        filename = os.path.basename(record.pathname)
        module_name = os.path.splitext(filename)[0]

        # 格式化时间
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S')

        # 自定义日志格式: [时间] [级别] [模块名:行号] 消息
        log_format = f"[{timestamp}] [{record.levelname}] [{module_name}:{record.lineno}] {record.getMessage()}"

        return log_format

def setup_logger(name: str = "av_translator", log_level: str = "INFO", log_file: Optional[str] = None) -> logging.Logger:
    """
    设置日志系统

    Args:
        name: logger名称
        log_level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 日志文件路径，如果为None则使用默认路径

    Returns:
        配置好的logger对象
    """

    # 创建logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))

    # 清除已有的handler，避免重复添加
    logger.handlers.clear()

    # 创建自定义格式化器
    formatter = CustomFormatter()

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level.upper()))
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件处理器
    if log_file is None:
        # 创建logs目录
        os.makedirs("logs", exist_ok=True)
        log_file = f"logs/av_translator_{datetime.now().strftime('%Y%m%d')}.log"

    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(getattr(logging, log_level.upper()))
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 防止日志传播到根logger
    logger.propagate = False

    return logger

def get_logger(name: str = "av_translator") -> logging.Logger:
    """
    获取已配置的logger，如果不存在则创建新的

    Args:
        name: logger名称

    Returns:
        logger对象
    """
    logger = logging.getLogger(name)

    # 如果logger还没有被配置，则进行配置
    if not logger.handlers:
        return setup_logger(name)

    return logger