from typing import Optional

from models.results import ChatResult


class SubtitleBlock:
    """字幕块链表节点类。

    用于尽力而为的重试策略，将字幕文本组织成链表结构以支持动态分片和重试。

    Attributes:
        origin (str): 原始字幕文本。
        processed (Optional[ChatResult]): 处理结果。
        is_processed (bool): 是否已处理。
        next (Optional[SubtitleBlock]): 下一个节点。
    """

    def __init__(
            self,
            origin: str,
            processed: Optional[ChatResult] = None,
            is_processed: bool = False,
            next_node=None,
    ):
        """初始化字幕块链表节点。

        Args:
            origin (str): 原始字幕文本。
            processed (Optional[ChatResult]): 处理结果。
            is_processed (bool): 是否已处理。
            next_node (Optional[SubtitleBlock]): 下一个节点。
        """
        self.origin = origin  # 原始字幕文本
        self.processed = processed  # 处理结果
        self.is_processed = is_processed  # 是否已处理
        self.next = next_node  # 下一个节点

    def count_subtitles(self) -> int:
        """计算原始文本中的字幕条目数量（台词数）。

        字幕块之间用两个换行符分隔。

        Returns:
            int: 字幕条目数量。
        """
        if not self.origin:
            return 0
        # 字幕块之间用两个换行符分隔
        blocks = self.origin.strip().split("\n\n")
        return len([b for b in blocks if b.strip()])

    def split_into_three(
            self,
    ) -> tuple["SubtitleBlock", "SubtitleBlock", "SubtitleBlock"]:
        """将当前节点的字幕文本三等分，返回三个新节点。

        将字幕块按台词数量三等分，创建三个新的链表节点并连接。

        Returns:
            tuple[SubtitleBlock, SubtitleBlock, SubtitleBlock]:
                三个新创建的节点，按顺序连接。
        """
        blocks = self.origin.strip().split("\n\n")
        blocks = [b for b in blocks if b.strip()]  # 过滤空块

        total = len(blocks)
        third = total // 3

        # 三等分
        part1 = blocks[:third]
        part2 = blocks[third: 2 * third]
        part3 = blocks[2 * third:]

        # 创建三个新节点
        node1 = SubtitleBlock(origin="\n\n".join(part1) + "\n\n", is_processed=False)
        node2 = SubtitleBlock(origin="\n\n".join(part2) + "\n\n", is_processed=False)
        node3 = SubtitleBlock(origin="\n\n".join(part3) + "\n\n", is_processed=False)

        # 连接节点
        node1.next = node2
        node2.next = node3
        node3.next = self.next  # 保持与原链表的连接

        return node1, node2, node3
