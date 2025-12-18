"""
配置管理器的单元测试
测试YAML配置加载、单例模式和异常处理
"""
import tempfile
from pathlib import Path

import pytest
import yaml

from aurora.config.manager import ConfigManager
from aurora.config.settings import GlobalConfig


class TestConfigManager:
    """测试配置管理器"""

    @pytest.fixture
    def valid_yaml_content(self):
        """返回有效的YAML配置内容"""
        return """
translate_orchestrator:
  streaming_model:
    - deepseek-chat
    - google/gemini-2.5-pro
  tasks:
    metadata_director:
      providers:
        - service: openai
          model: deepseek-chat
          api_key: ENV_DEEPSEEK_API_KEY
          base_url: ENV_DEEPSEEK_BASE_URL
      stream: true
      temperature: 0.7
    metadata_actor:
      providers:
        - service: openai
          model: deepseek-chat
          api_key: ENV_DEEPSEEK_API_KEY
          base_url: ENV_DEEPSEEK_BASE_URL

transcriber:
  type: whisper
  config:
    model_size: "large-v3"
    device: "cuda"
    compute_type: "float16"
  quality_checker:
    providers:
      service: openai
      model: "z-ai/glm-4.6"
      api_key: "ENV_OPENROUTER_API_KEY"
      base_url: "ENV_OPENROUTER_API_KEY"
"""

    @pytest.fixture
    def invalid_yaml_content(self):
        """返回无效的YAML内容（语法错误）"""
        return """
translate_orchestrator:
  streaming_model:
    - deepseek-chat
    - google/gemini-2.5-pro
  tasks:
    metadata_director:
      providers: [
        { service: openai
"""

    @pytest.fixture
    def invalid_schema_content(self):
        """返回YAML语法有效但模式无效的内容（缺少必填字段）"""
        return """
translate_orchestrator:
  streaming_model:
    - deepseek-chat
  # tasks 字段缺失
transcriber:
  type: whisper
  config:
    model_size: "large-v3"
  # quality_checker 字段缺失
"""

    def test_load_valid_config_from_file(self, valid_yaml_content):
        """测试从文件加载有效配置"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(valid_yaml_content)
            temp_path = f.name

        try:
            # 临时替换配置路径
            original_path = ConfigManager._config_path
            ConfigManager._config_path = Path(temp_path)

            # 清除单例实例以确保重新加载
            ConfigManager._instance = None

            config = ConfigManager.load()
            assert isinstance(config, GlobalConfig)
            assert config.translate_orchestrator is not None
            assert config.transcriber is not None
            assert len(config.translate_orchestrator.streaming_model) == 2
        finally:
            ConfigManager._config_path = original_path
            ConfigManager._instance = None
            Path(temp_path).unlink(missing_ok=True)

    def test_singleton_pattern(self, valid_yaml_content):
        """测试单例模式：多次调用返回相同实例"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(valid_yaml_content)
            temp_path = f.name

        try:
            original_path = ConfigManager._config_path
            ConfigManager._config_path = Path(temp_path)
            ConfigManager._instance = None

            config1 = ConfigManager.get()
            config2 = ConfigManager.get()
            config3 = ConfigManager.load()

            # 所有调用应返回相同实例
            assert config1 is config2
            assert config2 is config3

            # 实例应为GlobalConfig类型
            assert isinstance(config1, GlobalConfig)
        finally:
            ConfigManager._config_path = original_path
            ConfigManager._instance = None
            Path(temp_path).unlink(missing_ok=True)

    def test_load_missing_file(self):
        """测试加载不存在的配置文件"""
        original_path = ConfigManager._config_path
        ConfigManager._config_path = Path("/non/existent/path/config.yaml")
        ConfigManager._instance = None

        try:
            with pytest.raises(FileNotFoundError):
                ConfigManager.load()
        finally:
            ConfigManager._config_path = original_path
            ConfigManager._instance = None

    def test_load_invalid_yaml_syntax(self, invalid_yaml_content):
        """测试加载语法无效的YAML文件"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(invalid_yaml_content)
            temp_path = f.name

        try:
            original_path = ConfigManager._config_path
            ConfigManager._config_path = Path(temp_path)
            ConfigManager._instance = None

            # YAML语法错误应抛出异常
            with pytest.raises(Exception):
                ConfigManager.load()
        finally:
            ConfigManager._config_path = original_path
            ConfigManager._instance = None
            Path(temp_path).unlink(missing_ok=True)

    def test_load_invalid_schema(self, invalid_schema_content):
        """测试加载模式无效的YAML文件（缺少必填字段）"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(invalid_schema_content)
            temp_path = f.name

        try:
            original_path = ConfigManager._config_path
            ConfigManager._config_path = Path(temp_path)
            ConfigManager._instance = None

            # Pydantic验证应失败
            with pytest.raises(Exception):
                ConfigManager.load()
        finally:
            ConfigManager._config_path = original_path
            ConfigManager._instance = None
            Path(temp_path).unlink(missing_ok=True)

    def test_get_without_load(self, valid_yaml_content):
        """测试get()方法在未加载时自动加载"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(valid_yaml_content)
            temp_path = f.name

        try:
            original_path = ConfigManager._config_path
            ConfigManager._config_path = Path(temp_path)
            ConfigManager._instance = None

            # 直接调用get()应自动加载
            config = ConfigManager.get()
            assert isinstance(config, GlobalConfig)
            assert ConfigManager._instance is not None
        finally:
            ConfigManager._config_path = original_path
            ConfigManager._instance = None
            Path(temp_path).unlink(missing_ok=True)


def test_fixtures_config_yaml():
    """测试fixtures目录下的config.yml文件"""
    fixtures_path = Path(__file__).parent / "fixtures" / "config.yml"
    assert fixtures_path.exists(), f"Fixtures config file not found at {fixtures_path}"

    # 读取YAML内容
    with open(fixtures_path, 'r', encoding='utf-8') as f:
        yaml_content = yaml.safe_load(f)

    # 基本结构检查
    assert "translate_orchestrator" in yaml_content
    assert "transcriber" in yaml_content

    translate_config = yaml_content["translate_orchestrator"]
    assert "stream_models" in translate_config or "streaming_model" in translate_config
    assert "task" in translate_config or "tasks" in translate_config

    transcriber_config = yaml_content["transcriber"]
    assert "type" in transcriber_config
    assert "config" in transcriber_config
    assert "quality_checker" in transcriber_config
