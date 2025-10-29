"""流水线执行上下文模块。

定义流水线执行过程中 Stage 所需的共享资源和操作接口。
"""

import os
from dataclasses import dataclass
from typing import Optional

from domain.movie import Movie, Video, Metadata
from models.enums import MetadataType
from services.pipeline.manifest import Manifest
from services.translation.orchestrator import TranslateOrchestrator


@dataclass
class PipelineContext:
    """流水线执行上下文。

    封装流水线执行过程中各个 Stage 需要访问的共享资源。
    通过上下文对象模式，实现：
    1. Manifest 只由 Pipeline 管理，避免多层级持有
    2. Stage 通过统一接口访问共享资源
    3. 保持 Stage 的功能完整性（如写入数据库）

    Attributes:
        movie_code(str): 影片代码
        manifest (Manifest): 清单文件管理对象，唯一实例
        output_dir (str): 副产品输出路径目录，唯一实例
        translator (TranslateOrchestrator): 所以翻译活动要用到的翻译编排器
        langfuse_session_id (str|None): Langfuse 会话 ID，用于跟踪翻译请求
    """

    manifest: Manifest
    translator: TranslateOrchestrator
    movie_code: str = ""
    langfuse_session_id: str | None = None
    output_dir: str = os.path.join(os.getcwd(), "output")

    # ========== Movie 相关操作 ==========

    def register_movie(self, movie: Movie) -> None:
        """注册 Movie 到清单中。

        Args:
            movie (Movie): 待注册的电影对象
        """
        self.manifest.register_movie(movie)

    def get_metadata(self, movie_code: str) -> Optional[Metadata]:
        return self.manifest.get_metadata(movie_code)

    def update_movie(self, movie: Movie) -> None:
        """更新 Movie 的元数据信息到清单。

        Args:
            movie (Movie): 待更新的电影对象
        """
        self.manifest.update_movie(movie)

    # ========== Video 相关操作 ==========
    def update_video_location(self, video: Video, filename, absolute_path) -> None:
        """更新 Video 的文件路径到清单。

        Args:
            video (Video): 待更新的视频对象
            filename(str): 视频文件名
            absolute_path(str): 视频文件绝对路径
        """
        self.manifest.update_video_location(video, filename, absolute_path)

    def set_video_status(self, video: Video) -> None:
        """从清单中读取并设置 Video 的状态。

        Args:
            video (Video): 待设置状态的视频对象
        """
        self.manifest.set_video_status(video)

    def update_video(self, video: Video) -> None:
        """更新 Video 的处理状态到清单。

        Args:
            video (Video): 待更新的视频对象
        """
        self.manifest.update_video(video)

    # ========== 元数据实体操作 ==========

    def get_entity(
            self, entity_type: MetadataType, original_name: str
    ) -> Optional[str]:
        """从清单中查询元数据实体的翻译。

        支持查询：导演、演员、类别等元数据的已翻译版本。
        用于缓存查询，避免重复翻译。

        Args:
            entity_type (MetadataType): 实体类型
            original_name (str): 日文原文

        Returns:
            Optional[str]: 中文翻译，如果不存在则返回 None
        """
        return self.manifest.get_entity(entity_type, original_name)

    def update_entity(
            self, entity_type: MetadataType, original_name: str, translated_name: str
    ) -> None:
        """更新元数据实体的翻译到清单。

        将新翻译的元数据（导演、演员、类别等）保存到数据库。
        用于缓存新翻译结果，供后续查询使用。

        Args:
            entity_type (MetadataType): 实体类型
            original_name (str): 日文原文
            translated_name (str): 中文翻译
        """
        self.manifest.update_entity(entity_type, original_name, translated_name)

    # ========== 其他操作 ==========

    def export_to_json(self, path: str) -> None:
        """导出清单内容为 JSON 格式。

        Args:
            path (str): 导出文件路径
        """
        self.manifest.to_json(path)
