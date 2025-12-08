from pathlib import Path
from typing import List

from domain.enums import StageStatus, PiplinePhase
from domain.movie import Movie, Video
from domain.subtitle import BilingualList, BilingualText
from pipeline.base import VideoPipelineStage
from pipeline.context import PipelineContext
from utils.bilingual_subtitle_generator import generate_bilingual_ass_subtitle
from utils.logger import get_logger

logger = get_logger(__name__)


def _transform_to_text(item: BilingualList | List[BilingualText] | None) -> str | None:
    """将双语文本对象转换为字符串。"""
    if isinstance(item, list):
        item_list = ", ".join(
            [i.translated if i.translated else i.original for i in item]
        )
    elif isinstance(item, BilingualList):
        item_list = ", ".join(item.translated)
    else:
        item_list = None
    return item_list


class BilingualSubtitleStage(VideoPipelineStage):
    """双语字幕生成流水线阶段。

    负责将日语字幕和中文翻译字幕合并生成双语字幕文件（仅ASS格式）。
    以日语字幕为蓝本，按时间戳匹配中文字幕的内容。
    """

    def name(self):
        """获取阶段名称。

        Returns:
            str: 阶段名称 "bilingual_subtitle"。
        """
        return "bilingual_subtitle"

    def should_execute(self, video: Video, context: PipelineContext):
        """判断是否应该执行双语字幕生成阶段。

        Args:
            video (Video): 待检查的视频对象。
            context (PipelineContext): 流水线执行上下文。

        Returns:
            bool: 如果双语字幕阶段未成功完成则返回True。
        """
        return (
            video.status.get(PiplinePhase.BILINGUAL_SUBTITLE, StageStatus.PENDING)
            != StageStatus.SUCCESS
        )

    def execute(self, movie: Movie, video: Video, context: PipelineContext):
        """执行双语字幕生成处理。

        读取日语字幕和中文翻译字幕，合并生成双语字幕文件（仅ASS格式）。
        以日语字幕为蓝本，按时间戳匹配中文字幕的内容。

        Args:
            movie (Movie): 视频所属的电影对象。
            video (Video): 待处理的视频对象。
            context (PipelineContext): 流水线上下文，提供共享的对象和服务。

        """
        try:
            # 获取日语字幕和中文翻译字幕文件路径
            jap_srt_path = video.by_products[PiplinePhase.CORRECT_SUBTITLE]
            sch_srt_path = video.by_products[PiplinePhase.TRANSLATE_SUBTITLE]

            # 检查日语字幕文件是否存在
            if not Path(jap_srt_path).exists():
                raise FileNotFoundError(f"日语字幕文件不存在: {jap_srt_path}")

            # 检查中文字幕文件是否存在，如果不存在则记录警告
            if not Path(sch_srt_path).exists():
                logger.warning(f"中文字幕文件不存在: {sch_srt_path}，将仅生成日语字幕")

            # 生成输出标题
            metadata = movie.metadata
            title = (
                metadata.title.translated
                if metadata.title.translated
                else metadata.title.original
            )
            output_title = f"{movie.code} - {title}"

            # 生成双语ASS字幕内容
            ass_content = generate_bilingual_ass_subtitle(
                japanese_srt_path=jap_srt_path,
                chinese_srt_path=sch_srt_path,
                output_title=output_title,
                metadata=movie.metadata,
            )

            # 保存双语字幕文件
            output_dir = Path(context.output_dir) / movie.code
            output_dir.mkdir(parents=True, exist_ok=True)

            # ASS格式双语字幕
            bilingual_ass_path = output_dir / f"{video.filename}.ass"
            bilingual_ass_path.write_text(ass_content, encoding="utf-8")
            logger.info(f"双语ASS字幕已保存: {bilingual_ass_path}")

            # 更新视频状态和输出路径（只记录ass目录的位置）
            video.by_products[PiplinePhase.BILINGUAL_SUBTITLE] = str(bilingual_ass_path)
            video.status[PiplinePhase.BILINGUAL_SUBTITLE] = StageStatus.SUCCESS

            logger.info(f"成功为 {video.filename} 生成双语ASS字幕文件")

        except Exception as e:
            error_message = f"双语字幕生成失败: {e}"
            logger.error(
                f"为 {video.filename} 生成双语字幕时发生错误: {error_message}",
                exc_info=True,
            )
            video.status[PiplinePhase.BILINGUAL_SUBTITLE] = StageStatus.FAILED
            raise
