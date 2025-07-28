# == organizer.py ==

import logging
import sys
import shutil
import os
import re
import json
from pathlib import Path
from typing import Dict

# --- 尝试导入 pywin32 ---
try:
    import win32com.client

    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False

# --- 从我们自己的模块导入 ---
from config import VIDEO_LIBRARY_DIRECTORY, INDEX_DIR, BILINGUAL_SUB_DIR, VIDEO_SOURCE_DIRECTORY
from exceptions import FatalError

logger = logging.getLogger(__name__)


# --- 内部辅助函数 ---

def _create_shortcut(target_path: Path, shortcut_path: Path):
    """[内部函数] 跨平台地创建指向目标的快捷方式或符号链接。"""
    if not target_path.exists():
        logger.error(f"无法创建快捷方式，因为目标路径不存在: {target_path}")
        return

    shortcut_path.parent.mkdir(parents=True, exist_ok=True)

    # 移除已存在的同名文件或损坏的链接
    if shortcut_path.exists() or shortcut_path.is_symlink():
        shortcut_path.unlink(missing_ok=True)

    if sys.platform == "win32" and PYWIN32_AVAILABLE:
        # 在Windows上优先创建 .lnk 快捷方式
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(str(shortcut_path.with_suffix('.lnk')))
        shortcut.TargetPath = str(target_path.resolve())
        shortcut.save()
    else:
        # 在其他系统或pywin32不可用时，创建符号链接
        try:
            os.symlink(target_path.resolve(), shortcut_path)
        except OSError as e:
            logger.error(f"创建符号链接失败: {e}。在Windows上可能需要管理员权限。")


def _sanitize_for_path(name: str) -> str:
    """[内部函数] 清理字符串，使其可以安全地作为文件名或目录名。"""
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


# --- 公开接口 (工人函数) ---

def standardize_library_worker(av_code: str, segment_id: str, original_video_path_str: str) -> Dict:
    """【工人函数】将单个视频及其资源移动到标准库目录。"""
    logger.info(f"--- 开始标准化归档: {av_code} (分段: {segment_id}) ---")
    try:
        original_video_path = Path(original_video_path_str)
        if not original_video_path.exists():
            raise FileNotFoundError(f"源视频文件不存在: {original_video_path}")

        final_movie_dir = VIDEO_LIBRARY_DIRECTORY / av_code
        final_movie_dir.mkdir(exist_ok=True)
        final_video_path = final_movie_dir / original_video_path.name

        if original_video_path.resolve() != final_video_path.resolve():
            shutil.move(original_video_path, final_video_path)
            logger.info(f"已移动视频文件到: {final_video_path}")

        stem = original_video_path.stem
        for sub_ext in ['.srt', '.ass']:
            bilingual_sub = BILINGUAL_SUB_DIR / (stem + sub_ext)
            if bilingual_sub.exists():
                shutil.copy2(bilingual_sub, final_movie_dir)

        return {'status': 'success', 'av_code': av_code, 'segment_id': segment_id, 'new_path': str(final_video_path)}
    except Exception as e:
        raise FatalError(f"归档失败: {e}") from e


def build_index_worker(all_status_data: Dict) -> Dict:
    """【工人函数】根据完整的状态数据构建分类索引。"""
    logger.info("--- 开始构建媒体库分类索引 ---")
    try:
        if INDEX_DIR.exists():
            logger.info(f"正在清理旧索引目录: {INDEX_DIR}")
            shutil.rmtree(INDEX_DIR)

        category_dirs = {
            "actors": INDEX_DIR / "演员 (Actors)",
            "genres": INDEX_DIR / "类别 (Categories)",
            "director": INDEX_DIR / "导演 (Directors)"
        }
        for d in category_dirs.values():
            d.mkdir(parents=True, exist_ok=True)

        # 【修正】在这里初始化 shortcut_count 变量
        shortcut_count = 0

        for av_code, data in all_status_data.items():
            metadata_path = VIDEO_LIBRARY_DIRECTORY / av_code / "metadata.json"
            if not metadata_path.exists():
                continue

            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            for segment in data.get('segments', {}).values():
                video_path = Path(segment['full_path'])
                if not video_path.exists() or not video_path.is_file():
                    continue

                shortcut_name_base = f"{video_path.stem} - {metadata.get('title_zh', av_code)}"
                shortcut_name = _sanitize_for_path(shortcut_name_base)

                director = metadata.get('director', {}).get('name_zh', '未知导演')
                _create_shortcut(video_path, category_dirs['director'] / _sanitize_for_path(director) / shortcut_name)
                shortcut_count += 1

                for actor in metadata.get('actors', []):
                    actor_name = actor.get('name_zh', '未知演员')
                    _create_shortcut(video_path,
                                     category_dirs['actors'] / _sanitize_for_path(actor_name) / shortcut_name)
                    shortcut_count += 1

                for category in metadata.get('categories', []):
                    cat_name = category.get('name_zh', '未分类')
                    _create_shortcut(video_path, category_dirs['genres'] / _sanitize_for_path(cat_name) / shortcut_name)
                    shortcut_count += 1

        logger.info(f"索引构建完成，共创建 {shortcut_count} 个快捷方式。")
        return {'status': 'success'}
    except Exception as e:
        raise FatalError(f"索引构建失败: {e}") from e


def audit_and_cleanup_source_worker(source_dir: Path, execute_cleanup: bool = False):
    """【工人函数】执行“先报告，后清理”的安全策略。"""
    logger.info(f"--- 开始审查源目录: {source_dir} | 执行清理: {execute_cleanup} ---")

    empty_dirs = [Path(root) for root, dirs, files in os.walk(source_dir, topdown=False) if
                  not dirs and not files and Path(root) != source_dir]

    if not empty_dirs:
        logger.info("审查完成，未发现可清理的空目录。")
        return

    print("\n--- 清理审查报告 ---")
    print("以下目录在视频文件被整理后已变为空目录:")
    for d in empty_dirs:
        print(f"- {d}")

    if execute_cleanup:
        print("\n[警告] 您已授权执行清理操作！")
        confirm = input("即将永久删除以上所有目录，是否继续？ (输入 'yes' 确认): ")
        if confirm.lower() == 'yes':
            logger.info("用户已确认，开始执行删除操作...")
            deleted_count = 0
            for d in empty_dirs:
                try:
                    d.rmdir()
                    logger.info(f"已删除目录: {d}")
                    deleted_count += 1
                except OSError as e:
                    logger.error(f"删除目录 {d} 失败 (可能非空或无权限): {e}")
            logger.info(f"清理完成，共删除了 {deleted_count} 个目录。")
        else:
            logger.info("用户取消了操作，未执行任何删除。")
    else:
        print("\n当前为报告模式，未执行删除。如需清理，请使用 '--execute' 参数。")