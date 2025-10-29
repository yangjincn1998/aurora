"""
文件处理工具函数
"""

import hashlib
import os


def calculate_partial_sha256(
        file_path: str, size: int = 1024 * 1024, from_center: bool = True
) -> str:
    """
    计算文件部分内容的 SHA256 哈希值。

    默认从文件中心位置采样，以提高不同视频文件的区分度。
    对于小于采样大小的文件，将读取整个文件。

    Args:
        file_path (str): 文件的绝对路径。
        size (int): 要读取的字节数，默认为 1MB (1024 * 1024)。
        from_center (bool): 是否从文件中心位置采样。
                           - True (默认): 从文件中心位置采样，适用于视频文件
                           - False: 从文件开头采样，向后兼容旧行为

    Returns:
        str: 计算出的 SHA256 哈希值的十六进制字符串。
             如果文件不存在或发生IO错误，则返回空字符串。

    Examples:
        >>> # 从中心采样 (新默认行为)
        >>> hash1 = calculate_partial_sha256('/path/to/video.mp4')

        >>> # 从开头采样 (向后兼容)
        >>> hash2 = calculate_partial_sha256('/path/to/video.mp4', from_center=False)

        >>> # 自定义采样大小
        >>> hash3 = calculate_partial_sha256('/path/to/video.mp4', size=2*1024*1024)
    """
    hasher = hashlib.sha256()
    try:
        # 获取文件大小
        file_size = os.path.getsize(file_path)

        with open(file_path, "rb") as f:
            if from_center:
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
            else:
                # 从开头采样（向后兼容旧行为）
                chunk = f.read(size)

            hasher.update(chunk)
        return hasher.hexdigest()
    except (FileNotFoundError, IOError) as e:
        # 在实际应用中，你可能想要记录这个错误
        # 这里保持向后兼容，返回空字符串
        return ""
