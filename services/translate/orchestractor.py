from typing import Dict, List
from models.tasktype import TaskType
from models.query_result import ChatResult, ProcessResult
from services.translate.provider import Provider
from services.translate.strategies import TranslateStrategy, MetaDataTranslateStrategy, NoSliceSubtitleStrategy, \
    SliceSubtitleStrategy
from utils.config import Config

class TranslateOrchestrator:
    """用来协调翻译服务的类"""
    def __init__(self, providers: Dict[TaskType, List[Provider]]):
        self.providers = providers

    def translate_metadata(self, task_type: TaskType, text: str) -> ChatResult:
        providers = self.providers[task_type]
        strategy = MetaDataTranslateStrategy()

        for provider in providers:
            result = strategy.process(task_type, provider, text)
            if result.success:
                return result
        return ChatResult(success=False, attempt_count=0, time_taken=0, content=None)

    @staticmethod
    def _select_strategy_for_subtitle(task_type: TaskType, provider: Provider) -> TranslateStrategy:
        if provider.model in Config.get_config("SLICE_MODELS", set()):
            return SliceSubtitleStrategy()
        else:
            return SliceSubtitleStrategy(slice_size=550)

    def correct_or_translate_subtitle(self, task_type: TaskType, metadata: Dict, text: str) -> ProcessResult:
        providers = self.providers[task_type]

        for provider in providers:
            strategy = self._select_strategy_for_subtitle(task_type, provider)
            result = strategy.process(task_type, provider, metadata, text)
            if result.success:
                return result
        return ProcessResult(task_type=task_type, attempt_count=0, time_taken=0, content=None, success=False)
