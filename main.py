# == main.py ==

import argparse
import logging
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

# --- 在所有其他导入之前，首先配置日志系统 ---
from logging_config import setup_logging

setup_logging()

# --- 从我们自己的模块导入 ---
import config
from status_manager import StatManager
from exceptions import FatalError, IgnorableError
import movie_crawler
import audio_extractor
import transcriber
import text_translator
import subtitle_generator
import organizer

logger = logging.getLogger(__name__)


# --- 状态诊断函数 (已优化) ---
def get_tasks_for_movie(av_code: str, status_entry: dict) -> list:
    """根据番号的当前状态，动态诊断出下一步需要执行的任务列表。"""
    tasks_to_do = []
    features = status_entry.get('features', {})
    segments = status_entry.get('segments', {})
    if not segments: return []

    # 诊断元数据流程 (并行)
    meta_status = features.get('metadata', {}).get('status')
    if meta_status == 'new':
        tasks_to_do.append('metadata')

    # 诊断字幕流程 (串行)
    sub_status = features.get('subtitles', {}).get('status')
    if sub_status != 'completed' and sub_status != 'failed':
        if sub_status == 'new':
            tasks_to_do.append('audio')
        elif sub_status == 'audio_extracted':
            tasks_to_do.append('transcribe')
        elif sub_status == 'transcribed':
            tasks_to_do.append('translate_srt')
        elif sub_status == 'translated_srt':
            tasks_to_do.append('combine')

    return tasks_to_do


# --- 流水线函数 (已修正为真正的流水线模型) ---
def run_process_pipeline(stat_manager: StatManager, gpu_lock, shared_status, force: bool):
    """执行完整的、事件驱动的自动化处理流水线。"""
    logger.info("========== 启动完整处理流水线 ==========")

    max_procs = min((os.cpu_count() or 1), 4)
    with ProcessPoolExecutor(max_workers=max_procs) as executor:
        futures = {}
        worker_map = {
            'metadata': movie_crawler.crawl_metadata_worker, 'audio': audio_extractor.extract_audio_worker,
            'transcribe': transcriber.transcribe_audio_worker, 'translate_srt': text_translator.translate_srt_worker,
            'combine': subtitle_generator.generate_subtitle_worker
        }

        def submit_task(task_info: dict):
            """一个安全的辅助函数，用于构建参数并提交任务。"""
            task_type = task_info['type']
            av_code = task_info['av_code']
            worker = worker_map[task_type]

            logger.info(f"为 {av_code} 创建并提交任务 [{task_type}]")
            current_status = stat_manager.get_movie_status(av_code)

            if task_type == 'metadata':
                f = executor.submit(worker, av_code, force)
                futures[f] = {'type': 'metadata', 'av_code': av_code}
            else:
                for seg_id, seg_data in current_status.get('segments', {}).items():
                    args = [av_code, seg_id]
                    # 为不同的工人函数准备它们需要的特定参数
                    if task_type == 'audio':
                        args.append(seg_data['full_path'])
                    elif task_type == 'transcribe':
                        audio_path = str(config.AUDIO_DIR / (Path(seg_id).stem + ".mp3"))
                        args.extend([audio_path, gpu_lock, shared_status])
                    elif task_type == 'translate_srt':
                        jap_srt_path = str(config.JAP_SUB_DIR / (Path(seg_id).stem + ".srt"))
                        meta_path = str(config.VIDEO_LIBRARY_DIRECTORY / av_code / "metadata.json")
                        args.extend([jap_srt_path, meta_path])
                    args.append(force)

                    f = executor.submit(worker, *args)
                    task_info['segment_id'] = seg_id
                    futures[f] = task_info

        # --- 步骤1: 提交初始任务 ---
        logger.info("正在进行初始任务诊断...")
        for av_code, data in stat_manager.get_all_status().items():
            tasks_to_do = ['metadata', 'audio'] if force else get_tasks_for_movie(av_code, data)
            for task_type in tasks_to_do:
                submit_task({'type': task_type, 'av_code': av_code})

        if not futures:
            logger.info("没有发现任何需要处理的初始任务。流水线结束。")
            return

        # --- 步骤2: 事件驱动循环 ---
        logger.info(f"初始任务提交完成，共 {len(futures)} 个。进入事件循环...")
        while futures:
            for future in as_completed(futures):
                task_info = futures.pop(future)
                av_code = task_info['av_code']
                task_type = task_info['type']
                try:
                    result = future.result()
                    if result and result.get('status') in ['success', 'skipped']:
                        logger.info(f"任务 {av_code} [{task_type}] 成功完成。")
                        if task_type == 'metadata' and result.get('status') == 'success':
                            stat_manager.update_metadata(av_code, result['metadata'])
                            stat_manager.update_feature_status(av_code, 'metadata', 'completed')
                        elif task_type != 'metadata':
                            next_state_map = {'audio': 'audio_extracted', 'transcribe': 'transcribed',
                                              'translate_srt': 'translated_srt', 'combine': 'completed'}
                            stat_manager.update_feature_status(av_code, 'subtitles', next_state_map[task_type])

                        # --- 任务接力 ---
                        if not force:
                            current_status = stat_manager.get_movie_status(av_code)
                            next_tasks = get_tasks_for_movie(av_code, current_status)
                            for next_task_type in next_tasks:
                                submit_task({'type': next_task_type, 'av_code': av_code})
                except (IgnorableError, FatalError) as e:
                    feature = 'metadata' if task_type == 'metadata' else 'subtitles'
                    log_level = logging.WARNING if isinstance(e, IgnorableError) else logging.ERROR
                    logger.log(log_level, f"任务 {av_code} [{task_type}] 失败: {e}")
                    stat_manager.update_feature_status(av_code, feature, 'failed', str(e))
                except Exception:
                    logger.critical(f"任务 {av_code} [{task_type}] 发生未处理的严重异常", exc_info=True)

    text_translator.save_all_caches()
    logger.info("========== 所有流水线任务已处理完毕 ==========")


