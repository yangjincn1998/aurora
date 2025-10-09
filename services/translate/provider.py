from abc import ABC, abstractmethod
from models.query_result import QueryResult, ErrorType
import openai
from utils.logger import get_logger

logger = get_logger("av_translator")

class Provider(ABC):
    @property
    @abstractmethod
    def model(self) -> str:
        pass
    @abstractmethod
    def chat(self, messages, **kwargs)->QueryResult:
        pass


class OpenaiProvider(Provider):
    def __init__(self, api_key, base_url, model, timeout=300):
        self.api_key = api_key
        self.base_url = base_url
        self._model = model
        self.timeout = timeout
        self.client = openai.OpenAI(base_url=self.base_url, api_key=self.api_key, timeout=timeout)

    @property
    def model(self):
        return self._model

    def chat(self, messages, **kwargs) -> QueryResult:
        logger.info(f"OpenAIProvider chat called for model: {self.model}")

        # 为Google模型准备的安全设置，将其设置为最低阈值
        # 这会通过OpenRouter传递给后端的Gemini等模型
        safety_settings = {
            "safety_settings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ],
            # 禁用思维链模式，直接输出最终结果
            "thinking_mode": "disabled"
        }
        try:
            logger.info("Sending request to API (non-streaming mode)...")
            # 改用非流式请求，更稳定可靠
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=False,  # 关键改动：使用非流式
                extra_body=safety_settings,
                response_format={"type":"json_object"},
                **kwargs
            )

            logger.info("Received response from API")

            # 处理非流式响应
            if not response.choices:
                logger.error("No choices in response")
                return QueryResult(success=False, content=None, error=ErrorType.OTHER)

            choice = response.choices[0]
            content = choice.message.content
            finish_reason = choice.finish_reason

            logger.info(f"Response: finish_reason={finish_reason}, content_length={len(content) if content else 0} chars")

            # 检查完成原因
            if finish_reason == "stop":
                return QueryResult(success=True, content=content.strip() if content else "")
            elif finish_reason == "length":
                logger.warning("Response finished due to length limit")
                return QueryResult(success=False, content=None, error=ErrorType.LENGTH_LIMIT)
            elif finish_reason == "content_filter":
                logger.warning("Response blocked by content filter")
                return QueryResult(success=False, content=None, error=ErrorType.CONTENT_FILTER)
            else:
                # 其他 finish_reason 也返回内容
                logger.warning(f"Unexpected finish_reason: {finish_reason}")
                return QueryResult(success=True, content=content.strip() if content else "")
        except openai.APIConnectionError as e:
            logger.error(f"OpenAI API connection error: {e.__cause__}")
            return QueryResult(success=False, content=None, error=ErrorType.OTHER)
        except openai.RateLimitError as e:
            logger.error(f"OpenAI API rate limit exceeded: {e.response.text}")
            return QueryResult(success=False, content=None, error=ErrorType.INSUFFICIENT_RESOURCES)
        except openai.APIStatusError as e:
            logger.error(f"OpenAI API status error: {e.status_code} - {e.response.text}")
            return QueryResult(success=False, content=None, error=ErrorType.OTHER)
        except Exception as e:
            logger.error(f"An unexpected error occurred during OpenAI API call: {str(e)}")
            return QueryResult(success=False, content=None, error=ErrorType.OTHER)