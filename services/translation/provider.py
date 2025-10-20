import os
import time
from abc import ABC, abstractmethod
from typing import Dict, Optional

import openai

from models.enums import ErrorType
from models.results import ChatResult
from utils.logger import get_logger

logger = get_logger("av_translator")

class Provider(ABC):
    """翻译服务提供者抽象基类。

    定义所有翻译服务提供者必须实现的接口。
    """
    @property
    @abstractmethod
    def available(self) -> bool:
        """检查提供者是否可用。

        Returns:
            bool: 如果提供者可用返回True，否则返回False。
        """
        pass

    @property
    @abstractmethod
    def model(self) -> str:
        """获取模型名称。

        Returns:
            str: 使用的模型名称。
        """
        pass

    @abstractmethod
    def chat(self, messages, **kwargs) -> ChatResult:
        """发送聊天请求。

        Args:
            messages (list): 消息列表。
            **kwargs: 额外的关键字参数。

        Returns:
            ChatResult: 聊天请求的结果。
        """
        pass

    @staticmethod
    def from_config(config: Dict) -> Optional['Provider']:
        """从配置字典创建 Provider 实例（工厂方法）。

        Args:
            config (Dict): Provider 配置字典，包含以下字段：
                - service (str): 服务类型（如 "openai"）
                - model (str): 模型名称
                - api_key (str): API密钥（可以是 "ENV_XXX" 格式引用环境变量）
                - base_url (str): API基础URL（可以是 "ENV_XXX" 格式引用环境变量）
                - timeout (int, optional): 超时时间

        Returns:
            Optional[Provider]: Provider 实例，如果创建失败返回 None
        """
        service_type = config.get("service")

        if service_type == "openai":
            return OpenaiProvider.from_config(config)
        else:
            logger.warning(f"Unknown service type: {service_type}")
            return None


class OpenaiProvider(Provider):
    """OpenAI兼容的API提供者实现。

    支持OpenAI格式的API调用，包括自动重试和熔断机制。

    Attributes:
        api_key (str): API密钥。
        base_url (str): API基础URL。
        _model (str): 使用的模型名称。
        timeout (int): 请求超时时间（秒）。
        _available (bool): 提供者是否可用（熔断状态）。
        client (openai.OpenAI): OpenAI客户端实例。
    """
    def __init__(self, api_key, base_url, model, timeout=500):
        """初始化OpenAI提供者。

        Args:
            api_key (str): API密钥。
            base_url (str): API基础URL。
            model (str): 使用的模型名称。
            timeout (int): 请求超时时间（秒），默认500秒。
        """
        self.api_key = api_key
        self.base_url = base_url
        self._model = model
        self.timeout = timeout
        self._available = True
        self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)

    @property
    def available(self) -> bool:
        return self._available

    @property
    def model(self):
        return self._model

    @classmethod
    def from_config(cls, config: Dict) -> Optional['OpenaiProvider']:
        """从配置字典创建 OpenaiProvider 实例。

        Args:
            config (Dict): Provider 配置字典，包含以下字段：
                - model (str): 模型名称
                - api_key (str): API密钥（可以是 "ENV_XXX" 格式引用环境变量）
                - base_url (str): API基础URL（可以是 "ENV_XXX" 格式引用环境变量）
                - timeout (int, optional): 超时时间，默认500秒

        Returns:
            Optional[OpenaiProvider]: OpenaiProvider 实例，如果创建失败返回 None
        """
        model = config.get("model")
        api_key = config.get("api_key")
        base_url = config.get("base_url")
        timeout = config.get("timeout", 500)

        # 处理环境变量：如果值以 "ENV_" 开头，则从环境变量中获取
        if api_key and api_key.startswith("ENV_"):
            env_var = api_key[4:]  # 去掉 "ENV_" 前缀
            api_key = os.getenv(env_var)
            if not api_key:
                logger.warning(f"Environment variable {env_var} not found for api_key")
                return None

        if base_url and base_url.startswith("ENV_"):
            env_var = base_url[4:]
            base_url = os.getenv(env_var)
            if not base_url:
                logger.warning(f"Environment variable {env_var} not found for base_url")
                return None

        # 验证必需参数
        if not all([api_key, base_url, model]):
            logger.warning(
                f"Missing required parameters: api_key={bool(api_key)}, base_url={bool(base_url)}, model={bool(model)}")
            return None

        return cls(api_key=api_key, base_url=base_url, model=model, timeout=timeout)

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

        max_retries = 3

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
                self._available = False  # 触发熔断
                time_taken = int((time.time() - start_time) * 1000)
                return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.AUTHENTICATION_ERROR)

            except openai.PermissionDeniedError as e:
                # 权限错误 - 不可重试（账户权限不足），触发熔断
                logger.error(f"OpenAI API permission denied: {str(e)}")
                self._available = False  # 触发熔断
                time_taken = int((time.time() - start_time) * 1000)
                return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.PERMISSION_DENIED)

            except openai.NotFoundError as e:
                # 资源未找到 - 不可重试（模型不存在等），触发熔断
                logger.error(f"OpenAI API resource not found: {str(e)}")
                self._available = False  # 触发熔断
                time_taken = int((time.time() - start_time) * 1000)
                return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.NOT_FOUND)

            except openai.UnprocessableEntityError as e:
                # 请求格式错误 - 不可重试（参数问题），但不触发熔断（可能是特定请求的问题）
                logger.error(f"OpenAI API unprocessable entity: {str(e)}")
                time_taken = int((time.time() - start_time) * 1000)
                return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.UNPROCESSABLE_ENTITY)

            except openai.APITimeoutError as e:
                # 超时错误 - 可重试
                logger.error(f"OpenAI API timeout error (attempt {attempt + 1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                time_taken = int((time.time() - start_time) * 1000)
                return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.TIMEOUT)
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
                    self._available = False  # 触发熔断
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

            except openai.APIStatusError as e:
                # 根据状态码进行细粒度分类
                status_code = e.status_code
                time_taken = int((time.time() - start_time) * 1000)

                # 应触发熔断的状态码（Provider 级别的不可恢复错误）
                if status_code == 401:
                    logger.error(f"OpenAI API authentication error (401): {e.response.text}")
                    self._available = False  # 触发熔断
                    return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.AUTHENTICATION_ERROR)
                elif status_code == 402:
                    logger.error(f"OpenAI API payment required (402): {e.response.text}")
                    self._available = False  # 触发熔断
                    return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.INSUFFICIENT_QUOTA)
                elif status_code == 403:
                    logger.error(f"OpenAI API permission denied (403): {e.response.text}")
                    self._available = False  # 触发熔断
                    return ChatResult(success=False, attempt_count=attempt_count, time_taken=time_taken, content=None, error=ErrorType.PERMISSION_DENIED)
                elif status_code == 404:
                    logger.error(f"OpenAI API not found (404): {e.response.text}")
                    self._available = False  # 触发熔断
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