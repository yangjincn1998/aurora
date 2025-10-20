from dataclasses import fields
from typing import List, Optional

from base import MoviePipelineStage
from context import PipelineContext
from domain.movie import Movie, Metadata
from domain.subtitle import BilingualText, BilingualList
from models.enums import TaskType, MetadataType
from services.pipeline.manifest import SQLiteManifest
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

    def should_execute(self, movie):
        """判断是否应该执行抓取阶段。

        Args:
            movie (Movie): 待检查的电影对象。

        Returns:
            bool: 如果抓取阶段未成功完成则返回True。
        """
        return movie.metadata is None

    def _translate_and_cache(self, original_text: str, field_name: str) -> Optional[str]:
        """
        【核心重构】翻译单个文本并处理缓存。
        此方法是所有翻译逻辑的中心，避免了代码重复。

        1. 首先在 manifest (缓存) 中查找。
        2. 如果未找到，调用翻译器进行翻译。
        3. 如果翻译成功，将新结果更新到 manifest 中。
        4. 返回翻译结果或 None。
        """
        task_map = {
            "title": TaskType.METADATA_TITLE,
            "synopsis": TaskType.METADATA_SYNOPSIS,
            "director": TaskType.METADATA_DIRECTOR,
            "actors": TaskType.METADATA_ACTOR,
            "actresses": TaskType.METADATA_ACTOR,
            "categories": TaskType.METADATA_CATEGORY,
            "studio": TaskType.METADATA_STUDIO,
        }
        metadata_map = {
            "title": MetadataType.TITLE,
            "synopsis": MetadataType.SYNOPSIS,
            "director": MetadataType.DIRECTOR,
            "actors": MetadataType.ACTOR,
            "actresses": MetadataType.ACTRESS,
            "categories": MetadataType.CATEGORY,
            "studio": MetadataType.STUDIO,
        }
        entity_type = metadata_map.get(field_name)
        task_type = task_map.get(field_name)

        # 1. 检查缓存 - 通过 context 访问 manifest
        record = context.get_entity(entity_type, original_text)
        if record:
            logger.info(f"Cache hit for {field_name} '{original_text}': '{record}'")
            return record

        # 2. 调用翻译器
        translate_result = context.translator.translate_metadata(task_type, original_text)

        # 3. 更新缓存并返回 - 通过 context 写入 manifest
        if translate_result.success:
            logger.info(f"Translated {field_name} '{original_text}' to '{translate_result.content}'")
            translated_text = translate_result.content
            context.update_entity(entity_type, original_text, translated_text)
            return translated_text
        return None

    def execute(self, movie: Movie, context: PipelineContext):
        """执行影片信息抓取处理。

        Args:
            movie (Movie): 待处理的电影对象。
            context (PipelineContext): 流水线执行上下文。
        """
        metadata = context.get_metadata(movie.code)
        movie.metadata = metadata
        if movie.metadata is None or not movie.metadata.title:
            logger.info(f"Starting metadata scraping for {movie.code}...")
            # 抓取逻辑实现
            for server in self.web_servers:
                try:
                    logger.info(f"Trying to scrape {movie.code} from {server.url}...")
                    metadata: Metadata = server.get_metadata(movie.code)
                    movie.metadata = metadata
                    context.update_movie(movie)
                    break
                except Exception as e:
                    logger.warning(f"server {server.url} failed to get metadata for {movie.code}: {e}")
            if movie.metadata is None:
                logger.error(f"All web services failed to get metadata for {movie.code}")
                return

        for field in fields(movie.metadata):
            value = getattr(movie.metadata, field.name)
            logger.info(f"Processing field {field.name}...")
            if isinstance(value, BilingualText) and not value.translated:
                logger.info(f"Processing {value.original}...")
                value.translated = self._translate_and_cache(value.original, field.name)
                logger.info(f"Processed as {value.translated}...")
            elif isinstance(value, BilingualList) and (
                    not value.translated or len(value.translated) != len(value.original)):
                translated_list = []
                for original_item in value.original:
                    logger.info(f"Processing item {original_item}...")
                    translated_item = self._translate_and_cache(original_item, field.name)
                    logger.info(f"Translated as {translated_item}...")
                    translated_list.append(translated_item if translated_item else original_item)
                value.translated = translated_list
            elif isinstance(value, list) and len(value) > 0 and isinstance(value[0], BilingualText):
                for bt in value:
                    if not bt.translated:
                        logger.info(f"Processing item {bt.original}...")
                        bt.translated = self._translate_and_cache(bt.original, field.name)
                        logger.info(f"Processed as {bt.translated}...")
            else:
                continue
        logger.info(f"Completed metadata scraping and translation for {movie.code}")
        return


if __name__ == "__main__":
    import dotenv

    dotenv.load_dotenv()
    translator = TranslateOrchestrator.from_config_yaml("config.yml")
    context = PipelineContext(
        translator=translator,
        manifest=SQLiteManifest(),
    )
    movie = Movie(code="MGMQ-104")
    context.register_movie(movie)
    scraper = ScrapeStage(web_servers=[JavBusWebService()])
    scraper.execute(movie, context)
    context.update_movie(movie)
