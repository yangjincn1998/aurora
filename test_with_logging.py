"""
测试并记录完整的 HTTP 请求和响应
使用 httpx 事件钩子来捕获原始报文
"""
import os
import dotenv
import openai
import httpx
import json
from pathlib import Path
from datetime import datetime
from services.translate.prompts import CORRECT_SUBTITLE_SYSTEM_PROMPT, CORRECT_SUBTITLE_USER_QUERY

dotenv.load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
base_url = os.getenv("OPENROUTER_BASE_URL")

# 创建日志目录
log_dir = Path("test_mode/http_logs")
log_dir.mkdir(parents=True, exist_ok=True)

# 全局变量用于记录响应
response_log = {
    "timestamp": None,
    "request": {},
    "response": {},
    "raw_response_text": None,
    "error": None
}

def log_request(request: httpx.Request):
    """记录请求信息"""
    print(f"\n{'='*60}")
    print(f"REQUEST to {request.url}")
    print(f"{'='*60}")
    print(f"Method: {request.method}")
    print(f"Headers:")
    for key, value in request.headers.items():
        if key.lower() == 'authorization':
            print(f"  {key}: Bearer ***REDACTED***")
        else:
            print(f"  {key}: {value}")

    response_log["timestamp"] = datetime.now().isoformat()
    response_log["request"] = {
        "method": request.method,
        "url": str(request.url),
        "headers": dict(request.headers),
    }

    # 尝试记录请求体（如果有）
    try:
        if request.content:
            body = request.content.decode('utf-8')
            response_log["request"]["body_size"] = len(body)
            print(f"\nRequest body size: {len(body)} bytes")
    except Exception as e:
        print(f"Could not decode request body: {e}")

def log_response(response: httpx.Response):
    """记录响应信息"""
    print(f"\n{'='*60}")
    print(f"RESPONSE from {response.url}")
    print(f"{'='*60}")
    print(f"Status: {response.status_code}")
    print(f"Headers:")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")

    # 读取响应 - 必须先调用 read() 来读取流式响应
    response.read()

    # 读取原始响应文本
    raw_text = response.text
    print(f"\nResponse size: {len(raw_text)} bytes")
    print(f"Response starts with: {repr(raw_text[:200])}")

    # 统计前导空白行
    lines = raw_text.split('\n')
    blank_lines = 0
    for line in lines:
        if line.strip():
            break
        blank_lines += 1

    print(f"Leading blank lines: {blank_lines}")

    response_log["response"] = {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "body_size": len(raw_text),
        "leading_blank_lines": blank_lines,
    }
    response_log["raw_response_text"] = raw_text

    # 保存原始响应到文件
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_file = log_dir / f"raw_response_{timestamp}.txt"
    raw_file.write_text(raw_text, encoding='utf-8')
    print(f"\nRaw response saved to: {raw_file}")

    # 尝试找到 JSON 开始位置
    first_brace = raw_text.find('{')
    if first_brace > 0:
        print(f"\nFirst '{{' found at position: {first_brace}")
        print(f"Characters before first '{{': {repr(raw_text[:first_brace])}")

    # 保存详细日志
    log_file = log_dir / f"http_log_{timestamp}.json"
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(response_log, f, indent=2, ensure_ascii=False)
    print(f"Detailed log saved to: {log_file}")

# 读取测试文件
test_file = Path("test_mode/PRED-726-uncensored-nyap2p.com.srt")
test_srt = test_file.read_text(encoding="utf-8")

# 测试完整字幕
lines = test_srt.split("\n\n")
full_subtitle = test_srt

print(f"Total subtitle blocks: {len(lines)}")
print(f"Testing with FULL subtitle (no slicing)")
print(f"Full subtitle size: {len(full_subtitle)} chars\n")

