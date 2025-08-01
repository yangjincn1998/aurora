# == subtitle_generator.py ==
import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple
import os
import re

from sympy.integrals.meijerint_doc import category

# --- 第三方库导入 ---
try:
    import pysrt

    PYSRT_AVAILABLE = True
except ImportError:
    PYSRT_AVAILABLE = False
    pysrt = None

# --- 从我们自己的模块导入 ---
from config import JAP_SUB_DIR, SCH_SUB_DIR, BILINGUAL_SUB_DIR, VIDEO_LIBRARY_DIRECTORY, METADATA_PATH
from exceptions import FatalError

# StatManager 不再需要导入

logger = logging.getLogger(__name__)

# --- 模块级常量与配置 ---
# ASS 字幕的样式和头部模板
ASS_HEADER_TEMPLATE = """
[Script Info]
Title: {title}
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: CHS_Main,Microsoft YaHei,75,&H00FFFFFF,&H000000FF,&H00000000,&H0050000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,20,1
Style: JPN_Sub,Microsoft YaHei,55,&H00B0B0B0,&H000000FF,&H00000000,&H0050000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,20,1
Style: Intro_Normal,Microsoft YaHei,65,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,2,5,10,10,10,1
Style: Intro_Small,Microsoft YaHei,50,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,2,5,10,10,10,1
Style: Intro_Large,Microsoft YaHei,80,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,1,0,0,0,100,100,0,0,1,2,2,5,10,10,10,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


# --- 内部辅助函数 (_ 开头) ---
def _format_time_ass(time_obj) -> str:
    """将pysrt时间对象格式化为ASS时间戳 (H:MM:SS.cc)。"""
    return f"{time_obj.hours}:{time_obj.minutes:02d}:{time_obj.seconds:02d}.{time_obj.milliseconds // 10:02d}"


def _format_time_srt(time_obj) -> str:
    """将pysrt时间对象格式化为SRT时间戳 (HH:MM:SS,mmm)。"""
    return f"{time_obj.hours:02d}:{time_obj.minutes:02d}:{time_obj.seconds:02d},{time_obj.milliseconds:03d}"


def _format_seconds_to_ass(seconds: float) -> str:
    """将秒数格式化为ASS时间戳 (H:MM:SS.cc)。"""
    if seconds < 0: seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    sec = int(seconds % 60)
    csec = int((seconds * 100) % 100)
    return f"{hours}:{minutes:02d}:{sec:02d}.{csec:02d}"


def _generate_metadata_intro_events(metadata: dict) -> List[str]:
    """
    【内部函数】根据元数据动态生成ASS格式的片头事件行。
    实现了“中文优先，日文回退，都没有则不显示”的逻辑和动态时间轴。
    """
    display_items = []

    # 1. 搜集并校验需要显示的元数据

    # --- 片名 (大字) ---
    title_text = metadata.get('title_zh') or metadata.get('title')
    if title_text and (title_text != "N/A" or title_text == "不详"):
        # 去除番号前缀
        clean_title = re.sub(r'^[A-Z]{2,5}-\d{2,5}\s*', '', title_text).strip()
        display_items.append({'style': 'Intro_Large', 'text': clean_title})

    # --- 主演 (中字) ---
    # 【修正】适配您的JSON结构，它现在是字符串列表
    actor_list = metadata.get('actors_zh') or metadata.get('actors', [])
    actor_list = [name for name in actor_list if name and name != "N/A"]
    if actor_list:
        actor_text = f"主演\\N{'  '.join(actor_list)}"
        display_items.append({'style': 'Intro_Normal', 'text': actor_text})

    # --- 类别 (中字) ---
    category_list = metadata.get('categories_zh') or metadata.get('categories', [])
    category_list = [name for name in category_list if name and name not in  ["N/A", "不详"]]
    if category_list:
        category_text = f"类别：{', '.join(category_list)}"
        display_items.append({'style': 'Intro_Normal', 'text': category_text})

    # --- 发行日期与导演 (大字) ---
    director_name = metadata.get('director_zh') or metadata.get('director')
    release_date = metadata.get('release_date')

    director_line_parts = []
    if release_date and release_date not in ["N/A", "不详"]:
        director_line_parts.append(release_date)
    if director_name and director_name != ["N/A", "不详"]:
        director_line_parts.append(f"{director_name} 作品")

    if director_line_parts:
        director_text = "\\N".join(director_line_parts)  # 使用ASS换行符
        display_items.append({'style': 'Intro_Large', 'text': director_text})

    # 2. 如果没有任何可显示项，则直接返回，不生成任何事件
    if not display_items:
        return []

    # 3. 动态计算时间轴并生成事件行
    events = ["; --- Metadata Intro Sequence ---"]
    total_duration = 15.0
    start_delay = 0.5
    # 根据实际要显示的条目数，均匀分配时间
    duration_per_item = [3, 2.5, 4, 3]
    current_time = start_delay
    fade_effect = r"{\fad(500,500)}"

    for i, item in enumerate(display_items):
        start_s = current_time
        end_s = current_time + duration_per_item[i]

        # 格式化时间并生成Dialogue行
        start_time_ass = _format_seconds_to_ass(start_s)
        end_time_ass = _format_seconds_to_ass(end_s)

        events.append(
            f"Dialogue: 0,{start_time_ass},{end_time_ass},{item['style']},,0,0,0,,{fade_effect}{item['text']}")
        current_time = end_s

    return events


# --- 核心功能函数 (文本级接口) ---

def _create_bilingual_subtitle_content(jap_srt_text: str, sch_srt_text: str, metadata: dict) -> Tuple[str, str]:
    """【核心功能函数】接收字幕文本和元数据，生成双语SRT和ASS两种格式的内容字符串。"""
    if not PYSRT_AVAILABLE: raise FatalError("pysrt 库未安装。")
    try:
        subs_jap = pysrt.from_string(jap_srt_text)
        subs_sch = pysrt.from_string(sch_srt_text)
    except Exception as e:
        raise ValueError(f"解析SRT文本失败: {e}") from e

    # 生成 ASS 内容
    ass_events = _generate_metadata_intro_events(metadata)
    ass_events.append("\n; --- Dialogue ---")
    sch_map = {sub.index: sub.text for sub in subs_sch}
    for jap_sub in subs_jap:
        sch_text = sch_map.get(jap_sub.index, "").replace('\n', r'\N')
        jap_text = jap_sub.text.replace('\n', r'\N')
        start_time, end_time = _format_time_ass(jap_sub.start), _format_time_ass(jap_sub.end)
        bilingual_text = f"{{\\rCHS_Main}}{sch_text}{{\\rJPN_Sub}}\\N{jap_text}"
        ass_events.append(f"Dialogue: 0,{start_time},{end_time},CHS_Main,,0,0,0,,{bilingual_text}")
    final_ass_content = ASS_HEADER_TEMPLATE.format(title=metadata.get('title', '')) + "\n".join(ass_events)

    # 生成 SRT 内容
    actors_str = ', '.join([a for a in metadata.get('actors_zh', [])])
    info_header = f"0\n00:00:00,000 --> 00:00:05,000\n--- 由 Aurora 字幕工具生成 ---\n片名: {metadata.get('title_zh', 'N/A')}\n演员: {actors_str}\n"
    srt_content_parts = [info_header]
    for i, jap_sub in enumerate(subs_jap):
        sch_text = sch_map.get(jap_sub.index, "")
        bilingual_text = f"{sch_text}\n{jap_sub.text}"
        srt_content_parts.append(
            f"{i + 1}\n{_format_time_srt(jap_sub.start)} --> {_format_time_srt(jap_sub.end)}\n{bilingual_text}")
    final_srt_content = "\n\n".join(srt_content_parts)

    return final_srt_content, final_ass_content


# --- 公开接口 (工人/编排层) ---

def generate_subtitle_worker(av_code: str, segment_id: str, force: bool = False) -> Dict:
    """
    【工人函数】负责编排单个字幕文件的合并与生成流程。
    【架构修正】不再接收 stat_manager，改为返回结果字典。
    """
    logger.info(f"--- 开始处理番号 {av_code} (分段: {segment_id}) 的【核心流程：双语字幕生成】 ---")

    stem = Path(segment_id).stem
    jap_srt_path = JAP_SUB_DIR / f"{stem}.srt"
    sch_srt_path = SCH_SUB_DIR / f"{stem}.srt"
    bilingual_srt_path = BILINGUAL_SUB_DIR / f"{stem}.srt"
    bilingual_ass_path = BILINGUAL_SUB_DIR / f"{stem}.ass"
    metadata_path = METADATA_PATH

    try:
        # 依赖文件检查
        if not jap_srt_path.exists(): raise FatalError(f"依赖文件缺失：{jap_srt_path}")
        if not sch_srt_path.exists(): raise FatalError(f"依赖缺失：{sch_srt_path}")

        # 幂等性与时间戳检查
        if bilingual_ass_path.exists() and not force:
            ass_mtime = bilingual_ass_path.stat().st_mtime
            if ass_mtime >= jap_srt_path.stat().st_mtime and ass_mtime >= sch_srt_path.stat().st_mtime:
                logger.info(f"双语字幕 '{bilingual_ass_path.name}' 已是最新，跳过。")
                return {'status': 'skipped', 'av_code': av_code, 'segment_id': segment_id}

        movies_metadata = {}
        if metadata_path.exists():
            with open(metadata_path, 'r', encoding='utf-8') as f: movies_metadata = json.load(f)
        movie_metadata = movies_metadata.get(av_code, {})

        jap_srt_text = jap_srt_path.read_text(encoding='utf-8')
        sch_srt_text = sch_srt_path.read_text(encoding='utf-8')

        srt_content, ass_content = _create_bilingual_subtitle_content(jap_srt_text, sch_srt_text, movie_metadata)

        BILINGUAL_SUB_DIR.mkdir(parents=True, exist_ok=True)
        bilingual_srt_path.write_text(srt_content, encoding='utf-8')
        bilingual_ass_path.write_text(ass_content, encoding='utf-8')

        logger.info(f"成功为 {segment_id} 生成双语字幕文件。")
        return {'status': 'success', 'av_code': av_code, 'segment_id': segment_id}

    except Exception as e:
        error_message = f"双语字幕生成失败: {e}"
        logger.critical(f"为 {segment_id} 生成双语字幕时发生致命错误: {error_message}", exc_info=True)
        raise FatalError(error_message) from e