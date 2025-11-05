from dataclasses import fields, is_dataclass
from typing import List, Optional, Any

from langfuse import observe, get_client

from domain.movie import Movie, Metadata
from domain.subtitle import BilingualText, BilingualList
from models.enums import TaskType, MetadataType
from pipeline.base import MoviePipelineStage
from pipeline.context import PipelineContext
from services.pipeline.database_manager import DatabaseManager
from services.translation.orchestrator import TranslateOrchestrator
from services.web_request.javbus_web_service import JavBusWebService
from services.web_request.web_service import WebService
from utils.logger import get_logger

logger = get_logger(__name__)


class ScrapeStage(MoviePipelineStage):
    """影片信息抓取流水线阶段。

    负责从指定网站抓取影片的元数据信息。
    """

    def __init__(self, web_servers: List[WebService]):
        """初始化抓取阶段。

        Args:
            web_servers (List[WebService]): 用于抓取影片信息的Web服务列表。
        """
        self.web_servers = web_servers

    def name(self):
        """获取阶段名称。

        Returns:
            str: 阶段名称 "scrape"。
        """
        return "scrape"

    def should_execute(self, movie, context: PipelineContext) -> bool:
        """判断是否应该执行抓取阶段。

        Args:
            movie (Movie): 待检查的电影对象。
            context(PipelineContext): 用于占位。
        Returns:
            bool: 如果抓取阶段未成功完成则返回True。
        """
        return movie.metadata is None

    @staticmethod
    def _get_translation_with_caching(
        context: PipelineContext,
        entity_type: MetadataType,
        original_text: str,
        translation_func,
    ) -> Optional[str]:
        """
        【重构核心】通用的缓存与翻译逻辑。
        1. 检查缓存。
        2. 若缓存未命中，则执行传入的 translation_func。
        3. 成功后更新缓存。
        """
        # 1. 检查缓存
        cached_record = context.get_entity(entity_type, original_text)
        if cached_record:
            logger.info(
                f"Cache hit for {entity_type.name} '{original_text}': '{cached_record}'"
            )
            return cached_record

        # 2. 调用翻译器 (通过传入的函数)
        logger.info(f"Attempt to translate '{entity_type.name}': '{original_text}'")
        translate_result = translation_func()

        # 3. 返回
        if translate_result and translate_result.success:
            translated_text = translate_result.content
            logger.info(
                f"Translated {entity_type.name} '{original_text}' to '{translated_text}'"
            )
            return translated_text

        logger.warning(f"Translation failed for {entity_type.name} '{original_text}'")
        return None

    @observe
    def _translate_generic_field(
        self,
        context: PipelineContext,
        original_text: str,
        metadata_type: MetadataType,
        task_type: TaskType,
    ) -> Optional[str]:
        """翻译通用的、无额外上下文的元数据字段。"""
        langfuse = get_client()
        langfuse.update_current_trace(
            session_id=context.langfuse_session_id,
            tags=["scrape", "metadata", metadata_type.name.lower(), "translate"],
        )
        return self._get_translation_with_caching(
            context=context,
            entity_type=metadata_type,
            original_text=original_text,
            translation_func=lambda: context.translator.translate_generic_metadata(
                task_type, original_text
            ),
        )

    @observe
    def _translate_title(
        self, context: PipelineContext, metadata: Metadata
    ) -> Optional[str]:
        """翻译标题（需要演员上下文）。"""
        langfuse = get_client()
        langfuse.update_current_trace(
            session_id=context.langfuse_session_id,
            tags=["scrape", "metadata", "title", "translate"],
        )
        if not metadata.title or not metadata.title.original:
            return None

        return self._get_translation_with_caching(
            context=context,
            entity_type=MetadataType.TITLE,
            original_text=metadata.title.original,
            translation_func=lambda: context.translator.translate_title(
                text=metadata.title.original,
                actors=[
                    name.to_serial_dict()
                    for a in metadata.actors
                    for name in a.all_names
                ],
                actress=[
                    name.to_serial_dict()
                    for a in metadata.actresses
                    for name in a.all_names
                ],
            ),
        )

    @observe
    def _translate_synopsis(
        self, context: PipelineContext, metadata: Metadata
    ) -> Optional[str]:
        """翻译简介（需要演员上下文）。"""
        langfuse = get_client()
        langfuse.update_current_trace(
            session_id=context.langfuse_session_id,
            tags=["scrape", "metadata", "synopsis", "translate"],
        )
        if not metadata.synopsis or not metadata.synopsis.original:
            return None

        return self._get_translation_with_caching(
            context=context,
            entity_type=MetadataType.SYNOPSIS,
            original_text=metadata.synopsis.original,
            translation_func=lambda: context.translator.translate_synopsis(
                text=metadata.synopsis.original,
                actors=[
                    name.to_serial_dict()
                    for a in metadata.actors
                    for name in a.all_names
                ],
                actress=[
                    name.to_serial_dict()
                    for a in metadata.actresses
                    for name in a.all_names
                ],
            ),
        )

    def _translate_data_structure(
        self,
        data,
        context: PipelineContext,
        metadata_type: MetadataType,
        task_type: TaskType,
    ) -> Any:
        if isinstance(data, BilingualText) and not data.translated:
            logger.info(f"Processing BilingualText value {data}...")
            data.translated = self._translate_generic_field(
                context, data.original, metadata_type, task_type
            )
            return data
        elif isinstance(data, BilingualList) and (
            not data.translated or len(data.translated) != len(data.original)
        ):
            logger.info(f"Processing bilingual list object...")
            translated_list = []
            for item in data.original:
                logger.info(f"Processing item {item}...")
                translated = self._translate_generic_field(
                    context, item, metadata_type, task_type
                )
                translated_list.append(translated if translated else item)
            data.translated = translated_list
            return data
        elif isinstance(data, list):
            return [
                self._translate_data_structure(item, context, metadata_type, task_type)
                for item in data
            ]
        elif isinstance(data, dict):
            return {
                key: self._translate_data_structure(
                    item, context, metadata_type, task_type
                )
                for key, item in data.items()
            }
        elif isinstance(data, tuple):
            return (
                self._translate_data_structure(item, context, metadata_type, task_type)
                for item in data
            )
        elif isinstance(data, set):
            return {
                self._translate_data_structure(item, context, metadata_type, task_type)
                for item in data
            }
        elif isinstance(data, (str, int, float, bool)):
            return data
        else:
            # Check if data is a dataclass before calling fields()
            if is_dataclass(data):
                for field in fields(data):
                    value = getattr(data, field.name)
                    setattr(
                        data,
                        field.name,
                        self._translate_data_structure(
                            value, context, metadata_type, task_type
                        ),
                    )
                return data
            else:
                # If it's not a dataclass, just return the data as-is
                return data

    @observe
    def execute(self, movie: Movie, context: PipelineContext):
        """执行影片信息抓取处理。

        Args:
            movie (Movie): 待处理的电影对象。
            context (PipelineContext): 流水线执行上下文。
        """
        langfuse = get_client()
        langfuse.update_current_trace(
            session_id=context.langfuse_session_id,
            tags=["scrape", "metadata", movie.code],
        )

        metadata = context.get_metadata(movie.code)
        movie.metadata = metadata
        if movie.metadata is None:
            logger.info(f"Starting metadata scraping for {movie.code}...")
            # 抓取逻辑实现
            for server in self.web_servers:
                try:
                    logger.info(f"Trying to scrape {movie.code} from {server.url}...")
                    metadata: Metadata = server.fetch_metadata(movie.code)
                    movie.metadata = metadata
                    break
                except Exception as e:
                    logger.warning(
                        f"server {server.url} failed to get metadata for {movie.code}: {e}"
                    )
            if movie.metadata is None:
                logger.error(
                    f"All web services failed to get metadata for {movie.code}"
                )
                return
        # 定义字段到枚举的映射
        field_map = {
            "director": (MetadataType.DIRECTOR, TaskType.METADATA_DIRECTOR),
            "studio": (MetadataType.STUDIO, TaskType.METADATA_STUDIO),
            "categories": (MetadataType.CATEGORY, TaskType.METADATA_CATEGORY),
            "actors": (MetadataType.ACTOR, TaskType.METADATA_ACTOR),
            "actresses": (
                MetadataType.ACTOR,
                TaskType.METADATA_ACTOR,
            ),  # 注意：女演员也用 METADATA_ACTOR 任务
        }

        # 优先翻译通用字段，为标题和简介提供上下文
        for field in fields(movie.metadata):
            if field.name not in field_map:
                continue
            metadata_type, task_type = field_map[field.name]
            value = getattr(movie.metadata, field.name)
            logger.info(f'Check generic field: "{field.name}"...')
            self._translate_data_structure(value, context, metadata_type, task_type)

        # 最后翻译需要上下文的字段
        logger.info("Processing field title...")
        if movie.metadata.title and not movie.metadata.title.translated:
            movie.metadata.title.translated = self._translate_title(
                context, movie.metadata
            )
        elif not movie.metadata.title:
            logger.warning(f"Field title is empty.")
        else:
            logger.info(f"Cache hit field title: {movie.metadata.title}.")

        logger.info("Processing field synopsis...")
        if movie.metadata.synopsis and not movie.metadata.synopsis.translated:
            movie.metadata.synopsis.translated = self._translate_synopsis(
                context, movie.metadata
            )
        elif not movie.metadata.synopsis:
            logger.info(f"Field synopsis is empty.")
        else:
            logger.info(f"Cache hit field synopsis: {movie.metadata.synopsis}.")

        logger.info(f"Completed metadata scraping and translation for {movie.code}")
