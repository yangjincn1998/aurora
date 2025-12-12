import hashlib

import pytest

from aurora.utils.file_utils import sample_and_calculate_sha256, validate_sha256

# ===================================
# 1. 测试 sample_and_calculate_sha256
# ===================================

SAMPLE_SIZE = 1024 * 1024


def test_sample_small_file(tmp_path):
    content = b"0" * 100
    f = tmp_path / "small_file.bin"
    f.write_bytes(content)

    result = sample_and_calculate_sha256(str(f))
    expected = hashlib.sha256(content).hexdigest()
    assert result == expected


def test_sample_large_file(tmp_path):
    part_size = 1024 * 1024

    # 准备一个 3MB 的文件
    content = b"a" * part_size + b"b" * part_size + b"c" * part_size
    f = tmp_path / "large_file.bin"
    f.write_bytes(content)

    result = sample_and_calculate_sha256(str(f))
    expected = hashlib.sha256(b"b" * part_size).hexdigest()
    assert result == expected


def test_sample_file_not_found():
    with pytest.raises(FileNotFoundError):
        sample_and_calculate_sha256("path/to/ghost/file.mp4")


# ===================================
# 2. 测试 validate_sha256
# ===================================
@pytest.mark.parametrize(
    "sha_input, expected",
    [
        ("a" * 64, True),  # 有效：全小写
        ("A" * 64, True),  # 有效：全大写 (int转换支持)
        ("1234567890abcdef" * 4, True),  # 有效：混合
        ("a" * 63, False),  # 无效：太短
        ("a" * 65, False),  # 无效：太长
        ("g" * 64, False),  # 无效：非十六进制字符
        ("", False),  # 无效：空
    ],
)
def test_validate_sha256(sha_input, expected):
    assert validate_sha256(sha_input) == expected
