"""流水线执行上下文模块。

定义流水线执行过程中 Stage 所需的共享资源和操作接口。
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from contextlib import contextmanager

from domain.movie import Movie, Video, Metadata
from models.enums import MetadataType
from services.pipeline.database_manager import DatabaseManager
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

    database_manager: DatabaseManager
    translator: TranslateOrchestrator
    movie_code: str = ""
    langfuse_session_id: str | None = None
    output_dir: str = os.path.join(os.getcwd(), "output")
    _current_cursor: Optional = field(default=None, init=False)
    _current_connection: Optional = field(default=None, init=False)

    # ========== 数据库连接管理 ==========

    def begin_transaction(self):
        """开始事务，返回cursor用于整个影片处理过程"""
        if self._current_cursor is not None:
            raise RuntimeError("Transaction already in progress")

        # 创建一个新的连接和cursor，保持连接打开
        import sqlite3

        self._current_connection = sqlite3.connect(self.database_manager.db_path)
        self._current_cursor = self._current_connection.cursor()
        return self._current_cursor

    def commit_transaction(self):
        """提交事务"""
        if self._current_connection is not None:
            try:
                self._current_connection.commit()
            except Exception as e:
                print(f"提交事务时出错: {e}")
        self._cleanup_transaction()

    def rollback_transaction(self):
        """回滚事务"""
        if self._current_connection is not None:
            try:
                self._current_connection.rollback()
            except Exception as e:
                print(f"回滚事务时出错: {e}")
        self._cleanup_transaction()

    def _cleanup_transaction(self):
        """清理事务资源"""
        if self._current_connection is not None:
            try:
                self._current_connection.close()
            except:
                pass
        self._current_connection = None
        self._current_cursor = None

    @contextmanager
    def get_cursor(self, commit: bool = False):
        """获取数据库游标，用于原子操作。

        Args:
            commit (bool): 是否在退出时自动提交事务

        Yields:
            sqlite3.Cursor: 数据库游标
        """
        if self._current_cursor is not None:
            # 如果已有活跃的cursor，直接使用
            yield self._current_cursor
            if commit:
                # 对于事务中的cursor，不自动commit
                pass
        else:
            # 创建新的cursor
            with self.database_manager.get_cursor(commit=commit) as cursor:
                yield cursor

    # ========== Movie 相关操作 ==========

    def register_movie(self, movie: Movie) -> None:
        """注册 Movie 到清单中。

        Args:
            movie (Movie): 待注册的电影对象
        """
        with self.get_cursor() as cursor:
            self.database_manager.register_movie(movie, cursor)

    def get_metadata(self, movie_code: str) -> Optional[Metadata]:
        with self.get_cursor() as cursor:
            return self.database_manager.get_metadata(movie_code, cursor)

    def update_movie(self, movie: Movie) -> None:
        """更新 Movie 的元数据信息到清单。

        Args:
            movie (Movie): 待更新的电影对象
        """
        with self.get_cursor() as cursor:
            self.database_manager.update_movie(movie, cursor)

    # ========== Video 相关操作 ==========
    def update_video_location(self, video: Video, filename, absolute_path) -> None:
        """更新 Video 的文件路径到清单。

        Args:
            video (Video): 待更新的视频对象
            filename(str): 视频文件名
            absolute_path(str): 视频文件绝对路径
        """
        with self.get_cursor() as cursor:
            self.database_manager.update_video_location(
                video, filename, absolute_path, cursor
            )

    def set_video_status(self, video: Video) -> None:
        """从清单中读取并设置 Video 的状态。

        Args:
            video (Video): 待设置状态的视频对象
        """
        with self.get_cursor() as cursor:
            self.database_manager.set_video_status(video, cursor)

    def update_video(self, video: Video) -> None:
        """更新 Video 的处理状态到清单。

        Args:
            video (Video): 待更新的视频对象
        """
        with self.get_cursor() as cursor:
            self.database_manager.update_video(video, cursor)

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
        with self.get_cursor() as cursor:
            return self.database_manager.get_entity(entity_type, original_name, cursor)

    # ========== 术语相关操作 ==========

    def update_terms(self, movie: Movie) -> None:
        """更新影片的术语到数据库。

        Args:
            movie (Movie): 包含术语的电影对象
        """
        with self.get_cursor() as cursor:
            self.database_manager.update_terms(movie, cursor)
