from typing import Dict, List, Optional

from domain.movie import Term
from models.enums import TaskType
from models.results import ProcessResult
from models.context import TranslateContext
from services.translation.provider import Provider
from services.translation.strategies import TranslateStrategy, MetaDataTranslateStrategy, SliceSubtitleStrategy

class TranslateOrchestrator:
    """
    用来协调翻译服务的类.
    作为外观，为上层服务提供简介接口
    内部通过适配器方法，使用统一的上下文对象处理服务
    """
    def __init__(self, provider_map: Dict[TaskType, List[Provider]]):
        self.provider_map = provider_map

    def correct_subtitle(self, text: str, metadata: dict, terms: List[Term]|None=None) -> ProcessResult:
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
            terms=terms
        )
        return self._process_task(context)

    def translate_subtitle(self, text: str, metadata: dict, terms: List[Term]|None=None) -> ProcessResult:
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

    def translate_metadata(self, task_type: TaskType, text: str) -> ProcessResult:
        """翻译元数据的专用接口。

        Args:
            task_type (TaskType): 元数据任务类型（导演、演员、分类等）。
            text (str): 待翻译的文本。

        Returns:
            ProcessResult: 带有翻译任务结果的数据类。
        """
        context = TranslateContext(
            task_type=task_type,
            text_to_process=text
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
        providers = self.provider_map.get(context.task_type)
        if not providers:
            return ProcessResult(task_type=context.task_type, success=False, content=None, attempt_count=0, time_taken=0)

        for provider in providers:
            strategy = self._select_strategy(provider, context.task_type)
            result = strategy.process(provider, context)

            if result and result.success:
                return result
        return ProcessResult(task_type=context.task_type, success=False, content=None, attempt_count=0, time_taken=0)

    @staticmethod
    def _select_strategy(provider: Provider, task_type: TaskType) -> TranslateStrategy:
        """选择合适的翻译策略。

        Args:
            provider (Provider): 服务提供者。
            task_type (TaskType): 任务类型。

        Returns:
            TranslateStrategy: 选中的翻译策略实例。
        """
        if task_type == TaskType.CORRECT_SUBTITLE:
            return SliceSubtitleStrategy(slice_size=500)
        elif task_type == TaskType.TRANSLATE_SUBTITLE:
            return SliceSubtitleStrategy(slice_size=550)
        else:
            return MetaDataTranslateStrategy()
