# == exceptions.py ==

class FatalError(Exception):
    """
    致命错误。发生此异常后，当前任务的核心流程应被终止。
    例如：字幕流程中的音频提取失败。
    """
    pass

class IgnorableError(Exception):
    """
    可忽略的错误。发生此异常后，程序可以记录日志并继续处理其他不相关的流程。
    例如：元数据抓取失败不应影响字幕流程。
    """
    pass