# 使用与 main.py 一致的 metadata
metadata = {
    "director_jp": "きとるね川口",
    "director_zh": "基托鲁内 川口",
    "actors_jp": ["星宮一花"],
    "actors_zh": ["星宫一花"],
    "categories_jp": ["單體作品", "紧缚", "多P", "中出", "深喉", "女檢察官", "DMM獨家", "高畫質"],
    "categories_zh": ["单体作品", "紧缚", "多P", "中出", "深喉", "女检察官", "DMM独家", "高画质"]
}

# 构建消息
user_query = CORRECT_SUBTITLE_USER_QUERY.format(metadata=metadata, text=full_subtitle)
messages = [
    {"role": "system", "content": CORRECT_SUBTITLE_SYSTEM_PROMPT},
    {"role": "user", "content": user_query}
]

print(f"System prompt length: {len(CORRECT_SUBTITLE_SYSTEM_PROMPT)} chars")
print(f"User query length: {len(user_query)} chars\n")

# 创建带有事件钩子的自定义 httpx 客户端
custom_http_client = httpx.Client(
    timeout=httpx.Timeout(600.0, connect=60.0),
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    event_hooks={
        'request': [log_request],
        'response': [log_response]
    }
)

# 使用自定义客户端创建 OpenAI 客户端
client = openai.OpenAI(
    base_url=base_url,
    api_key=api_key,
    http_client=custom_http_client
)

# 安全设置
safety_settings = {
    "safety_settings": [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
}

print("=" * 60)
print("Testing with HTTP logging enabled...")
print("=" * 60)

try:
    response = client.chat.completions.create(
        model="google/gemini-2.5-pro",
        messages=messages,
        stream=False,
        extra_body=safety_settings,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    finish_reason = response.choices[0].finish_reason

    print(f"\n{'='*60}")
    print(f"SUCCESS!")
    print(f"{'='*60}")
    print(f"Finish reason: {finish_reason}")
    print(f"Response length: {len(content)} chars")
    print(f"\nFirst 500 chars of response:")
    print("-" * 60)
    print(content[:500])
    print("-" * 60)

    # 保存结果
    output_file = Path("test_mode/logged_result.srt")
    output_file.write_text(content, encoding="utf-8")
    print(f"\nResult saved to: {output_file}")

    response_log["success"] = True
    response_log["parsed_content_length"] = len(content)

except json.JSONDecodeError as je:
    print(f"\n{'='*60}")
    print(f"JSON DECODE ERROR!")
    print(f"{'='*60}")
    print(f"Error: {je}")
    print(f"Error at line {je.lineno}, column {je.colno}, position {je.pos}")

    response_log["success"] = False
    response_log["error"] = {
        "type": "JSONDecodeError",
        "message": str(je),
        "lineno": je.lineno,
        "colno": je.colno,
        "pos": je.pos
    }

    # 如果有原始响应文本，显示错误位置附近的内容
    if response_log.get("raw_response_text"):
        raw_text = response_log["raw_response_text"]
        if je.pos > 0:
            start = max(0, je.pos - 200)
            end = min(len(raw_text), je.pos + 200)
            print(f"\nContext around error position {je.pos}:")
            print("=" * 60)
            print(repr(raw_text[start:end]))
            print("=" * 60)

    import traceback
    traceback.print_exc()

except Exception as e:
    print(f"\n{'='*60}")
    print(f"ERROR!")
    print(f"{'='*60}")
    print(f"Error: {type(e).__name__}: {e}")

    response_log["success"] = False
    response_log["error"] = {
        "type": type(e).__name__,
        "message": str(e)
    }

    import traceback
    traceback.print_exc()

finally:
    # 关闭客户端
    custom_http_client.close()

    # 最终保存完整日志
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_log = log_dir / f"complete_log_{timestamp}.json"
    with open(final_log, 'w', encoding='utf-8') as f:
        json.dump(response_log, f, indent=2, ensure_ascii=False)
    print(f"\nFinal complete log saved to: {final_log}")
