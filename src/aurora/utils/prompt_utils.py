from typing import List, Dict, Union


def recursive_replace(data_structure, replacements):
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
            new_dict[key] = recursive_replace(value, replacements)
        return new_dict

    if isinstance(data_structure, list):
        return [recursive_replace(item, replacements) for item in data_structure]

    if isinstance(data_structure, set):
        return {recursive_replace(item, replacements) for item in data_structure}

    if isinstance(data_structure, str) and data_structure in replacements:
        return replacements[data_structure]

    return data_structure


def build_messages(
    system_prompt: str, examples: Dict[str, str], query: str
) -> List[Dict[str, str]]:
    """构建消息，用于元数据翻译。

    Args:
        system_prompt (str): 系统提示词。
        examples (dict): 示例字典。
        query (str): 用户查询。

    Returns:
        list: 构建好的消息列表。
    """
    messages = [{"role": "system", "content": system_prompt}]
    for question, answer in examples.items():
        messages.append({"role": "user", "content": question})
        messages.append({"role": "assistant", "content": answer})
    messages.append({"role": "user", "content": query})
    return messages
