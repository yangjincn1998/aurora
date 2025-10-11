import uuid
import json
import re
import time
from abc import ABC, abstractmethod
from typing import List, Optional

from models.query_result import ChatResult, ProcessResult, SrtBlockLinkedListNode
from models.tasktype import TaskType
from services.translate.prompts import DIRECTOR_SYSTEM_PROMPT, ACTOR_SYSTEM_PROMPT, CATEGORY_SYSTEM_PROMPT, director_examples, actor_examples, category_examples, CORRECT_SUBTITLE_SYSTEM_PROMPT, CORRECT_SUBTITLE_USER_QUERY, TRANSLATE_SUBTITLE_PROMPT, TRANSLATE_SUBTITLE_USER_QUERY
from utils.logger import get_logger

logger = get_logger("av_translator")

class TranslateStrategy(ABC):
    """
    翻译策略的高层接口
    所有翻译策略都需要实现 process 方法
    process 方法必须包含 provider 和 text 参数，其他参数可以不同
    """
    @abstractmethod
    def process(self, *args, **kwargs):
        """子类需要实现此方法，但签名可以不同"""
        pass

    def _check_provider_available(self, provider, task_type: TaskType) -> Optional[ProcessResult]:
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

class SubtitleTranslateStrategy(TranslateStrategy):
    """字幕翻译策略的基类"""
    @abstractmethod
    def process(self, task_type, provider, metadata, text):
        pass

class MetaDataTranslateStrategy(TranslateStrategy):
    """元数据翻译策略"""
    def __init__(self):
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
        """构建带有 UUID 前缀的消息，用于元数据翻译"""
        messages = []
        hint = "\n用户的查询会以uuid开头，请忽略它"
        messages.append({"role": "system", "content": system_prompt + hint})
        for question, answer in examples.items():
            messages.append({"role": "user", "content": str(uuid.uuid4()) + question})
            messages.append({"role": "assistant", "content": answer})
        messages.append({"role": "user", "content": str(uuid.uuid4()) + query})
        return messages

    def process(self, task_type, provider, text) -> ProcessResult:
        """
        处理元数据翻译
        返回 ProcessResult 以保持与其他策略的一致性
        """
        # 熔断检查：如果 Provider 已熔断，快速失败
        circuit_breaker_result = self._check_provider_available(provider, task_type)
        if circuit_breaker_result is not None:
            return circuit_breaker_result

        # 调用 Provider
        system_prompt = self.system_prompts[task_type]
        examples = self.examples.get(task_type, {})
        messages = self._build_message_with_uuid(system_prompt, examples, text)
        chat_result = provider.chat(messages)

        # 将 ChatResult 转换为 ProcessResult
        return ProcessResult(
            task_type=task_type,
            attempt_count=chat_result.attempt_count,
            time_taken=chat_result.time_taken,
            content=chat_result.content,
            success=chat_result.success
        )

class BaseSubtitleStrategy(SubtitleTranslateStrategy):
    """最朴素的字幕翻译策略 - 直接调用 Provider 处理"""
    def __init__(self):
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
        """
        递归地遍历一个嵌套的字典或列表，并替换指定的占位符字符串
        :param data_structure: 要遍历的数据结构。
        :param replacements: 一部字典，key是占位符，value是替换内容。
        :return: 一个新的、替换了占位符的数据结构。
        """
        if isinstance(data_structure, dict):
            new_dict = {}
            for key, value in data_structure.items():
                new_dict[key] = BaseSubtitleStrategy._recursive_replace(value, replacements)
            return new_dict
        elif isinstance(data_structure, list):
            return [BaseSubtitleStrategy._recursive_replace(item, replacements) for item in data_structure]
        elif isinstance(data_structure, str) and data_structure in replacements:
            return replacements[data_structure]
        else:
            return data_structure

    @staticmethod
    def _build_messages(system_prompt, user_query, metadata, text):
        """构建字幕处理消息"""
        replacements = {
            "metadata_value": metadata,
            "text_value": text
        }
        populated_query_dict = BaseSubtitleStrategy._recursive_replace(user_query, replacements)
        user_content_json = json.dumps(populated_query_dict, ensure_ascii=False, indent=2)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content_json}
        ]
        return messages

    def process(self, task_type, provider, metadata, text):
        pass

