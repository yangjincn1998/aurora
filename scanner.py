# == scanner.py ==
import json

from config import VIDEO_SOURCE_DIRECTORY, METADATA_PATH
import re
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Union, Any
from exceptions import FatalError
from json import dumps, loads

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


def _load_metadata(path: Path) -> Dict[str, Any]:
    """一个健壮的辅助函数，用于加载和解析JSON文件。"""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, TypeError):
        logging.error(f"元数据文件 {path} 解析失败，将使用空字典。")
        return {}


def scan_and_make_json():
    """
    【重构版】
    通过一次循环全面同步文件系统和元数据文件，处理新增、删除和移动的情况。
    """
    # 1. 加载当前状态和磁盘上的最新状态
    memorized_metadata = _load_metadata(METADATA_PATH)
    current_metadata = scan_directory(VIDEO_SOURCE_DIRECTORY)

    # 创建一个深拷贝用于修改，以便最后与原始数据比较
    reconciled_metadata = json.loads(json.dumps(memorized_metadata))  # 简单的深拷贝方法

    # 2. 获取所有番号的合集，方便一次性遍历
    all_av_codes = set(memorized_metadata.keys()) | set(current_metadata.keys())

    # 3. 通过一次循环完成所有同步逻辑
    for av_code in all_av_codes:
        # 使用 .get() 提供空字典作为默认值，极大简化后续代码
        current_movie_data = current_metadata.get(av_code, {})
        current_segments = current_movie_data.get('segments', {})

        # 情况 A: 影片是新扫描到的
        if av_code not in reconciled_metadata:
            reconciled_metadata[av_code] = current_movie_data
            logging.info(f"发现新番号并已添加: {av_code}")
            continue

        # 情况 B: 影片已存在，需要检查其分段
        memorized_segments = reconciled_metadata[av_code].setdefault('segments', {})
        all_segment_ids = set(memorized_segments.keys()) | set(current_segments.keys())

        for segment_id in all_segment_ids:
            current_segment_data = current_segments.get(segment_id)

            # B.1: 分段被删除了
            if not current_segment_data:
                if not memorized_segments.get(segment_id, {}).get('deleted'):
                    memorized_segments[segment_id]['deleted'] = True
                    memorized_segments[segment_id]['full_path'] = None
                    logging.warning(f"分段已删除: {av_code} -> {segment_id}")
                continue

            # B.2: 分段是新增的
            if segment_id not in memorized_segments:
                memorized_segments[segment_id] = current_segment_data
                logging.info(f"发现新分段并已添加: {av_code} -> {segment_id}")
                continue

            # B.3: 分段已存在，检查路径是否变更 (移动)
            memorized_segment_data = memorized_segments[segment_id]
            if memorized_segment_data.get('full_path') != current_segment_data.get('full_path'):
                memorized_segment_data['full_path'] = current_segment_data['full_path']
                logging.info(f"分段路径已更新: {av_code} -> {segment_id}")

            # 确保 'deleted' 标志被正确设置
            memorized_segment_data['deleted'] = False

    # 4. 比较原始数据和最终数据，仅在有变化时才写入文件
    # 转换为格式化的JSON字符串进行比较，是一种精确且可靠的方式
    if json.dumps(memorized_metadata, sort_keys=True) != json.dumps(reconciled_metadata, sort_keys=True):
        logging.info("元数据已发生变更，正在写入文件...")
        METADATA_PATH.write_text(json.dumps(reconciled_metadata, indent=4, ensure_ascii=False), encoding='utf-8')
        print("元数据文件已更新。")
    else:
        logging.info("元数据与文件系统状态一致，无需更新。")
        print("元数据文件无需更新。")


