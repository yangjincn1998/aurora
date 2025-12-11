import json
from typing import List

from src.aurora.domain.context import TranslateContext
from src.aurora.domain.results import ProcessResult
from src.aurora.utils.logger import get_logger

logger = get_logger(__name__)


def adaptive_slice_subtitle(srt_content: str, slice_size: int) -> List[str]:
    """自适应分片字幕内容。

    根据字幕总数和slice_size动态计算分片方案，确保分片均匀。

    Args:
        srt_content (str): 原始字幕内容。
        slice_size (int): 每个分片的字幕条目数量。

    Returns:
        List[str]: 分片后的字幕文本列表。
    """
    if not srt_content:
        return []
    all_blocks = [b for b in srt_content.strip().split("\n\n") if b.strip()]
    total_blocks = len(all_blocks)

    if total_blocks == 0:
        return []
    if total_blocks <= slice_size:
        return [srt_content]

    num_slices = (total_blocks + slice_size - 1) // slice_size
    base_size = total_blocks // num_slices
    remainder = total_blocks % num_slices
    logger.info(
        "Adaptive slice: total lines number: %d, slice size: %d -> plan to slice to %d slices, base size: %d, remainder: %d",
        total_blocks,
        slice_size,
        num_slices,
        base_size,
        remainder,
    )
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


def should_split_node(current, threshold: int = 10) -> bool:
    """判断是否需要拆分节点。

    Args:
        current: 当前节点对象。
        threshold (int): 拆分阈值，默认为10。

    Returns:
        bool: 是否需要拆分。
    """
    if not hasattr(current, "count_subtitles"):
        return False
    subtitle_count = current.count_subtitles()
    logger.warning("Node processing failed, subtitle count: %d", subtitle_count)
    return subtitle_count >= threshold


def process_chain_with_retry(head, processor_func, should_retry_func=None):
    """通用链表处理函数，支持重试机制。

    Args:
        head: 链表头节点。
        processor_func: 处理函数，接收当前节点作为参数，返回处理结果。
        should_retry_func: 重试判断函数，接收当前节点作为参数，返回是否需要重试。

    Returns:
        tuple: (更新后的头节点, 总调用次数, 总API时间)
    """
    prev = None
    current = head
    new_head = head

    total_attempt_count = 0
    total_api_time = 0

    while current is not None:
        if current.is_processed:
            # 已处理，跳过
            prev = current
            current = current.next
            continue

        # 处理当前节点
        result = processor_func(current)

        # 累加统计信息
        if hasattr(result, "attempt_count"):
            total_attempt_count += result.attempt_count
        if hasattr(result, "time_taken"):
            total_api_time += result.time_taken

        if result.success:
            # 成功，标记为已处理
            current.processed = result
            current.is_processed = True
            prev = current
            current = current.next
        else:
            # 失败，检查是否需要重试/拆分
            if should_retry_func and should_retry_func(current):
                logger.info("Splitting node into 3 parts")
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


def renumber_subtitles(srt_content: str) -> str:
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


def update_translate_context(context, chat_result):
    """根据最新的ChatResult更新TranslateContext。

    Args:
        context: 当前的处理上下文对象。
        chat_result: 最新的聊天结果对象。

    Returns:
        更新后的处理上下文对象。
    """
    if not chat_result.success or not chat_result.content:
        return context

    try:
        result_json = json.loads(chat_result.content)
        result_terms = result_json.get("terms", [])
        if not result_terms:
            return context

        # 以术语中的 japanese 作为主键
        history_primary_keys = (
            {term["japanese"] for term in context.terms} if context.terms else set()
        )
        for term in result_terms:
            if term["japanese"] not in history_primary_keys:
                context.terms.append(term)
                history_primary_keys.add(term["japanese"])
                term_ja, term_ch = term["japanese"], term.get("recommended_chinese", "")
                logger.info("Updated term: %s -> %s", term_ja, term_ch)

        # 返回新的上下文对象（保持原有结构）
        return TranslateContext(
            task_type=context.task_type,
            metadata=context.metadata,
            terms=context.terms,
            text_to_process=context.text_to_process,
        )
    except json.JSONDecodeError:
        return context


def aggregate_successful_results(
    head, task_type, total_attempt_count: int, total_time_taken: int
):
    """聚合链表中所有成功节点的处理结果。

    合并所有content和differences，重新排序字幕序号。

    Args:
        head: 链表头节点。
        task_type: 任务类型。
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
                logger.error("Failed to parse JSON from processed content: %s", e)

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
        terms=all_terms if all_terms else None,
        differences=all_differences if all_differences else None,
        success=renumbered_content is not None,
    )
