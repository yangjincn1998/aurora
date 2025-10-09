import uuid
from abc import ABC, abstractmethod

from models.query_result import QueryResult
from models.tasktype import TaskType
from services.translate.prompts import DIRECTOR_SYSTEM_PROMPT, ACTOR_SYSTEM_PROMPT, CATEGORY_SYSTEM_PROMPT, director_examples, actor_examples, category_examples, CORRECT_SUBTITLE_SYSTEM_PROMPT, CORRECT_SUBTITLE_USER_QUERY, TRANSLATE_SUBTITLE_PROMPT, TRANSLATE_SUBTITLE_USER_QUERY

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
        messages = self._build_messages(system_prompt, user_query,metadata, text)
        return provider.chat(messages, timeout=500)

class NoSliceSubtitleStrategy(BaseSubtitleStrategy):
    pass

class SliceSubtitleStrategy(BaseSubtitleStrategy):
    def __init__(self, slice_size=200):
        super().__init__()
        self.slice_size = slice_size
    def _slice_subtitle(self, srt_content):
        lines = srt_content.split("\n\n")
        blocks = []
        current = ""
        for i, line in enumerate(lines):
            current += line+"\n\n"
            if (i + 1) % self.slice_size == 0:
                blocks.append(current)
                current = ""
        if current:  # 添加剩余内容
            blocks.append(current)
        return blocks
    def process(self, task_type, provider, metadata, text):
        blocks = self._slice_subtitle(text)
        answers = ""
        for block in blocks:
            result = super().process(task_type, provider, metadata, block)
            if not result.success:
                return QueryResult(success=False, content=None, error=result.error)
            answers += result.content + "\n\n"
        return QueryResult(success=True, content=answers.strip())
