import json
import uuid
from typing import List, Dict, Any, Union

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
    elif isinstance(data_structure, list):
        return [recursive_replace(item, replacements) for item in data_structure]
    elif isinstance(data_structure, set):
        return {recursive_replace(item, replacements) for item in data_structure}
    elif isinstance(data_structure, str) and data_structure in replacements:
        return replacements[data_structure]
    else:
        return data_structure


def build_message_with_uuid(system_prompt: str, examples: Dict[str, str], query: str) -> List[Dict[str, str]]:
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
        messages.append({"role": "user", "content": str(uuid.uuid1()) + question})
        messages.append({"role": "assistant", "content": answer})
    messages.append({"role": "user", "content": str(uuid.uuid1()) + query})
    return messages


def build_message_with_replacements(system_prompt: str, examples: List[tuple], query: Dict,
                                  context) -> List[Dict[str, str]]:
    """构建带有上下文替换的消息，用于元数据翻译。

    Args:
        system_prompt (str): 系统提示词。
        examples (list[tuple]): 示例字典或列表。
        query(dict): 用户查询模板。
        context: 处理上下文对象，需要包含actors、actress、text_to_process等属性。

    Returns:
        list: 构建好的消息列表。
    """
    messages = [{"role": "system", "content": system_prompt}]
    for question, answer in examples:
        messages.append({"role": "user", "content": str(question)})
        messages.append({"role": "assistant", "content": answer})
    replacements = {
        "actors_value": context.actors,
        "actresses_value": context.actress,
        "synopsis_value": context.text_to_process,
        "title_value": context.text_to_process,
    }
    populated_query = recursive_replace(query, replacements)
    messages.append({"role": "user", "content": json.dumps(populated_query)})
    return messages


def build_subtitle_messages(system_prompt: str, user_query: Dict[str, Any],
                           context, node_text: str) -> List[Dict[str, str]]:
    """构建字幕处理消息。

    Args:
        system_prompt (str): 系统提示词。
        user_query (dict): 用户查询模板。
        context: 处理上下文对象，需要包含metadata、terms等属性。
        node_text (str): 待处理的字幕文本。

    Returns:
        list: 构建好的消息列表。
    """
    replacements = {
        "metadata_value": context.metadata,
        "text_value": node_text,
        "terms_value": context.terms,
    }
    populated_query_dict = recursive_replace(user_query, replacements)
    user_content_json = json.dumps(populated_query_dict, ensure_ascii=False, indent=2)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content_json}
    ]
    return messages