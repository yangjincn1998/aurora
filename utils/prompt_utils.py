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