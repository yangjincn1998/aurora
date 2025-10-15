from enum import Enum, auto


class TaskType(Enum):
    """任务类型枚举。

    定义系统支持的各种任务类型，包括元数据翻译和字幕处理。

    Attributes:
        METADATA_DIRECTOR: 元数据导演信息翻译任务。
        METADATA_ACTOR: 元数据演员信息翻译任务。
        METADATA_CATEGORY: 元数据分类信息翻译任务。
        CORRECT_SUBTITLE: 字幕校正任务。
        TRANSLATE_SUBTITLE: 字幕翻译任务。
    """
    METADATA_DIRECTOR = auto()
    METADATA_ACTOR = auto()
    METADATA_CATEGORY = auto()
    CORRECT_SUBTITLE = auto()
    TRANSLATE_SUBTITLE = auto()


class StageStatus(Enum):
    """流水线阶段状态枚举。

    定义流水线各阶段的执行状态。

    Attributes:
        SUCCESS: 执行成功。
        FAILED: 执行失败。
        PENDING: 待执行。
    """
    SUCCESS = auto()
    FAILED = auto()
    PENDING = auto()


class ErrorType(Enum):
    """错误类型枚举。

    定义各种API调用可能出现的错误类型，分为不可恢复错误、请求相关错误、可重试错误等。

    Attributes:
        AUTHENTICATION_ERROR: 认证失败（API密钥无效），不可恢复。
        PERMISSION_DENIED: 权限不足，不可恢复。
        INSUFFICIENT_QUOTA: 额度不足，不可恢复。
        NOT_FOUND: 资源不存在（如模型不存在），不可恢复。
        CONTENT_FILTER: 内容违规被过滤，不可恢复。
        UNPROCESSABLE_ENTITY: 请求格式/参数错误，不可恢复。
        PAYLOAD_TOO_LARGE: 请求体过大，不可恢复。
        LENGTH_LIMIT: 输出因达到最大token限制而被截断，请求相关错误。
        RATE_LIMIT: 速率限制（可等待后重试），可重试错误。
        CONNECTION_ERROR: 网络连接错误，可重试错误。
        TIMEOUT: 请求超时，可重试错误。
        OTHER: 其他未分类错误。
    """
    # === 不可恢复错误（应触发熔断）===
    AUTHENTICATION_ERROR = auto()  # 认证失败（API密钥无效）
    PERMISSION_DENIED = auto()  # 权限不足
    INSUFFICIENT_QUOTA = auto()  # 额度不足
    NOT_FOUND = auto()  # 资源不存在（如模型不存在）
    CONTENT_FILTER = auto()  # 内容违规被过滤
    UNPROCESSABLE_ENTITY = auto()  # 请求格式/参数错误
    PAYLOAD_TOO_LARGE = auto()  # 请求体过大

    # === 请求相关错误（可能需要调整请求，目前只支持一种）===
    LENGTH_LIMIT = auto()  # 输出因达到最大token限制而被截断


    # === 可重试错误 ===
    RATE_LIMIT = auto()  # 速率限制（可等待后重试）
    CONNECTION_ERROR = auto()  # 网络连接错误
    TIMEOUT = auto()  # 请求超时

    # === 其他 ===
    OTHER = auto()  # 其他未分类错误


class PiplinePhase(Enum):
    """流水线阶段枚举。

    定义视频处理流水线中的各个阶段。

    Attributes:
        PROCESSING_METADATA: 元数据处理阶段。
        EXTRACT_AUDIO: 音频提取阶段。
        DENOISE_AUDIO: 音频降噪阶段。
        TRANSCRIBE_AUDIO: 音频转写阶段。
        CORRECT_SUBTITLE: 字幕校正阶段。
        TRANSLATE_SUBTITLE: 字幕翻译阶段。
    """
    PROCESSING_METADATA = auto()

    EXTRACT_AUDIO = auto()
    DENOISE_AUDIO = auto()
    TRANSCRIBE_AUDIO = auto()

    CORRECT_SUBTITLE = auto()
    TRANSLATE_SUBTITLE = auto()
    BILINGUAL_SUBTITLE = auto()
