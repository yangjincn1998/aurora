import uuid
import json
import re
import time
from abc import ABC, abstractmethod

from models.query_result import ChatResult, ProcessResult, SrtBlockLinkedListNode
from models.tasktype import TaskType
from services.translate.prompts import DIRECTOR_SYSTEM_PROMPT, ACTOR_SYSTEM_PROMPT, CATEGORY_SYSTEM_PROMPT, director_examples, actor_examples, category_examples, CORRECT_SUBTITLE_SYSTEM_PROMPT, CORRECT_SUBTITLE_USER_QUERY, TRANSLATE_SUBTITLE_PROMPT, TRANSLATE_SUBTITLE_USER_QUERY
from utils.logger import get_logger

logger = get_logger("av_translator")

def renumber_subtitles(srt_content: str) -> str:
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

class TranslateStrategy(ABC):
    @abstractmethod
    def process(self, task_type, provider, metadata, text):
        pass
class BuilderMessageStrategy():
    @staticmethod
    def build_message_with_uuid(system_prompt, examples, query):
        messages = []
        hint = "\n用户的查询会以uuid开头，请忽略它"
        messages.append({"role": "system", "content": system_prompt+hint})
        for question, answer in examples.items():
            messages.append({"role": "user", "content": str(uuid.uuid4())+question})
            messages.append({"role": "assistant", "content": answer})
        messages.append({"role": "user", "content": str(uuid.uuid4())+query})
        return messages

class MetaDataTranslateStrategy(BuilderMessageStrategy):
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
    def process(self, task_type, provider, text):
        system_prompt = self.system_prompts[task_type]
        examples = self.examples.get(task_type, {})
        messages = self.build_message_with_uuid(system_prompt, examples, text)
        return provider.chat(messages)

class BaseSubtitleStrategy(TranslateStrategy):
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
    def _build_messages(system_prompt, user_query, metadata, text):
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_query.format(metadata=metadata, text=text)}]
        return messages

    def process(self, task_type, provider, metadata, text):
        system_prompt = self.system_prompts[task_type]
        user_query = self.user_queries[task_type]
        messages = self._build_messages(system_prompt, user_query, metadata, text)
        return provider.chat(messages, timeout=500)

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
            renumbered_content = renumber_subtitles(merged_content)
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

class BestEffortSubtitleStrategy(BaseSubtitleStrategy):
    """
    尽力而为的字幕处理策略基类
    - 维护字幕块链表
    - 当节点失败时，如果台词数 >= 10，则三等分后重试
    - 子类只需实现 _create_initial_linked_list 方法来创建初始链表
    """

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
        current = head
        new_head = head

        while current is not None:
            if current.is_processed:
                # 已处理，跳过
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
                current = current.next
            else:
                # 失败，检查是否需要三等分
                subtitle_count = current.count_subtitles()
                logger.warning(f"Node processing failed, subtitle count: {subtitle_count}")

                if subtitle_count >= 10:
                    # 三等分
                    logger.info(f"Splitting node into 3 parts")
                    node1, node2, node3 = current.split_into_three()

                    # 如果是头节点，更新 head
                    if current == new_head:
                        new_head = node1

                    # 替换当前节点
                    # 需要找到前一个节点来更新链接
                    if current == head:
                        # 如果是第一个节点
                        current = node1
                        new_head = node1
                    else:
                        # 找到前一个节点
                        prev = new_head
                        while prev.next != current:
                            prev = prev.next
                        prev.next = node1
                        current = node1
                else:
                    # 台词数 < 10，标记为失败但已处理
                    current.processed = result
                    current.is_processed = True
                    logger.warning(f"Node has < 10 subtitles, marking as processed with failure")
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

    def _slice_subtitle(self, srt_content):
        """将字幕分片"""
        lines = srt_content.split("\n\n")
        blocks = []
        current = ""
        for i, line in enumerate(lines):
            current += line + "\n\n"
            if (i + 1) % self.slice_size == 0:
                blocks.append(current)
                current = ""
        if current:  # 添加剩余内容
            blocks.append(current)
        return blocks

    def _create_initial_linked_list(self, text: str) -> SrtBlockLinkedListNode:
        """创建多节点链表（预分片）"""
        blocks = self._slice_subtitle(text)

        # 创建链表
        head = None
        prev = None
        for block in blocks:
            node = SrtBlockLinkedListNode(origin=block, is_processed=False)
            if head is None:
                head = node
                prev = node
            else:
                prev.next = node
                prev = node

        return head
