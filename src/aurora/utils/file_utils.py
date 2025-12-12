"""
文件处理工具函数
"""

import hashlib
import os


def sample_and_calculate_sha256(file_path: str) -> str | FileNotFoundError | IOError:
    """
    计算文件部分内容的 SHA256 哈希值。

    从文件中心位置采样 1MB，以提高不同视频文件的区分度。
    对于小于采样大小的文件，将读取整个文件。

    Args:
        file_path (str): 文件的绝对路径。
    Returns:
        str: 计算出的 SHA256 哈希值的十六进制字符串。
    Raises:
        FileNotFoundError: 如果文件不存在。
        IOError: 发生IO错误。

    Examples:
        >>> # 从中心采样 (新默认行为)
        >>> hash1 = sample_and_calculate_sha256('/path/to/video.mp4')
    """
    hasher = hashlib.sha256()
    size = 1024 * 1024  # 采样大小为 1MB
    try:
        # 获取文件大小
        file_size = os.path.getsize(file_path)
        with open(file_path, "rb") as f:
            # 从中心位置采样
            if file_size <= size:
                # 文件小于采样大小，读取整个文件
                chunk = f.read()
            else:
                # 计算中心位置的起始偏移量
                # 中心位置 = (文件大小 - 采样大小) / 2
                offset = (file_size - size) // 2
                f.seek(offset)
                chunk = f.read(size)
            hasher.update(chunk)
        return hasher.hexdigest()
    except (FileNotFoundError, IOError) as e:
        raise e


def validate_sha256(sha256: str) -> bool:
    """
    验证给定的字符串是否为有效的 SHA256 哈希值。

    Args:
        sha256 (str): 要验证的 SHA256 哈希值字符串。

    Returns:
        bool: 如果字符串是有效的 SHA256 哈希值，返回 True；否则返回 False。

    Examples:
        >>> validate_sha256('1234567890abcdef' * 4)
        True
        >>> validate_sha256('invalid_sha256_hash')
        False
    """
    if len(sha256) != 64:
        return False
    try:
        int(sha256, 16)
        return True
    except ValueError:
        return False
