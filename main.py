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
import scanner
import movie_crawler
import audio_extractor
import transcriber
import text_translator
import subtitle_generator
import organizer

logger = logging.getLogger(__name__)


# --- 状态诊断函数 ---
def determine_current_state(av_code: str, status_entry: dict) -> list:
    """根据物理文件和状态，动态诊断一个番号需要执行的任务列表。"""
    tasks_to_do = []
    features = status_entry.get('features', {})
    segments = status_entry.get('segments', {})
    if not segments: return []

    meta_status = features.get('metadata', {}).get('status')
    if meta_status not in ['completed', 'failed']:
        if not (config.VIDEO_LIBRARY_DIRECTORY / av_code / "metadata.json").exists():
            tasks_to_do.append('metadata')

    sub_status = features.get('subtitles', {}).get('status')
    if sub_status not in ['completed', 'failed']:
        first_segment_id = next(iter(segments))
        stem = Path(first_segment_id).stem

        if not (config.BILINGUAL_SUB_DIR / f"{stem}.ass").exists():
            if not (config.SCH_SUB_DIR / f"{stem}.srt").exists():
                if not (config.JAP_SUB_DIR / f"{stem}.srt").exists():
                    if Path(segments[first_segment_id]['full_path']).exists():
                        tasks_to_do.append('audio')
                else:
                    tasks_to_do.append('translate_srt')
            else:
                tasks_to_do.append('combine')

    return tasks_to_do


# --- 流水线函数 (已修正为循环诊断模型) ---
def run_process_pipeline(stat_manager: StatManager, gpu_lock, shared_status, force: bool):
    """执行完整的自动化处理流水线。"""
    logger.info("========== 启动完整处理流水线 ==========")

    max_procs = min((os.cpu_count() or 1), 4)
    with ProcessPoolExecutor(max_workers=max_procs) as executor:

        # 启动主循环，直到没有新任务产生
        while True:
            tasks_by_type = {'metadata': [], 'audio': [], 'transcribe': [], 'translate_srt': [], 'combine': []}
            all_status = stat_manager.get_all_status()

            # --- 生产者：在每次循环开始时，都重新诊断状态 ---
            for av_code, data in all_status.items():
                sub_feature_status = data.get('features', {}).get('subtitles', {}).get('status')
                tasks_to_do = determine_current_state(av_code, data)
                if force: tasks_to_do = ['metadata', 'audio', 'transcribe', 'translate_srt', 'combine']

                task_info = {'av_code': av_code, 'data': data}
                if 'metadata' in tasks_to_do: tasks_by_type['metadata'].append(task_info)
                if 'audio' in tasks_to_do: tasks_by_type['audio'].append(task_info)
                if sub_feature_status == 'audio_extracted' or (force and 'transcribe' in tasks_to_do): tasks_by_type[
                    'transcribe'].append(task_info)
                if sub_feature_status == 'transcribed' or (force and 'translate_srt' in tasks_to_do): tasks_by_type[
                    'translate_srt'].append(task_info)
                if sub_feature_status == 'translated_srt' or (force and 'combine' in tasks_to_do): tasks_by_type[
                    'combine'].append(task_info)

            # --- 检查是否还有任务 ---
            total_tasks = sum(len(t) for t in tasks_by_type.values())
            if total_tasks == 0:
                logger.info("所有任务均已完成，流水线结束。")
                break

            logger.info(f"新一轮诊断完成，发现 {total_tasks} 个待办任务。正在提交...")

            # --- 消费者：提交当前批次的任务 ---
            futures = {}
            worker_map = {
                'metadata': movie_crawler.crawl_metadata_worker, 'audio': audio_extractor.extract_audio_worker,
                'transcribe': transcriber.transcribe_audio_worker,
                'translate_srt': text_translator.translate_srt_worker,
                'combine': subtitle_generator.generate_subtitle_worker
            }

            for task_type, task_list in tasks_by_type.items():
                if not task_list: continue
                worker = worker_map[task_type]
                for t in task_list:
                    av_code = t['av_code']
                    if task_type == 'metadata':
                        f = executor.submit(worker, av_code, force)
                        futures[f] = {'type': 'metadata', 'av_code': av_code}
                    else:
                        for seg_id, seg_data in t['data']['segments'].items():
                            args = [av_code, seg_id]
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
                            futures[f] = {'type': task_type, 'av_code': av_code, 'segment_id': seg_id}

            # --- 结果处理：等待当前批次任务完成 ---
            for future in as_completed(futures):
                task_info = futures[future]
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
                            next_state = {'audio': 'audio_extracted', 'transcribe': 'transcribed',
                                          'translate_srt': 'translated_srt', 'combine': 'completed'}
                            stat_manager.update_feature_status(av_code, 'subtitles', next_state[task_type])
                except IgnorableError as e:
                    logger.warning(f"任务 {av_code} [Metadata] 失败: {e}")
                    stat_manager.update_feature_status(av_code, 'metadata', 'failed', str(e))
                except FatalError as e:
                    logger.error(f"任务 {av_code} [{task_type}] 失败: {e}")
                    stat_manager.update_feature_status(av_code, 'subtitles', 'failed', str(e))
                except Exception:
                    logger.critical(f"任务 {av_code} [{task_type}] 发生未处理的严重异常", exc_info=True)

    text_translator.save_all_caches()
    logger.info("========== 所有流水线任务已处理完毕 ==========")


def run_organizer_pipeline(stat_manager: StatManager):
    logger.info("========== 启动媒体库整理与索引任务 ==========")
    tasks = []
    for code, data in stat_manager.get_all_status().items():
        subs_ok = data.get('features', {}).get('subtitles', {}).get('status') == 'completed'
        if subs_ok and data.get('segments'):
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
    """主程序入口。"""
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