def run_organizer_pipeline(stat_manager: StatManager):
    logger.info("========== 启动媒体库整理与索引任务 ==========")
    tasks = []
    for code, data in stat_manager.get_all_status().items():
        meta_ok = data.get('features', {}).get('metadata', {}).get('status') in ['completed', 'failed']
        subs_ok = data.get('features', {}).get('subtitles', {}).get('status') == 'completed'
        if meta_ok and subs_ok and data.get('segments'):
            for seg_id, seg_data in data['segments'].items():
                tasks.append({'av_code': code, 'segment_id': seg_id, 'path': seg_data['full_path']})

    with ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {executor.submit(organizer.standardize_library_worker, t['av_code'], t['segment_id'], t['path']): t
                      for t in tasks}
        for future in as_completed(future_map):
            task_info = future_map[future]
            try:
                result = future.result()
                if result.get('status') == 'success':
                    stat_manager.update_segment_path(result['av_code'], result['segment_id'], result['new_path'])
            except Exception as e:
                logger.error(f"归档任务 {task_info['av_code']} 失败: {e}")

    organizer.build_index_worker(stat_manager.get_all_status())


def main():
    parser = argparse.ArgumentParser(description="Aurora AV Toolkit - 媒体处理与管理套件")
    parser.add_argument('task', choices=['process', 'organize', 'cleanup', 'reconcile'], help="要执行的任务")
    parser.add_argument('--force', action='store_true', help="强制重新执行已完成的任务")
    parser.add_argument('--execute', action='store_true', help="在 cleanup 任务中，真实地执行删除操作")
    args = parser.parse_args()

    multiprocessing.freeze_support()

    with multiprocessing.Manager() as manager:
        shared_status = manager.dict({'transcription_service': 'assemblyai'})
        gpu_lock = manager.Lock()

        stat_manager = StatManager()

        if args.task != 'cleanup':
            stat_manager.reconcile()

        if args.task == 'process':
            run_process_pipeline(stat_manager, gpu_lock, shared_status, args.force)
        elif args.task == 'organize':
            run_organizer_pipeline(stat_manager)
        elif args.task == 'cleanup':
            organizer.audit_and_cleanup_source_worker(config.VIDEO_SOURCE_DIRECTORY, args.execute)

        logger.info(f"'{args.task}' 任务已完成。")


if __name__ == "__main__":
    main()