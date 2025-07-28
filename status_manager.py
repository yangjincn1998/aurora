# == status_manager.py ==

import json
import os
import logging
from threading import Lock
import time
from pathlib import Path

# --- 从我们自己的模块导入 ---
from config import VIDEO_SOURCE_DIRECTORY, VIDEO_LIBRARY_DIRECTORY, STATUS_FILE_PATH
from scanner import scan_directory
from exceptions import FatalError

logger = logging.getLogger(__name__)


class StatManager:
    """
    一个线程/进程安全的状态管理器，所有方法都只应在主进程中调用。
    """

    def __init__(self, status_file=STATUS_FILE_PATH, source_dir=VIDEO_SOURCE_DIRECTORY,
                 library_dir=VIDEO_LIBRARY_DIRECTORY):
        """
        初始化状态管理器。

        参数:
            status_file (pathlib.Path): status.json 文件的路径。
            source_dir (pathlib.Path): 视频源文件目录。
            library_dir (pathlib.Path): 整理后的媒体库目录。
        """
        self.file_path = status_file
        self.source_dir = source_dir
        self.library_dir = library_dir
        self._lock = Lock()  # 此锁用于防止主进程中可能的多线程冲突
        self.status_data = self._load()

    def _load(self) -> dict:
        """从JSON文件加载状态。这是一个内部方法。"""
        if not self.file_path.exists():
            logger.info(f"状态文件 '{self.file_path}' 不存在，将创建新的状态。")
            return {}
        try:
            with self._lock, open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.info(f"状态已从 '{self.file_path}' 成功加载。")
                return data
        except (json.JSONDecodeError, TypeError):
            logger.error(f"状态文件 '{self.file_path}' 解析失败。将使用空状态。")
            return {}
        except Exception as e:
            raise FatalError(f"无法加载状态文件: {e}")

    def save(self):
        """将当前状态线程安全地保存到JSON文件。"""
        with self._lock:
            try:
                temp_file_path = self.file_path.with_suffix('.tmp')
                with open(temp_file_path, 'w', encoding='utf-8') as f:
                    json.dump(self.status_data, f, indent=2, ensure_ascii=False)
                os.replace(temp_file_path, self.file_path)
                logger.debug(f"状态已安全保存到 '{self.file_path}'。")
            except Exception as e:
                logger.error(f"保存状态到 '{self.file_path}' 时发生严重错误: {e}", exc_info=True)

    def reconcile(self):
        """
        将当前状态与文件系统进行比对和同步。
        """
        logger.info(">>> 开始执行状态同步流程...")
        source_snapshot = scan_directory(str(self.source_dir))
        library_snapshot = scan_directory(str(self.library_dir))
        filesystem_snapshot = {**source_snapshot, **library_snapshot}
        logger.info(f"扫描完成，文件系统中总共发现 {len(filesystem_snapshot)} 个独立番号。")

        status_changed = False
        status_codes = set(self.status_data.keys())
        snapshot_codes = set(filesystem_snapshot.keys())

        # 【修正逻辑】处理视频文件被删除的番号：只清空segments，保留元数据
        codes_with_no_videos = status_codes - snapshot_codes
        for code in codes_with_no_videos:
            if self.status_data.get(code, {}).get('segments'):
                logger.warning(f"番号 {code} 的所有视频文件已删除。清空文件段信息，但保留元数据。")
                self.status_data[code]['segments'] = {}
                status_changed = True

        for code, fs_data in filesystem_snapshot.items():
            fs_segments = fs_data.get('segments', {})
            if code not in self.status_data:
                logger.info(f"发现新番号: {code}。")
                self.status_data[code] = {
                    'features': {'metadata': {'status': 'new'}, 'subtitles': {'status': 'new'}},
                    'last_updated': time.time(),
                    'segments': fs_segments,
                    'metadata': {}  # 初始化空的元数据字段
                }
                status_changed = True
            else:
                # 同步已存在番号的分段信息（路径等）
                current_segments = self.status_data[code].setdefault('segments', {})
                if current_segments != fs_segments:
                    self.status_data[code]['segments'] = fs_segments
                    logger.info(f"番号 {code} 的分段/路径信息已更新。")
                    status_changed = True

        if status_changed:
            logger.info("状态在同步过程中已更新，正在保存 status.json...")
            self.save()
        else:
            logger.info("文件系统状态与记录一致，无需更新。")
        logger.info("<<< 状态同步流程执行完毕。")

    def get_all_status(self) -> dict:
        """获取整个状态字典的一个线程安全的副本。"""
        with self._lock:
            return self.status_data.copy()

    def get_movie_status(self, av_code: str) -> dict | None:
        """获取单个番号的状态信息的线程安全副本。"""
        with self._lock:
            return self.status_data.get(av_code, {}).copy()

    def update_feature_status(self, av_code: str, feature: str, new_status: str, error_msg: str = None):
        """更新特定功能的处理状态。"""
        with self._lock:
            if av_code in self.status_data:
                entry = self.status_data[av_code].setdefault('features', {}).setdefault(feature, {})
                entry['status'] = new_status
                entry['error_message'] = error_msg
                self.status_data[av_code]['last_updated'] = time.time()
                logger.info(f"番号 {av_code} 的功能 '{feature}' 状态已更新为: {new_status}")
        self.save()

    def update_segment_path(self, av_code: str, segment_id: str, new_path: str):
        """【新增方法】安全地更新一个视频分段的路径。"""
        with self._lock:
            if self.status_data.get(av_code, {}).get('segments', {}).get(segment_id):
                self.status_data[av_code]['segments'][segment_id]['full_path'] = new_path
        self.save()

    def update_metadata(self, av_code: str, metadata: dict):
        """【新增方法】安全地更新一个番号的元数据。"""
        with self._lock:
            if av_code in self.status_data:
                self.status_data[av_code]['metadata'] = metadata
        self.save()