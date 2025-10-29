import time
from abc import ABC, abstractmethod
from typing import Optional, Tuple

from langfuse import observe

from data_structures.subtitle_node import SubtitleBlock
from models.context import TranslateContext
from models.enums import TaskType
from models.results import ProcessResult
from services.translation.prompts import DIRECTOR_SYSTEM_PROMPT, ACTOR_SYSTEM_PROMPT, CATEGORY_SYSTEM_PROMPT, \
    director_examples, actor_examples, category_examples, studio_examples, synopsis_examples, title_examples, \
    CORRECT_SUBTITLE_SYSTEM_PROMPT, CORRECT_SUBTITLE_USER_QUERY, TRANSLATE_SUBTITLE_PROMPT, \
    TRANSLATE_SUBTITLE_USER_QUERY, STUDIO_SYSTEM_PROMPT, SYNOPSIS_SYSTEM_PROMPT, TITLE_SYSTEM_PROMPT, \
    SYNOPSIS_USER_QUERY, \
    TITLE_USER_QUERY
from services.translation.provider import Provider
from utils.logger import get_logger
from utils.prompt_utils import build_message_with_uuid, build_message_with_replacements, build_subtitle_messages
from utils.subtitle_utils import update_translate_context, adaptive_slice_subtitle, \
    aggregate_successful_results

logger = get_logger("av_translator")

class TranslateStrategy(ABC):
    """
    翻译策略的高层接口
    所有翻译策略都需要实现 process 方法
    process 方法必须包含 provider 和 text 参数，其他参数可以不同
    Attribute:
        stream(bool): 是否启用流式输入。
        temperature(float): 模型调用的温度。
    """
    def __init__(self, stream:bool=False, temperature:float=1.0):
        self.stream = stream
        self.temperature = temperature

    @abstractmethod
    def process(self, provider: Provider, context: TranslateContext) -> ProcessResult:
        """子类需要实现此方法，但签名可以不同"""
        pass


    @staticmethod
    def _check_provider_available(provider, task_type: TaskType) -> Optional[ProcessResult]:
        """
        检查 Provider 是否可用（熔断检查）
        如果 Provider 已熔断，返回失败的 ProcessResult
        否则返回 None，表示可以继续处理

        这是所有 Strategy 子类的通用逻辑，用于快速失败
        """
        if hasattr(provider, 'available') and not provider.available:
            logger.warning(f"Provider {provider.model} is unavailable (circuit breaker triggered), failing fast")
            return ProcessResult(
                task_type=task_type,
                attempt_count=0,
                time_taken=0,
                content=None,
                success=False
            )
        return None

class MetaDataTranslateStrategy(TranslateStrategy):
    """元数据翻译策略。

    用于翻译导演、演员、分类等元数据信息。

    Attributes:
        system_prompts (dict): 各任务类型对应的系统提示词。
        examples (dict): 各任务类型对应的示例。
    """
    def __init__(self, stream, temperature):
        """初始化元数据翻译策略。"""
        super().__init__(stream, temperature)
        self.system_prompts = {
            TaskType.METADATA_DIRECTOR: DIRECTOR_SYSTEM_PROMPT,
            TaskType.METADATA_ACTOR: ACTOR_SYSTEM_PROMPT,
            TaskType.METADATA_CATEGORY: CATEGORY_SYSTEM_PROMPT,
            TaskType.METADATA_TITLE: TITLE_SYSTEM_PROMPT,
            TaskType.METADATA_SYNOPSIS: SYNOPSIS_SYSTEM_PROMPT,
            TaskType.METADATA_STUDIO: STUDIO_SYSTEM_PROMPT
        }
        self.examples = {
            TaskType.METADATA_DIRECTOR: director_examples,
            TaskType.METADATA_ACTOR: actor_examples,
            TaskType.METADATA_CATEGORY: category_examples,
            TaskType.METADATA_TITLE: title_examples,
            TaskType.METADATA_SYNOPSIS: synopsis_examples,
            TaskType.METADATA_STUDIO: studio_examples
        }
        self.query_templates = {
            TaskType.METADATA_SYNOPSIS: SYNOPSIS_USER_QUERY,
            TaskType.METADATA_TITLE: TITLE_USER_QUERY,
        }

    def process(self, provider: Provider, context: TranslateContext) -> ProcessResult:
        raise NotImplementedError()


