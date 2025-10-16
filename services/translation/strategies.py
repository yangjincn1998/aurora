import json
import time
import uuid
from abc import ABC, abstractmethod
from typing import List, Optional

from data_structures.subtitle_node import SubtitleBlock
from models.context import TranslateContext
from models.enums import TaskType
from models.results import ProcessResult, ChatResult
from services.translation.prompts import DIRECTOR_SYSTEM_PROMPT, ACTOR_SYSTEM_PROMPT, CATEGORY_SYSTEM_PROMPT, \
    director_examples, actor_examples, category_examples, CORRECT_SUBTITLE_SYSTEM_PROMPT, CORRECT_SUBTITLE_USER_QUERY, \
    TRANSLATE_SUBTITLE_PROMPT, TRANSLATE_SUBTITLE_USER_QUERY
from services.translation.provider import Provider
from utils.logger import get_logger

logger = get_logger("av_translator")

class TranslateStrategy(ABC):
    """
    翻译策略的高层接口
    所有翻译策略都需要实现 process 方法
    process 方法必须包含 provider 和 text 参数，其他参数可以不同
    """
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
    def __init__(self):
        """初始化元数据翻译策略。"""
        self.system_prompts = {
            TaskType.METADATA_DIRECTOR: DIRECTOR_SYSTEM_PROMPT,
            TaskType.METADATA_ACTOR: ACTOR_SYSTEM_PROMPT,
            TaskType.METADATA_CATEGORY: CATEGORY_SYSTEM_PROMPT
        }
        self.examples = {
            TaskType.METADATA_DIRECTOR: director_examples,
            TaskType.METADATA_ACTOR: actor_examples,
            TaskType.METADATA_CATEGORY: category_examples
        }

    @staticmethod
    def _build_message_with_uuid(system_prompt, examples, query):
        """构建带有UUID前缀的消息，用于元数据翻译。

        Args:
            system_prompt (str): 系统提示词。
            examples (dict): 示例字典。
            query (str): 用户查询。

        Returns:
            list: 构建好的消息列表。
        """
        messages = []
        hint = "\n用户的查询会以uuid开头，请忽略它"
        messages.append({"role": "system", "content": system_prompt + hint})
        for question, answer in examples.items():
            messages.append({"role": "user", "content": str(uuid.uuid4()) + question})
            messages.append({"role": "assistant", "content": answer})
        messages.append({"role": "user", "content": str(uuid.uuid4()) + query})
        return messages

    def process(self, provider: Provider, context:TranslateContext) -> ProcessResult:
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
        messages = self._build_message_with_uuid(system_prompt, examples, context.text_to_process)
        chat_result = provider.chat(messages)

        # 将 ChatResult 转换为 ProcessResult
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
    def __init__(self):
        """初始化基础字幕处理策略。"""
        self.system_prompts = {
            TaskType.CORRECT_SUBTITLE: CORRECT_SUBTITLE_SYSTEM_PROMPT,
            TaskType.TRANSLATE_SUBTITLE: TRANSLATE_SUBTITLE_PROMPT
        }
        self.user_queries = {
            TaskType.CORRECT_SUBTITLE: CORRECT_SUBTITLE_USER_QUERY,
            TaskType.TRANSLATE_SUBTITLE: TRANSLATE_SUBTITLE_USER_QUERY
        }

    @staticmethod
    def _recursive_replace(data_structure, replacements):
        """递归地遍历嵌套数据结构并替换占位符。

        Args:
            data_structure (Union[dict, list, set, str, Any]): 要遍历的数据结构。
            replacements (dict): 占位符到替换内容的映射字典。

        Returns:
            Union[dict, list, str, Any]: 替换后的新数据结构。
        """
        if isinstance(data_structure, dict):
            new_dict = {}
            for key, value in data_structure.items():
                new_dict[key] = BaseSubtitleStrategy._recursive_replace(value, replacements)
            return new_dict
        elif isinstance(data_structure, list):
            return [BaseSubtitleStrategy._recursive_replace(item, replacements) for item in data_structure]
        elif isinstance(data_structure, set):
            return {BaseSubtitleStrategy._recursive_replace(item, replacements) for item in data_structure}
        elif isinstance(data_structure, str) and data_structure in replacements:
            return replacements[data_structure]
        else:
            return data_structure

    @staticmethod
    def _build_messages(system_prompt, user_query, context: TranslateContext, node_text: str):
        """构建字幕处理消息。

        Args:
            system_prompt (str): 系统提示词。
            user_query (dict): 用户查询模板。
            context (TranslateContext): 处理上下文。
            node_text (str): 待处理的字幕文本。

        Returns:
            list: 构建好的消息列表。
        """
        replacements = {
            "metadata_value": context.metadata,
            "text_value": node_text,
            "terms_value": context.terms,
        }
        populated_query_dict = BaseSubtitleStrategy._recursive_replace(user_query, replacements)
        user_content_json = json.dumps(populated_query_dict, ensure_ascii=False, indent=2)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content_json}
        ]
        return messages

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

    @staticmethod
    def _renumber_subtitles(srt_content: str) -> str:
        """重新排序SRT字幕的序号。

        Args:
            srt_content (str): 原始SRT字幕内容。

        Returns:
            str: 重新编号后的SRT字幕内容。
        """
        if not srt_content:
            return srt_content

        blocks = srt_content.strip().split("\n\n")
        renumbered_blocks = []

        for idx, block in enumerate(blocks, start=1):
            if not block.strip():
                continue
            lines = block.split("\n")
            if len(lines) >= 2:
                # 替换第一行的序号
                lines[0] = str(idx)
                renumbered_blocks.append("\n".join(lines))

        return "\n\n".join(renumbered_blocks)

    @staticmethod
    def _update_context(context: TranslateContext, chat_result: ChatResult) -> TranslateContext:
        """根据最新的ChatResult更新TranslateContext。

        Args:
            context (TranslateContext): 当前的处理上下文。
            chat_result (ChatResult): 最新的聊天结果。

        Returns:
            TranslateContext: 更新后的处理上下文。
        """
        if not chat_result.success or not chat_result.content:
            return context

        try:
            result_json = json.loads(chat_result.content)
            result_terms = result_json.get("terms", [])
            if not result_terms:
                return context
            # 以术语中的 japanese 作为主键
            history_primary_keys = {term['japanese'] for term in context.terms} if context.terms else set()
            for term in result_terms:
                if term['japanese'] not in history_primary_keys:
                    context.terms.append(term)
                    history_primary_keys.add(term['japanese'])
                    term_ja, term_ch = term['japanese'], term.get('recommended_chinese', '')
                    logger.info(f"Updated term: {term_ja} -> {term_ch}")
            return TranslateContext(
                task_type=context.task_type,
                metadata=context.metadata,
                terms=context.terms,
                text_to_process=context.text_to_process
            )
        except json.JSONDecodeError:
            return context

    def _aggregate_linked_list(self, head: SubtitleBlock, task_type: TaskType,
                               total_attempt_count: int, total_time_taken: int) -> ProcessResult:
        """聚合链表中所有成功节点的处理结果。

        合并所有content和differences，重新排序字幕序号。

        Args:
            head (SubtitleBlock): 链表头节点。
            task_type (TaskType): 任务类型。
            total_attempt_count (int): 累计调用次数。
            total_time_taken (int): 累计总耗时（毫秒）。

        Returns:
            ProcessResult: 聚合后的处理结果。
        """
        all_content_parts = []
        all_differences = []
        all_terms = []

        # 遍历链表，只收集成功节点的内容
        current = head
        while current is not None:
            if current.is_processed and current.processed and current.processed.success:
                # 解析 JSON 内容
                try:
                    result_json = json.loads(current.processed.content)

                    # 收集 content
                    if "content" in result_json:
                        all_content_parts.append(result_json["content"])

                    # 收集 differences
                    if "differences" in result_json and result_json["differences"]:
                        all_differences.extend(result_json["differences"])

                    # 收集 terms
                    if "terms" in result_json and result_json["terms"]:
                        all_terms.extend(result_json["terms"])

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON from processed content: {e}")

            current = current.next

        # 合并所有 content
        if all_content_parts:
            merged_content = "\n\n".join(all_content_parts)
            # 重新排序字幕序号
            renumbered_content = self._renumber_subtitles(merged_content)
        else:
            renumbered_content = None

        return ProcessResult(
            task_type=task_type,
            attempt_count=total_attempt_count,
            time_taken=total_time_taken,
            content=renumbered_content,
            terms=all_terms if all_terms else None,
            differences=all_differences if all_differences else None,
            success=renumbered_content is not None
        )

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
            context.task_type, provider, context, head, total_attempt_count, total_api_time
        )

        # Strategy 层总耗时
        strategy_time_taken = int((time.time() - start_time) * 1000)  # 毫秒

        # 聚合结果
        return self._aggregate_linked_list(head, context.task_type, total_attempt_count, strategy_time_taken)

    def _process_linked_list_with_best_effort(self, task_type, provider, context, head: SubtitleBlock,
                                              total_attempt_count: int, total_api_time: int):
        """尽力而为地处理链表。

        逐个处理节点，失败时如果台词数>=10则三等分节点并插入链表。
        在处理过程中动态累积术语库，使后续节点能够利用之前识别的术语。

        Args:
            task_type (TaskType): 任务类型。
            provider (Provider): 服务提供者。
            context (TranslateContext): 元数据。
            head (SubtitleBlock): 链表头节点。
            total_attempt_count (int): 累计调用次数。
            total_api_time (int): 累计API时间（毫秒）。

        Returns:
            tuple: (更新后的头节点, 总调用次数, 总API时间)。
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
            messages = self._build_messages(system_prompt, user_query, context, current.origin)

            logger.info(f"Processing node with {current.count_subtitles()} subtitles")
            result = provider.chat(messages, timeout=500, response_format={"type": "json_object"})

            # 累加调用次数和API时间（无论成功失败）
            total_attempt_count += result.attempt_count
            total_api_time += result.time_taken

            if result.success:
                # 成功，标记为已处理
                current.processed = result
                current.is_processed = True
                context = self._update_context(context, result)
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

    def __init__(self, slice_size=200):
        """初始化分片策略。

        Args:
            slice_size (int): 每个分片的字幕条目数量，默认200。
        """
        super().__init__()
        self.slice_size = slice_size

    def _adaptive_slice_subtitle(self, srt_content: str) -> List[str]:
        """自适应分片字幕内容。

        根据字幕总数和slice_size动态计算分片方案，确保分片均匀。

        Args:
            srt_content (str): 原始字幕内容。

        Returns:
            List[str]: 分片后的字幕文本列表。
        """
        if not srt_content:
            return []
        all_blocks = [b for b in srt_content.strip().split("\n\n") if b.strip()]
        total_blocks = len(all_blocks)

        if total_blocks == 0:
            return []
        if total_blocks <= self.slice_size:
            return [srt_content]

        num_slices = (total_blocks + self.slice_size - 1) // self.slice_size
        base_size = total_blocks // num_slices
        remainder = total_blocks % num_slices
        logger.info(f"Adaptive slice: total lines number: {total_blocks}, slice size: {self.slice_size} -> "
                   f"plan to slice to {num_slices} slices, base size: {base_size}, remainder: {remainder}")
        final_slices = []
        current_index = 0
        for i in range(num_slices):
            slice_size = base_size + 1 if i < remainder else base_size
            start_index = current_index
            end_index = current_index + slice_size

            slice_blocks = all_blocks[start_index:end_index]
            final_slices.append("\n\n".join(slice_blocks))

            current_index = end_index
        return final_slices

    def _create_initial_linked_list(self, text: str) -> Optional[SubtitleBlock]:
        """创建多节点链表（预分片）。

        Args:
            text (str): 待处理的字幕文本。

        Returns:
            Optional[SubtitleBlock]: 分片后的链表头节点，如果文本为空则返回None。
        """
        blocks = self._adaptive_slice_subtitle(text)

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
