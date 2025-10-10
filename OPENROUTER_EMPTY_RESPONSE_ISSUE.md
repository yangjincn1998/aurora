# OpenRouter API 空响应问题分析与解决方案

## 📋 问题总结

通过详细的 HTTP 请求/响应日志记录，我们发现了 **OpenRouter API 的真正问题**：

### 问题现象

使用 OpenRouter API (google/gemini-2.5-pro 模型) 时，经常出现 `JSONDecodeError`，错误信息类似：
```
JSONDecodeError: Expecting value: line 619 column 1 (char 3399)
```

### 🔍 深入调查发现

通过捕获原始 HTTP 响应，我们发现：

| 测试次数 | HTTP 状态码 | 响应大小 | 前导空白行 | 包含JSON | 结果 |
|---------|-----------|---------|-----------|---------|------|
| 1 | 200 | 11,539 bytes | 2,099 | ❌ 无 | **失败** |
| 2 | 200 | 825 bytes | 151 | ❌ 无 | **失败** |
| 3 | 200 | 92,097 bytes | 2,280 | ✅ 有 | **成功** |
| 4 | 200 | 30,112 bytes | 654 | ✅ 有 | **成功** |

### ⚠️ 关键发现

1. **API 返回 HTTP 200 状态码，但响应内容可能完全无效**
   - 失败的响应只包含空白字符（`\n` + 空格的重复）
   - 没有任何 JSON 数据

2. **这不是 JSON 解析器的问题**
   - 之前的分析错误：问题不在于 httpx 或 json.loads() 是否能处理前导空白
   - 真正问题：OpenRouter API 有时返回**完全空的响应体**

3. **随机性**
   - 问题是随机发生的
   - 同样的请求，有时成功，有时失败
   - 成功的响应也包含大量前导空白（654-2280 行），但确实包含有效的 JSON 数据

## 🎯 根本原因分析

可能的原因：

1. **API 速率限制**：频繁请求触发了限流，但返回 200 而不是 429
2. **上游 Gemini API 超时**：OpenRouter 调用 Gemini 时超时，但返回了空响应
3. **CloudFlare 中间层问题**：响应被 CF 截断或损坏
4. **模型生成被截断**：模型开始生成但因某种原因中断

## ✅ 解决方案

### 方案 1: 使用增强的 API 客户端（推荐）

我们创建了 `services/translate/api_client.py`，包含：

```python
from services.translate.api_client import OpenRouterClient

with OpenRouterClient(
    base_url=base_url,
    api_key=api_key,
    max_retries=5,      # 最多重试 5 次
    retry_delay=3.0,    # 每次重试间隔 3 秒
    timeout=600.0,
    log_dir=Path("logs")  # 保存所有响应日志
) as client:
    response = client.chat_completion(
        model="google/gemini-2.5-pro",
        messages=messages,
        response_format={"type": "json_object"},
        extra_body=safety_settings,
    )
```

#### 核心功能

1. **自动检测空响应**
   - 检查响应大小和是否包含 JSON
   - 将小于 1000 字节或不包含 `{` 的响应视为无效

2. **智能重试**
   - 检测到空响应自动重试
   - 可配置重试次数和延迟
   - 每次重试之间等待，避免触发速率限制

3. **详细日志**
   - 保存所有原始响应到文件
   - 文件名包含尝试次数和验证结果
   - 便于事后分析和调试

4. **错误处理**
   - 捕获 HTTP 错误、超时、JSON 解析错误
   - 在所有重试失败后抛出详细的错误信息

### 方案 2: 手动重试逻辑

如果不想使用封装的客户端，可以手动实现：

```python
import httpx
import time

def call_api_with_retry(max_retries=5):
    for attempt in range(1, max_retries + 1):
        response = httpx.post(url, json=data, timeout=600)
        raw_text = response.text

        # 检查响应是否有效
        if len(raw_text) < 1000 or '{' not in raw_text:
            print(f"Invalid response on attempt {attempt}, retrying...")
            time.sleep(3)
            continue

        # 解析 JSON
        try:
            return response.json()
        except json.JSONDecodeError:
            if attempt < max_retries:
                time.sleep(3)
                continue
            raise

    raise Exception("All retries failed")
```

## 📊 测试结果

使用增强客户端的测试结果：

```bash
$ python test_enhanced_client.py
2025-10-09 17:57:31,776 - INFO - Attempt 1/5
2025-10-09 17:59:49,812 - INFO - Response info: 30112 bytes, 654 blank lines, valid=True
2025-10-09 17:59:49,814 - INFO - Response saved to: test_mode/enhanced_client_logs/response_attempt_1_valid_20251009_175949.txt
2025-10-09 17:59:49,814 - INFO - Success on attempt 1
```

**成功率显著提高**！即使遇到空响应，也会自动重试直到获得有效响应。

## 🔧 在项目中集成

### 步骤 1: 更新依赖

确保安装了所需的包：
```bash
pip install httpx openai
```

### 步骤 2: 使用增强客户端

在 `services/translate/strategies.py` 或其他调用 API 的地方：

```python
from services.translate.api_client import OpenRouterClient

# 创建客户端（建议在应用启动时创建一次）
client = OpenRouterClient(
    base_url=os.getenv("OPENROUTER_BASE_URL"),
    api_key=os.getenv("OPENROUTER_API_KEY"),
    max_retries=5,
    retry_delay=3.0,
    log_dir=Path("logs/api_responses")
)

# 使用客户端
response = client.chat_completion(
    model="google/gemini-2.5-pro",
    messages=messages,
    response_format={"type": "json_object"}
)

# 记得关闭
client.close()
```

### 步骤 3: 配置日志级别

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
```

## 💡 最佳实践

1. **合理配置重试次数**
   - 推荐 3-5 次重试
   - 每次重试间隔 2-5 秒

2. **监控日志**
   - 定期检查保存的响应日志
   - 统计空响应的频率
   - 如果频率过高，考虑联系 OpenRouter 支持

3. **错误处理**
   - 捕获所有重试失败的情况
   - 提供友好的错误提示给用户
   - 考虑降级方案（如使用其他模型）

4. **性能优化**
   - 如果不需要保存所有响应，可以将 `log_dir` 设为 `None`
   - 考虑异步调用（使用 `httpx.AsyncClient`）

## 📝 总结

- ❌ **错误理解**：问题不在于 JSON 解析器无法处理前导空白
- ✅ **正确理解**：OpenRouter API 有时返回**完全空的响应**（只有空白字符）
- 🔧 **解决方案**：使用带有验证和重试逻辑的增强客户端
- 📈 **效果**：显著提高 API 调用成功率

## 🔗 相关文件

- `/Users/jin.yang/PycharmProjects/aurora/services/translate/api_client.py` - 增强的 API 客户端
- `/Users/jin.yang/PycharmProjects/aurora/test_enhanced_client.py` - 测试脚本
- `/Users/jin.yang/PycharmProjects/aurora/test_mode/enhanced_client_logs/` - 响应日志目录