class SimpleMetaDataStrategy(MetaDataTranslateStrategy):
    """带UUID前缀的元数据翻译策略。不需要其他额外信息，用于片商、演员、导演和类别等简单元数据翻译。"""
    
    @observe
    def process(self, provider: Provider, context: TranslateContext) -> ProcessResult:
        """处理元数据翻译。

        Args:
            provider (Provider): 服务提供者。
            context (TranslateContext): 处理上下文。

        Returns:
            ProcessResult: 翻译结果。
        """
        # 熔断检查：如果 Provider 已熔断，快速失败
        circuit_breaker_result = self._check_provider_available(provider, context.task_type)
        if circuit_breaker_result is not None:
            return circuit_breaker_result

        # 调用 Provider
        system_prompt = self.system_prompts[context.task_type]
        examples = self.examples.get(context.task_type, {})
        messages = build_message_with_uuid(system_prompt, examples, context.text_to_process)
        chat_result = provider.chat(messages, stream=self.stream, temperature=self.temperature)

        # 将 ChatResult 转换为 ProcessResult
        return ProcessResult(
            task_type=context.task_type,
            attempt_count=chat_result.attempt_count,
            time_taken=chat_result.time_taken,
            content=chat_result.content,
            success=chat_result.success
        )


class ContextualMetaDataStrategy(MetaDataTranslateStrategy):
    """使用上下文替换的元数据翻译策略。适用于需要上下文信息的元数据翻译，如简介、标题等。"""

    
    @observe
    def process(self, provider: Provider, context: TranslateContext) -> ProcessResult:
        system_prompt = self.system_prompts[context.task_type]
        examples = self.examples.get(context.task_type, [])
        query = self.query_templates.get(context.task_type, {})
        messages = build_message_with_replacements(system_prompt, examples, query, context)
        chat_result = provider.chat(messages, stream=self.stream, temperature=self.temperature)
        return ProcessResult(
            task_type=context.task_type,
            attempt_count=chat_result.attempt_count,
            time_taken=chat_result.time_taken,
            content=chat_result.content,
            success=chat_result.success
        )

class BaseSubtitleStrategy(TranslateStrategy):
    """基础字幕处理策略。

    最朴素的字幕翻译策略，直接调用Provider处理。

    Attributes:
        system_prompts (dict): 各任务类型对应的系统提示词。
        user_queries (dict): 各任务类型对应的用户查询模板。
    """
    def __init__(self, stream:bool=False, temperature:float=1.0):
        """初始化基础字幕处理策略。"""
        super().__init__(stream, temperature)
        self.system_prompts = {
            TaskType.CORRECT_SUBTITLE: CORRECT_SUBTITLE_SYSTEM_PROMPT,
            TaskType.TRANSLATE_SUBTITLE: TRANSLATE_SUBTITLE_PROMPT
        }
        self.user_queries = {
            TaskType.CORRECT_SUBTITLE: CORRECT_SUBTITLE_USER_QUERY,
            TaskType.TRANSLATE_SUBTITLE: TRANSLATE_SUBTITLE_USER_QUERY
        }

    
    def process(self, provider: Provider, context: TranslateContext) -> ProcessResult:
        """处理字幕（需由子类实现）。

        Args:
            provider (Provider): 服务提供者。
            context (TranslateContext): 处理上下文。

        Raises:
            NotImplementedError: 子类必须实现此方法。
        """
        raise NotImplementedError()

