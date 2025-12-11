from dataclasses import dataclass
from typing import Dict, List, Optional

from aurora.domain.context import TranslateContext
from aurora.domain.enums import TaskType
from aurora.domain.movie import Term
from aurora.domain.results import ProcessResult
from aurora.services.translation.provider import Provider
from aurora.services.translation.strategies import (
    TranslateStrategy,
    SliceSubtitleStrategy,
    SimpleMetaDataStrategy,
    ContextualMetaDataStrategy,
    NoSliceSubtitleStrategy,
)
from langfuse import observe
from yaml import safe_load


@dataclass
class TaskConfig:
    """任务配置数据类"""

    providers: List[Provider]
    stream: Optional[bool] = None  # 如果为 None，则使用全局 streaming_models 判断
    temperature: Optional[float] = None  # 如果为 None, 则不传参
    strategy: Optional[Dict] = None  # 策略配置（如 slice、size 等）


class TranslateOrchestrator:
    """
    用来协调翻译服务的类.
    作为外观，为上层服务提供简介接口
    内部通过适配器方法，使用统一的上下文对象处理服务
    """

    def __init__(
        self,
        task_configs: Dict[TaskType, TaskConfig],
        streaming_models: List[str] = None,
    ):
        self.task_configs = task_configs
        self.streaming_models = streaming_models or []

    @classmethod
    def from_config_yaml(cls, file_path: str):
        """从 YAML 配置文件创建 TranslateOrchestrator 实例。

        Args:
            file_path (str): YAML 配置文件路径

        Returns:
            TranslateOrchestrator: 翻译编排器实例
        """
        with open(file_path, "r", encoding="utf-8") as f:
            config: Dict = safe_load(f)
            return cls.from_config(config["translate_orchestrator"])

    @classmethod
    def from_config(cls, config: Dict):
        """从配置字典创建 TranslateOrchestrator 实例。

        Args:
            config (Dict): 翻译编排器配置字典

        Returns:
            TranslateOrchestrator: 翻译编排器实例
        """
        # 任务名称到 TaskType 的映射
        task_name_to_type: Dict[str, TaskType] = {
            "director": TaskType.METADATA_DIRECTOR,
            "actor": TaskType.METADATA_ACTOR,
            "category": TaskType.METADATA_CATEGORY,
            "studio": TaskType.METADATA_STUDIO,
            "title": TaskType.METADATA_TITLE,
            "synopsis": TaskType.METADATA_SYNOPSIS,
            "correct": TaskType.CORRECT_SUBTITLE,
            "subtitle": TaskType.TRANSLATE_SUBTITLE,
        }

        task_configs: Dict[TaskType, TaskConfig] = {}
        tasks_config = config.get("config", {})

        # 遍历配置中的每个任务
        for task_name, task_data in tasks_config.items():
            task_type = task_name_to_type.get(task_name)
            if not task_type:
                continue

            # 创建 Provider 列表
            providers = []
            for provider_config in task_data.get("providers", []):
                provider = Provider.from_config(provider_config)
                if provider:
                    providers.append(provider)

            # 读取 stream 配置（可选）
            stream = task_data.get("stream")

            # 读取 temperature 配置(可选)
            temperature = task_data.get("temperature", 1.0)

            # 读取 strategy 配置（可选）
            strategy = task_data.get("strategy")

            # 创建 TaskConfig
            task_configs[task_type] = TaskConfig(
                providers=providers,
                stream=stream,
                temperature=temperature,
                strategy=strategy,
            )

        # 读取需要流式请求的模型列表
        streaming_models = config.get("streaming_models", [])

        return cls(task_configs, streaming_models)

    @observe
    def correct_subtitle(
        self, text: str, metadata: dict, terms: List[Term] | None = None
    ) -> ProcessResult:
        """
        校正字幕的专用接口
        这个方法实际上只是一个适配器，将简单参数转换为内部上下文
        Args:
            text(str): 待校正的字幕文本
            metadata(dict)： 关于字幕的元数据
            terms(Optional[List[Term]]): 术语库
        Returns:
            ProcessResult: 带有校正任务结果的数据类
        """
        context = TranslateContext(
            task_type=TaskType.CORRECT_SUBTITLE,
            metadata=metadata,
            text_to_process=text,
            terms=terms,
        )
        return self._process_task(context)

    @observe
    def translate_subtitle(
        self, text: str, metadata: dict, terms: List[Term] | None = None
    ) -> ProcessResult:
        """翻译字幕的专用接口。

        这个方法实际上只是一个适配器，将简单参数转换为内部上下文。

        Args:
            text (str): 待翻译的字幕文本。
            metadata (dict): 关于字幕的元数据。
            terms(Optional[List[Term]]): 关于字幕的术语库
        Returns:
            ProcessResult: 带有翻译任务结果的数据类。
        """
        context = TranslateContext(
            task_type=TaskType.TRANSLATE_SUBTITLE,
            metadata=metadata,
            terms=terms,
            text_to_process=text,
        )
        return self._process_task(context)

    @observe
    def translate_title(
        self,
        text: str,
        actors: List[Dict] | None = None,
        actress: List[Dict] | None = None,
    ) -> ProcessResult:
        """翻译标题的专用接口。

        Args:
            text (str): 待翻译的文本。
            actors (Optional[List[Dict]]): 相关演员列表。
            actress (Optional[List[Dict]]): 相关女优列表。

        Returns:
            ProcessResult: 带有翻译任务结果的数据类。
        """
        context = TranslateContext(
            task_type=TaskType.METADATA_TITLE,
            text_to_process=text,
            actors=actors,
            actress=actress,
        )
        return self._process_task(context)

    @observe
    def translate_synopsis(
        self,
        text: str,
        actors: List[Dict] | None = None,
        actress: List[Dict] | None = None,
    ) -> ProcessResult:
        """翻译简介的专用接口。

        Args:
            text (str): 待翻译的文本。
            actors (Optional[List[Dict]]): 相关演员列表。
            actress (Optional[List[Dict]]): 相关女优列表。

        Returns:
            ProcessResult: 带有翻译任务结果的数据类。
        """
        context = TranslateContext(
            task_type=TaskType.METADATA_SYNOPSIS,
            text_to_process=text,
            actors=actors,
            actress=actress,
        )
        return self._process_task(context)

    @observe
    def translate_generic_metadata(
        self, task_type: TaskType, text: str
    ) -> ProcessResult:
        """翻译元数据的专用接口。

        Args:
            task_type (TaskType): 元数据任务类型（导演、演员、分类、片商等）。
            text (str): 待翻译的文本。

        Returns:
            ProcessResult: 带有翻译任务结果的数据类。
        """
        context = TranslateContext(
            task_type=task_type,
            text_to_process=text,
        )
        return self._process_task(context)

    def _process_task(self, context: TranslateContext) -> ProcessResult:
        """处理任务的内部方法。

        根据任务类型选择合适的Provider和Strategy进行处理。

        Args:
            context (TranslateContext): 任务上下文。

        Returns:
            ProcessResult: 处理结果。
        """
        task_config = self.task_configs.get(context.task_type)
        if not task_config or not task_config.providers:
            return ProcessResult(
                task_type=context.task_type,
                success=False,
                content=None,
                attempt_count=0,
                time_taken=0,
            )

        for provider in task_config.providers:
            strategy = self._select_strategy(provider, context.task_type, task_config)
            result = strategy.process(provider, context)

            if result and result.success:
                return result
        return ProcessResult(
            task_type=context.task_type,
            success=False,
            content=None,
            attempt_count=0,
            time_taken=0,
        )

    def _select_strategy(
        self, provider: Provider, task_type: TaskType, task_config: TaskConfig
    ) -> TranslateStrategy:
        """选择合适的翻译策略。

        Args:
            provider (Provider): 服务提供者。
            task_type (TaskType): 任务类型。
            task_config (TaskConfig): 任务配置。

        Returns:
            TranslateStrategy: 选中的翻译策略实例。
        """
        # 判断是否使用流式请求
        # 优先级：task_config.stream > streaming_models 列表
        if task_config.stream is not None:
            use_stream = task_config.stream
        else:
            use_stream = provider.model in self.streaming_models
        use_temperature = task_config.temperature

        # 根据任务类型选择策略
        if task_type == TaskType.CORRECT_SUBTITLE:
            # 读取策略配置
            strategy_config = task_config.strategy or {}
            slice_enabled = strategy_config.get("slice", True)
            slice_size = strategy_config.get("size", 500)
            if slice_enabled:
                return SliceSubtitleStrategy(
                    slice_size=slice_size,
                    stream=use_stream,
                    temperature=use_temperature,
                )
            else:
                return NoSliceSubtitleStrategy(stream=use_stream)

        elif task_type == TaskType.TRANSLATE_SUBTITLE:
            # 读取策略配置
            strategy_config = task_config.strategy or {}
            slice_enabled = strategy_config.get("slice", True)
            slice_size = strategy_config.get("size", 550)
            if slice_enabled:
                return SliceSubtitleStrategy(
                    slice_size=slice_size,
                    stream=use_stream,
                    temperature=use_temperature,
                )
            else:
                return NoSliceSubtitleStrategy(stream=use_stream)

        elif task_type in {
            TaskType.METADATA_DIRECTOR,
            TaskType.METADATA_ACTOR,
            TaskType.METADATA_CATEGORY,
            TaskType.METADATA_STUDIO,
        }:
            # 简单元数据策略（不需要上下文）
            return SimpleMetaDataStrategy(
                stream=use_stream, temperature=use_temperature
            )
        else:
            # 上下文元数据策略（需要上下文，如 title、synopsis）
            return ContextualMetaDataStrategy(
                stream=use_stream, temperature=use_temperature
            )
