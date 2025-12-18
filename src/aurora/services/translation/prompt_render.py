from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from aurora.config.manager import config  # 引用我们刚做好的配置


class PromptRenderer:
    def __init__(self):
        # 允许用户在 data_dir/templates 下覆盖默认模板
        user_template_dir = config.data_dir / "templates"
        # 默认模板目录 (假设在当前文件同级)
        default_template_dir = Path(__file__).parent / "templates"

        # 优先查找用户目录，没有再找默认目录
        search_paths = [user_template_dir, default_template_dir]

        self.env = Environment(
            loader=FileSystemLoader(search_paths),
            autoescape=select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True
        )

    def render(self, template_name: str, **kwargs: Any) -> str:
        """
        通用渲染方法
        :param template_name: 模板相对路径，如 'subtitle/correct_system.j2'
        :param kwargs: 传给模板的变量，直接支持 Pydantic 对象
        """
        template = self.env.get_template(template_name)
        return template.render(**kwargs)


# 单例实例
prompt_renderer = PromptRenderer()