class BestEffortSubtitleStrategy(BaseSubtitleStrategy):
    """
    尽力而为的字幕处理策略
    - 维护字幕块链表
    - 当节点失败时，如果台词数 >= 10，则三等分后重试
    - 子类只需实现 _create_initial_linked_list 方法来创建初始链表
    """

    @staticmethod
    def _renumber_subtitles(srt_content: str) -> str:
        """重新排序SRT字幕的序号"""
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

    def _aggregate_linked_list(self, head: SrtBlockLinkedListNode, task_type: TaskType,
                               total_attempt_count: int, total_time_taken: int) -> ProcessResult:
        """
        聚合链表中所有成功节点的处理结果
        - 合并所有 content
        - 合并所有 differences
        - 重新排序字幕序号
        - 使用传入的累加器作为总调用次数和总时间
        """
        all_content_parts = []
        all_differences = []

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
            differences=all_differences if all_differences else None,
            success=renumbered_content is not None
        )

    def _create_initial_linked_list(self, text: str) -> SrtBlockLinkedListNode:
        """
        创建初始链表
        子类需要实现此方法
        """
        raise NotImplementedError("Subclass must implement _create_initial_linked_list")

    def process(self, task_type, provider, metadata, text, file_name="unknown") -> ProcessResult:
        """
        处理字幕，采用尽力而为策略:
        - 创建初始链表
        - 如果失败且台词数 >= 10，则三等分后重试
        - 聚合所有结果并返回 StrategyResult
        """
        # 熔断检查：如果 Provider 已熔断，快速失败
        circuit_breaker_result = self._check_provider_available(provider, task_type)
        if circuit_breaker_result is not None:
            return circuit_breaker_result

        # Strategy 层总时间计时器
        start_time = time.time()

        # 创建初始链表（由子类实现）
        head = self._create_initial_linked_list(text)

        # 初始化累加器
        total_attempt_count = 0
        total_api_time = 0  # provider 层的累计时间

        # 处理链表
        head, total_attempt_count, total_api_time = self._process_linked_list_with_best_effort(
            task_type, provider, metadata, head, total_attempt_count, total_api_time
        )

        # Strategy 层总耗时
        strategy_time_taken = int((time.time() - start_time) * 1000)  # 毫秒

        # 聚合结果
        return self._aggregate_linked_list(head, task_type, total_attempt_count, strategy_time_taken)

    def _process_linked_list_with_best_effort(self, task_type, provider, metadata, head: SrtBlockLinkedListNode,
                                              total_attempt_count: int, total_api_time: int):
        """
        尽力而为地处理链表
        - 逐个处理节点
        - 失败时，如果台词数 >= 10，则三等分节点并插入链表
        - 失败时，如果台词数 < 10，则跳过该节点
        - 返回更新后的 head、总调用次数、总API时间
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
            messages = self._build_messages(system_prompt, user_query, metadata, current.origin)

            logger.info(f"Processing node with {current.count_subtitles()} subtitles")
            result = provider.chat(messages, timeout=500)

            # 累加调用次数和API时间（无论成功失败）
            total_attempt_count += result.attempt_count
            total_api_time += result.time_taken

            if result.success:
                # 成功，标记为已处理
                current.processed = result
                current.is_processed = True
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
    """不分片策略，使用尽力而为的重试机制"""

    def _create_initial_linked_list(self, text: str) -> SrtBlockLinkedListNode:
        """创建单节点链表"""
        return SrtBlockLinkedListNode(origin=text, is_processed=False)

class SliceSubtitleStrategy(BestEffortSubtitleStrategy):
    """分片策略，使用尽力而为的重试机制"""

    def __init__(self, slice_size=200):
        super().__init__()
        self.slice_size = slice_size

    def _adaptive_slice_subtitle(self, srt_content: str) -> List[str]:
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

    def _create_initial_linked_list(self, text: str) -> Optional[SrtBlockLinkedListNode]:
        """创建多节点链表（预分片）"""
        blocks = self._adaptive_slice_subtitle(text)

        if not blocks:
            return None

        # 创建链表
        head = None
        prev = None
        for block_content in blocks:
            if not block_content.endswith("\n\n"):
                block_content += "\n\n"
            node = SrtBlockLinkedListNode(origin=block_content, is_processed=False)
            if head is None:
                head = node
            else:
                prev.next = node
            prev = node

        return head
