"""
定义Pydantic模型
"""
from pathlib import Path
from typing import Any

from platformdirs import user_data_path, user_cache_path
from pydantic import BaseModel, Field

from aurora.domain.enums import TaskType

APP_NAME = "aurora"


def get_default_data_dir() -> Path:
    path = user_data_path(APP_NAME)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_default_cache_dir() -> Path:
    path = user_cache_path(APP_NAME)
    path.mkdir(parents=True, exist_ok=True)
    return path


class ProviderConfig(BaseModel):
    service: str
    model: str
    api_key: str = Field(..., description="支持环境变量引用，如 ENV_OPENAI_KEY")
    base_url: str | None = Field(..., description="支持环境变量引用，如 ENV_OPENAI_KEY")
    timeout: int = 30


class StrategyConfig(BaseModel):
    slice_enabled: bool = Field(True)
    slice_size: int = 500


class TaskConfig(BaseModel):
    providers: list[ProviderConfig] = Field(default_factory=list)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    stream: bool | None = None
    temperature: bool | None = Field(None, ge=0.0, le=1.0)


class TranslateOrchestratorConfig(BaseModel):
    streaming_model: list[str] = Field(default_factory=list)
    tasks: dict[TaskType, TaskConfig] = Field(default_factory=dict)


class QualityCheckConfig(BaseModel):
    providers: ProviderConfig


class TranscriberConfig(BaseModel):
    type: str
    config: dict[str, Any]
    quality_checker: QualityCheckConfig


class GlobalConfig(BaseModel):
    translate_orchestrator: TranslateOrchestratorConfig
    transcriber: TranscriberConfig
    data_dir: Path = Field(default_factory=get_default_data_dir)
    cache_dir: Path = Field(default_factory=get_default_cache_dir)
