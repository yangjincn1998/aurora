from enum import Enum, auto


class MetadataType(Enum):
    """数据库中元数据实体类型枚举。

    定义系统支持的各种实体类型，包括导演、演员、分类、标题和简介。

    Attributes:
        STUDIO: 制作商实体类型。
        DIRECTOR: 导演实体类型。
        ACTOR: 男演员实体类型。
        CATEGORY: 分类实体类型。
        TITLE: 标题实体类型。
        SYNOPSIS: 简介实体类型。
    """

    STUDIO = "studio"
    DIRECTOR = "director"
    CATEGORY = "category"
    ACTOR = "actor"
    TITLE = "title"
    SYNOPSIS = "synopsis"


class TaskType(Enum):
    """任务类型枚举。

    定义系统支持的各种任务类型，包括元数据翻译和字幕处理。

    Attributes:
        METADATA_STUDIO: 元数据中制作上翻译任务。
        METADATA_DIRECTOR: 元数据导演信息翻译任务。
        METADATA_ACTOR: 元数据演员信息翻译任务。
        METADATA_CATEGORY: 元数据分类信息翻译任务。
        METADATA_TITLE: 元数据标题翻译任务。
        METADATA_SYNOPSIS: 元数据简介翻译任务。
        CORRECT_SUBTITLE: 字幕校正任务。
        TRANSLATE_SUBTITLE: 字幕翻译任务。
    """

    METADATA_STUDIO = "metadata_studio"
    METADATA_DIRECTOR = "metadata_director"
    METADATA_ACTOR = "metadata_actor"
    METADATA_CATEGORY = "metadata_category"
    METADATA_TITLE = "metadata_title"
    METADATA_SYNOPSIS = "metadata_synopsis"
    CORRECT_SUBTITLE = "correct_subtitle"
    TRANSLATE_SUBTITLE = "translate_subtitle"


class StageStatus(Enum):
    """流水线阶段状态枚举。

    定义流水线各阶段的执行状态。

    Attributes:
        SUCCESS: 执行成功。
        FAILED: 执行失败。
        PENDING: 待执行。
    """

    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"


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

    PROCESSING_METADATA = "pipeline_phase_processing_metadata"

    EXTRACT_AUDIO = "pipeline_phase_extract_audio"
    DENOISE_AUDIO = "pipeline_phase_denoise_audio"
    TRANSCRIBE_AUDIO = "pipeline_phase_transcribe_audio"

    CORRECT_SUBTITLE = "pipeline_phase_correct_subtitle"
    TRANSLATE_SUBTITLE = "pipeline_phase_translate_subtitle"
    BILINGUAL_SUBTITLE = "pipeline_phase_bilingual_subtitle"


VIDEO_SUFFIXES = {
    "mp4",
    "mkv",
    "avi",
    "mov",
    "wmv",
    "flv",
    "webm",
    "mpg",
    "mpeg",
    "3gp",
}
