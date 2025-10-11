from abc import ABC, abstractmethod
from models.query_result import ChatResult, ErrorType
import openai
from utils.logger import get_logger
import time
import json

logger = get_logger("av_translator")

class Provider(ABC):
    @property
    @abstractmethod
    def model(self) -> str:
        pass
    @abstractmethod
    def chat(self, messages, **kwargs) -> ChatResult:
        pass


class OpenaiProvider(Provider):
    def __init__(self, api_key, base_url, model, timeout=500):
        self.api_key = api_key
        self.base_url = base_url
        self._model = model
        self.timeout = timeout
        self.available = True
        self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)

    @property
    def model(self):
        return self._model

    def chat(self, messages, **kwargs) -> ChatResult:
        """
        发送chat请求，支持自动重试机制
        - 最多重试3次
        - 遇到可恢复错误时等待5秒后重试
        - 黑名单模式：默认可重试，只排除明确不可重试的错误
        """
        # 熔断检查：如果 Provider 已不可用，快速失败
        if not self.available:
            logger.warning(f"Provider {self.model} is unavailable due to previous irrecoverable error")
            return ChatResult(success=False, attempt_count=0, time_taken=0, content=None, error=ErrorType.OTHER)
        start_time = time.time()
        attempt_count = 0

        logger.info(f"OpenAIProvider chat called for model: {self.model}")

        max_retries = 5
        retry_delay = 8  # 秒

        # 为Google模型准备的安全设置，将其设置为最低阈值
        # 这会通过OpenRouter传递给后端的Gemini等模型
        safety_settings = {
            "safety_settings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ],
        }

        for attempt in range(max_retries):
            attempt_count += 1
            try:
                logger.info(f"Sending request to API (attempt {attempt + 1}/{max_retries}, non-streaming mode)...")
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
                    # 空响应可能是临时问题，允许重试
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        continue
                    time_taken = int((time.time() - start_time) * 1000)  # 毫秒
                    return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.OTHER)

                choice = response.choices[0]
                content = choice.message.content
                finish_reason = choice.finish_reason

                logger.info(f"Response: finish_reason={finish_reason}, content_length={len(content) if content else 0} chars")

                # 检查完成原因
                if finish_reason == "stop":
                    time_taken = int((time.time() - start_time) * 1000)  # 毫秒
                    return ChatResult(success=True, attempt_count=attempt_count, time_taken=time_taken, content=content.strip() if content else "")
                elif finish_reason == "length":
                    # 长度限制 - 不可重试（业务逻辑问题）
                    logger.warning("Response finished due to length limit")
                    time_taken = int((time.time() - start_time) * 1000)
                    return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.LENGTH_LIMIT)
                elif finish_reason == "content_filter":
                    # 内容过滤 - 不可重试（内容违规）
                    logger.warning("Response blocked by content filter")
                    time_taken = int((time.time() - start_time) * 1000)
                    return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.CONTENT_FILTER)
                else:
                    # 其他 finish_reason 也返回内容
                    logger.warning(f"Unexpected finish_reason: {finish_reason}")
                    time_taken = int((time.time() - start_time) * 1000)
                    return ChatResult(success=True, attempt_count=attempt_count, time_taken=time_taken, content=content.strip() if content else "")

            except openai.AuthenticationError as e:
                # 认证错误 - 不可重试（API密钥无效），触发熔断
                logger.error(f"OpenAI API authentication error: {str(e)}")
                self.available = False  # 触发熔断
                time_taken = int((time.time() - start_time) * 1000)
                return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.AUTHENTICATION_ERROR)

            except openai.PermissionDeniedError as e:
                # 权限错误 - 不可重试（账户权限不足），触发熔断
                logger.error(f"OpenAI API permission denied: {str(e)}")
                self.available = False  # 触发熔断
                time_taken = int((time.time() - start_time) * 1000)
                return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.PERMISSION_DENIED)

            except openai.NotFoundError as e:
                # 资源未找到 - 不可重试（模型不存在等），触发熔断
                logger.error(f"OpenAI API resource not found: {str(e)}")
                self.available = False  # 触发熔断
                time_taken = int((time.time() - start_time) * 1000)
                return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.NOT_FOUND)

            except openai.UnprocessableEntityError as e:
                # 请求格式错误 - 不可重试（参数问题），但不触发熔断（可能是特定请求的问题）
                logger.error(f"OpenAI API unprocessable entity: {str(e)}")
                time_taken = int((time.time() - start_time) * 1000)
                return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.UNPROCESSABLE_ENTITY)

            except openai.APIConnectionError as e:
                # 连接错误 - 可重试
                logger.error(f"OpenAI API connection error (attempt {attempt + 1}/{max_retries}): {e.__cause__}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                time_taken = int((time.time() - start_time) * 1000)
                return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.CONNECTION_ERROR)

            except openai.RateLimitError as e:
                # 速率限制 - 检查是否为额度不足
                error_message = str(e)
                # 检查是否是额度不足（insufficient_quota）
                if "insufficient_quota" in error_message.lower() or "quota" in error_message.lower():
                    logger.error(f"OpenAI API insufficient quota: {error_message}")
                    self.available = False  # 触发熔断
                    time_taken = int((time.time() - start_time) * 1000)
                    return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.INSUFFICIENT_QUOTA)

                # 普通速率限制 - 可重试
                logger.error(f"OpenAI API rate limit exceeded (attempt {attempt + 1}/{max_retries}): {error_message}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                time_taken = int((time.time() - start_time) * 1000)
                return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.RATE_LIMIT)

            except openai.APITimeoutError as e:
                # 超时错误 - 可重试
                logger.error(f"OpenAI API timeout error (attempt {attempt + 1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                time_taken = int((time.time() - start_time) * 1000)
                return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.TIMEOUT)

            except openai.APIStatusError as e:
                # 根据状态码进行细粒度分类
                status_code = e.status_code
                time_taken = int((time.time() - start_time) * 1000)

                # 应触发熔断的状态码（Provider 级别的不可恢复错误）
                if status_code == 401:
                    logger.error(f"OpenAI API authentication error (401): {e.response.text}")
                    self.available = False  # 触发熔断
                    return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.AUTHENTICATION_ERROR)
                elif status_code == 402:
                    logger.error(f"OpenAI API payment required (402): {e.response.text}")
                    self.available = False  # 触发熔断
                    return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.INSUFFICIENT_QUOTA)
                elif status_code == 403:
                    logger.error(f"OpenAI API permission denied (403): {e.response.text}")
                    self.available = False  # 触发熔断
                    return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.PERMISSION_DENIED)
                elif status_code == 404:
                    logger.error(f"OpenAI API not found (404): {e.response.text}")
                    self.available = False  # 触发熔断
                    return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.NOT_FOUND)

                # 请求级别错误（不触发熔断，可能通过调整请求解决）
                elif status_code == 400:
                    logger.error(f"OpenAI API bad request (400): {e.response.text}")
                    return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.UNPROCESSABLE_ENTITY)
                elif status_code == 413:
                    logger.error(f"OpenAI API payload too large (413): {e.response.text}")
                    return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.PAYLOAD_TOO_LARGE)
                elif status_code == 422:
                    logger.error(f"OpenAI API unprocessable entity (422): {e.response.text}")
                    return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.UNPROCESSABLE_ENTITY)

                # 其他状态码 - 可重试（如 5xx, 429, 408 等）
                else:
                    logger.error(f"OpenAI API status error (attempt {attempt + 1}/{max_retries}): {status_code} - {e.response.text}")
                    if attempt < max_retries - 1:
                        logger.info(f"Status code {status_code} is retryable. Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        continue
                    return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.OTHER)

            except Exception as e:
                # 其他未知错误 - 默认可重试（黑名单模式）
                logger.error(f"Unexpected error during OpenAI API call (attempt {attempt + 1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                time_taken = int((time.time() - start_time) * 1000)
                return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.OTHER)

        # 理论上不会到这里，但作为保险
        logger.error("All retry attempts exhausted")
        time_taken = int((time.time() - start_time) * 1000)
        return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.OTHER)