class BestEffortSubtitleStrategy(BaseSubtitleStrategy):
    """尽力而为的字幕处理策略。

    维护字幕块链表，当节点失败时如果台词数>=10则三等分后重试。
    子类只需实现_create_initial_linked_list方法来创建初始链表。
    """
    def _create_initial_linked_list(self, text: str) -> SubtitleBlock:
        """创建初始链表。

        子类需要实现此方法。

        Args:
            text (str): 待处理的字幕文本。

        Raises:
            NotImplementedError: 子类必须实现此方法。

        Returns:
            SubtitleBlock: 链表头节点。
        """
        raise NotImplementedError("Subclass must implement _create_initial_linked_list")

    @observe
    def process(self, provider: Provider, context: TranslateContext) -> ProcessResult:
        """处理字幕，采用尽力而为策略。

        创建初始链表，如果失败且台词数>=10则三等分后重试，最后聚合所有结果。

        Args:
            provider (Provider): 服务提供者。
            context (TranslateContext): 处理上下文。

        Returns:
            ProcessResult: 处理结果。
        """
        # 熔断检查：如果 Provider 已熔断，快速失败
        circuit_breaker_result = self._check_provider_available(provider, context.task_type)
        if circuit_breaker_result is not None:
            return circuit_breaker_result

        # Strategy 层总时间计时器
        start_time = time.time()

        # 创建初始链表（由子类实现）
        head = self._create_initial_linked_list(context.text_to_process)

        # 初始化累加器
        total_attempt_count = 0
        total_api_time = 0  # provider 层的累计时间

        # 处理链表
        head, total_attempt_count, total_api_time = self._process_linked_list_with_best_effort(
            context.task_type, provider, context, head, total_attempt_count, total_api_time, self.stream
        )

        # Strategy 层总耗时
        strategy_time_taken = int((time.time() - start_time) * 1000)  # 毫秒

        # 聚合结果
        return aggregate_successful_results(head, context.task_type, total_attempt_count, strategy_time_taken)

    def _process_linked_list_with_best_effort(self,
                                              task_type,
                                              provider,
                                              context,
                                              head: SubtitleBlock,
                                              total_attempt_count: int,
                                              total_api_time: int,
                                              stream: bool = False,
                                              temperature: float = 1.0,
                                              ) -> Tuple[SubtitleBlock, int, int]:
        """尽力而为地处理链表。

        逐个处理节点，失败时如果台词数>=10则三等分节点并插入链表。
        在处理过程中动态累积术语库，使后续节点能够利用之前识别的术语。

        Args:
            task_type: 任务类型。
            provider: 服务提供者。
            context: 元数据。
            head: 链表头节点。
            total_attempt_count: 累计调用次数。
            total_api_time: 累计API时间（毫秒）。
            stream: 是否使用流式调用，默认False。
            temperature: 调用模型的温度，默认 1.0。
        Returns:
            A tuple containing:
                SubtitleBlock: 更新后的头结点.
                int: 总 api 调用次数.
                int: 总 api 时间(ms).
        """
        prev = None
        current = head
        new_head = head

        while current is not None:
            if current.is_processed:
                # 已处理，跳过
                prev = current
                current = current.next
                continue

            # 处理当前节点
            system_prompt = self.system_prompts[task_type]
            user_query = self.user_queries[task_type]
            messages = build_subtitle_messages(system_prompt, user_query, context, current.origin)

            logger.info(f"Processing node with {current.count_subtitles()} subtitles")
            result = provider.chat(messages, stream=stream, temperature=temperature, timeout=500, response_format={"type": "json_object"})

            # 累加调用次数和API时间（无论成功失败）
            total_attempt_count += result.attempt_count
            total_api_time += result.time_taken

            if result.success:
                # 成功，标记为已处理
                current.processed = result
                current.is_processed = True
                context = update_translate_context(context, result)
                logger.info(f"Node processed successfully")
                prev = current
                current = current.next
            else:
                # 失败，检查是否需要三等分
                subtitle_count = current.count_subtitles()
                logger.warning(f"Node processing failed, subtitle count: {subtitle_count}")

                if subtitle_count >= 10:
                    # 三等分
                    logger.info(f"Splitting node into 3 parts")
                    node1, node2, node3 = current.split_into_three()

                    if prev is None:
                        new_head = node1
                    else:
                        prev.next = node1

                    current = node1
                else:
                    current.processed = result
                    current.is_processed = True
                    prev = current
                    current = current.next
        return new_head, total_attempt_count, total_api_time

class NoSliceSubtitleStrategy(BestEffortSubtitleStrategy):
    """不分片字幕处理策略。

    将整个字幕文本作为一个节点处理，使用尽力而为的重试机制。
    """

    def _create_initial_linked_list(self, text: str) -> SubtitleBlock:
        """创建单节点链表。

        Args:
            text (str): 待处理的字幕文本。

        Returns:
            SubtitleBlock: 包含整个文本的单节点链表。
        """
        return SubtitleBlock(origin=text, is_processed=False)

class SliceSubtitleStrategy(BestEffortSubtitleStrategy):
    """分片字幕处理策略。

    将字幕文本按指定大小分片后处理，使用尽力而为的重试机制。

    Attributes:
        slice_size (int): 每个分片的字幕条目数量。
    """

    def __init__(self, stream, temperature, slice_size=200):
        """初始化分片策略。

        Args:
            slice_size (int): 每个分片的字幕条目数量，默认200。
        """
        super().__init__(stream, temperature)
        self.slice_size = slice_size

    
    def _create_initial_linked_list(self, text: str) -> Optional[SubtitleBlock]:
        """创建多节点链表（预分片）。

        Args:
            text (str): 待处理的字幕文本。

        Returns:
            Optional[SubtitleBlock]: 分片后的链表头节点，如果文本为空则返回None。
        """
        blocks = adaptive_slice_subtitle(text, self.slice_size)

        if not blocks:
            return None

        # 创建链表
        head = None
        prev = None
        for block_content in blocks:
            if not block_content.endswith("\n\n"):
                block_content += "\n\n"
            node = SubtitleBlock(origin=block_content, is_processed=False)
            if head is None:
                head = node
            else:
                prev.next = node
            prev = node

        return head
