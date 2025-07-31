# == scanner.py ==
import re
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Union
from exceptions import FatalError
import json

logger = logging.getLogger(__name__)
VIDEO_EXTENSIONS: List[str] = ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm']
AV_PATTERNS_CASCADE: List[Tuple[str, str]] = [
    ("标准格式 (例如, DDT-475)", r'\b([A-Z]{2,5})-([0-9]{2,5})\b'),
    ("连续格式 (例如, sivr00315)", r'\b([A-Z]{2,6})([0-9]{3,5})')
]


def _normalize_code(code_parts: Tuple[str, str]) -> str:
    letters = code_parts[0].upper()
    numbers = str(int(code_parts[1]))
    padded_numbers = numbers.zfill(3)
    return f"{letters}-{padded_numbers}"


def _extract_av_code_and_segment(filename: str) -> Tuple[str | None, str | None]:
    stem = Path(filename).stem
    for desc, pattern in AV_PATTERNS_CASCADE:
        try:
            matches = list(re.finditer(pattern, stem, re.IGNORECASE))
            if matches:
                normalized_code = _normalize_code(matches[0].groups())
                return normalized_code, filename
        except re.error as e:
            logger.error(f"正则表达式错误: {pattern} - {e}")
            continue
    return None, None


def scan_directory(directory_path: Union[str, Path]) -> Dict:
    path = Path(directory_path).resolve()
    logger.info(f"--- 开始文件扫描任务: {path} ---")
    if not path.exists(): raise FatalError(f"扫描目录 '{path}' 不存在。")
    if not path.is_dir(): raise FatalError(f"扫描路径 '{path}' 是一个文件，而不是目录。")

    found_videos_map = {}
    try:
        all_files = list(path.rglob('*'))
        # 优先处理目录名
        for p in all_files:
            if p.is_dir():
                base_av_code, _ = _extract_av_code_and_segment(p.name)
                if base_av_code:
                    for video_file in p.iterdir():
                        if video_file.is_file() and video_file.suffix.lower() in VIDEO_EXTENSIONS:
                            av_entry = found_videos_map.setdefault(base_av_code, {'segments': {}})
                            av_entry['segments'][video_file.name] = {
                                'full_path': str(video_file.resolve()), 'video_file_name': video_file.name
                            }
        # 处理散落文件
        for p in all_files:
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS:
                base_av_code, seg_id = _extract_av_code_and_segment(p.name)
                if base_av_code:
                    # 检查是否已通过目录扫描找到，避免重复
                    if base_av_code not in found_videos_map:
                        av_entry = found_videos_map.setdefault(base_av_code, {'segments': {}})
                        av_entry['segments'][seg_id] = {'full_path': str(p.resolve()), 'video_file_name': seg_id}
    except (PermissionError, OSError) as e:
        raise FatalError(f"扫描因文件系统错误而终止: {e}") from e

    count = sum(len(data['segments']) for data in found_videos_map.values())
    logger.info(f"扫描完成。共找到 {count} 个视频文件，归属于 {len(found_videos_map)} 个番号。")
    return found_videos_map

if __name__ == "__main__":
    # 测试扫描功能
    test_directory = Path(r"D:\4. Collections\6.Adult Videos\raw")  # 请替换为实际测试目录
    try:
        result = scan_directory(test_directory)
        json = json.dumps(result, indent=4, ensure_ascii=False)
        with open('metadata.json', 'w', encoding='utf-8') as f:
            f.write(json)
    except FatalError as e:
        logger.error(f"扫描失败: {e}")