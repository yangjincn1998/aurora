"""
双语字幕生成器模块

提供模块化的双语字幕生成功能，支持以日语字幕为蓝本，按时间戳匹配中文字幕内容。
只生成ASS格式字幕。
"""

from pathlib import Path
from typing import List, Optional, Any

import pysrt

from utils.logger import get_logger

logger = get_logger(__name__)

# ASS 字幕的样式和头部模板
ASS_HEADER_TEMPLATE = """[Script Info]
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


def _format_time_ass(time_obj) -> str:
    """将pysrt时间对象格式化为ASS时间戳 (H:MM:SS.cc)。"""
    return f"{time_obj.hours}:{time_obj.minutes:02d}:{time_obj.seconds:02d}.{time_obj.milliseconds // 10:02d}"


def _format_seconds_to_ass(seconds: float) -> str:
    """将秒数格式化为ASS时间戳 (H:MM:SS.cc)。"""
    if seconds < 0:
        seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    sec = int(seconds % 60)
    csec = int((seconds * 100) % 100)
    return f"{hours}:{minutes:02d}:{sec:02d}.{csec:02d}"


def _find_matching_chinese_subtitle(
    jap_sub: pysrt.SubRipItem,
    chinese_subs: List[pysrt.SubRipItem],
    time_tolerance_ms: int = 500,
) -> Optional[pysrt.SubRipItem]:
    """
    根据时间戳匹配找到对应的中文字幕。

    Args:
        jap_sub: 日语字幕项
        chinese_subs: 中文字幕列表
        time_tolerance_ms: 时间容差（毫秒）

    Returns:
        匹配的中文字幕项，如果没有找到则返回None
    """
    jap_start = jap_sub.start.ordinal
    jap_end = jap_sub.end.ordinal

    for ch_sub in chinese_subs:
        ch_start = ch_sub.start.ordinal
        ch_end = ch_sub.end.ordinal

        # 检查时间重叠
        if (
            abs(jap_start - ch_start) <= time_tolerance_ms
            and abs(jap_end - ch_end) <= time_tolerance_ms
        ):
            return ch_sub

    return None


def _generate_intro_metadata(metadata: Any) -> List[str]:
    """
    生成片头元数据展示内容。

    Args:
        metadata: 影片元数据对象

    Returns:
        ASS事件行列表
    """
    intro_events = []
    current_time = 0.0  # 从0秒开始

    # 辅助函数：获取翻译文本
    def _get_translated_text(bilingual_item):
        if hasattr(bilingual_item, "translated") and bilingual_item.translated:
            return bilingual_item.translated
        elif hasattr(bilingual_item, "original") and bilingual_item.original:
            return bilingual_item.original
        return ""

    # 辅助函数：获取列表文本
    def _get_list_text(bilingual_list):
        if isinstance(bilingual_list, list):
            return ", ".join(
                [
                    _get_translated_text(item)
                    for item in bilingual_list
                    if _get_translated_text(item)
                ]
            )
        elif hasattr(bilingual_list, "translated"):
            return ", ".join(bilingual_list.translated)
        return ""

    # 1. 大字居中：【题目】展示1s
    if metadata.title:
        title_text = _get_translated_text(metadata.title)
        if title_text:
            start_time = _format_seconds_to_ass(current_time)
            end_time = _format_seconds_to_ass(current_time + 1.0)
            intro_events.append(
                f"Dialogue: 0,{start_time},{end_time},Intro_Large,,0,0,0,,{title_text}"
            )
            current_time += 1.0

    # 2. 中字居中：演员：【演员名列表】1s
    actors_text = ""
    if metadata.actresses:
        actresses_text = _get_list_text(metadata.actresses)
        if actresses_text:
            actors_text += f"女演员：{actresses_text}"
    if metadata.actors:
        actors_list_text = _get_list_text(metadata.actors)
        if actors_list_text:
            if actors_text:
                actors_text += "，"
            actors_text += f"男演员：{actors_list_text}"

    if actors_text:
        start_time = _format_seconds_to_ass(current_time)
        end_time = _format_seconds_to_ass(current_time + 1.0)
        intro_events.append(
            f"Dialogue: 0,{start_time},{end_time},Intro_Normal,,0,0,0,,{actors_text}"
        )
        current_time += 1.0

    # 3. 中字居中：类别：【类别列表】1s
    if metadata.categories:
        categories_text = _get_list_text(metadata.categories)
        if categories_text:
            start_time = _format_seconds_to_ass(current_time)
            end_time = _format_seconds_to_ass(current_time + 1.0)
            intro_events.append(
                f"Dialogue: 0,{start_time},{end_time},Intro_Normal,,0,0,0,,类别：{categories_text}"
            )
            current_time += 1.0

    # 4. 中字居中：制作商【制作商译名】1s
    if metadata.studio:
        studio_text = _get_translated_text(metadata.studio)
        if studio_text:
            start_time = _format_seconds_to_ass(current_time)
            end_time = _format_seconds_to_ass(current_time + 1.0)
            intro_events.append(
                f"Dialogue: 0,{start_time},{end_time},Intro_Normal,,0,0,0,,制作商：{studio_text}"
            )
            current_time += 1.0

    # 5. 大字居中【导演中文名】作品\n发行日期（中字）1s
    director_text = ""
    if metadata.director:
        director_name = _get_translated_text(metadata.director)
        if director_name:
            director_text = f"{director_name}作品"

    release_date_text = ""
    if metadata.release_date:
        release_date_text = f"发行日期：{metadata.release_date}"

    if director_text or release_date_text:
        combined_text = director_text
        if release_date_text:
            if combined_text:
                combined_text += r"\N" + release_date_text
            else:
                combined_text = release_date_text

        start_time = _format_seconds_to_ass(current_time)
        end_time = _format_seconds_to_ass(current_time + 1.0)
        intro_events.append(
            f"Dialogue: 0,{start_time},{end_time},Intro_Large,,0,0,0,,{combined_text}"
        )
        current_time += 1.0

    return intro_events


def generate_bilingual_ass_subtitle(
    japanese_srt_path: str,
    chinese_srt_path: str,
    output_title: str = "Bilingual Subtitle",
    metadata: Optional[Any] = None,
) -> str:
    """
    生成双语ASS字幕内容。

    以日语字幕为蓝本，按时间戳匹配中文字幕的内容，找到一句就把这一句中文的内容加上。
    这样即使中文字幕完全为空，也有输出，不会报错。

    Args:
        japanese_srt_path: 日语字幕文件路径
        chinese_srt_path: 中文字幕文件路径
        output_title: 输出字幕的标题
        metadata: 影片元数据，用于生成片头信息

    Returns:
        ASS格式的双语字幕内容字符串
    """
    try:
        # 读取日语字幕
        if not Path(japanese_srt_path).exists():
            raise FileNotFoundError(f"日语字幕文件不存在: {japanese_srt_path}")

        jap_subs = pysrt.open(japanese_srt_path)

        # 读取中文字幕（如果存在）
        chinese_subs = []
        if Path(chinese_srt_path).exists():
            chinese_subs = pysrt.open(chinese_srt_path)

        # 生成 ASS 内容
        ass_events = []

        # 添加片头元数据部分
        if metadata:
            ass_events.append("; --- 片头元数据 ---")
            intro_events = _generate_intro_metadata(metadata)
            ass_events.extend(intro_events)

        # 添加对话部分
        ass_events.append("; --- Dialogue ---")

        for jap_sub in jap_subs:
            # 查找匹配的中文字幕
            ch_sub = _find_matching_chinese_subtitle(jap_sub, chinese_subs)

            # 获取字幕文本
            jap_text = jap_sub.text.replace("\n", r"\N")
            ch_text = ch_sub.text.replace("\n", r"\N") if ch_sub else ""

            # 格式化时间
            start_time = _format_time_ass(jap_sub.start)
            end_time = _format_time_ass(jap_sub.end)

            # 构建双语文本
            if ch_text:
                bilingual_text = f"{{\\rCHS_Main}}{ch_text}{{\\rJPN_Sub}}\\N{jap_text}"
            else:
                # 如果没有中文字幕，只显示日语
                bilingual_text = f"{{\\rJPN_Sub}}{jap_text}"

            # 添加对话行
            ass_events.append(
                f"Dialogue: 0,{start_time},{end_time},CHS_Main,,0,0,0,,{bilingual_text}"
            )

        # 组合完整的ASS内容
        final_ass_content = ASS_HEADER_TEMPLATE.format(title=output_title) + "\n".join(
            ass_events
        )

        logger.info(f"成功生成双语ASS字幕，共处理 {len(jap_subs)} 条日语字幕")
        return final_ass_content

    except Exception as e:
        error_msg = f"生成双语ASS字幕失败: {e}"
        logger.error(error_msg, exc_info=True)
        raise ValueError(error_msg) from e


def save_bilingual_ass_subtitle(
    japanese_srt_path: str,
    chinese_srt_path: str,
    output_path: str,
    output_title: str = "Bilingual Subtitle",
) -> None:
    """
    生成并保存双语ASS字幕文件。

    Args:
        japanese_srt_path: 日语字幕文件路径
        chinese_srt_path: 中文字幕文件路径
        output_path: 输出ASS文件路径
        output_title: 输出字幕的标题
    """
    try:
        # 生成ASS内容
        ass_content = generate_bilingual_ass_subtitle(
            japanese_srt_path, chinese_srt_path, output_title
        )

        # 确保输出目录存在
        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        # 保存文件
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        logger.info(f"双语ASS字幕已保存: {output_path}")

    except Exception as e:
        error_msg = f"保存双语ASS字幕失败: {e}"
        logger.error(error_msg, exc_info=True)
        raise
