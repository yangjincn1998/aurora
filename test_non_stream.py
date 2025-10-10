"""
测试非流式请求，使用与 main.py 完全一致的提示词
"""
import os
import dotenv
import openai
import httpx
import json
from pathlib import Path
from services.translate.prompts import CORRECT_SUBTITLE_SYSTEM_PROMPT, CORRECT_SUBTITLE_USER_QUERY

dotenv.load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
base_url = os.getenv("OPENROUTER_BASE_URL")

# 读取测试文件
test_file = Path("test_mode/PRED-726-uncensored-nyap2p.com.srt")
test_srt = test_file.read_text(encoding="utf-8")

# 测试完整字幕（不切片）
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

# 构建与 strategies.py 完全一致的消息
user_query = CORRECT_SUBTITLE_USER_QUERY.format(metadata=metadata, text=full_subtitle)
messages = [
    {"role": "system", "content": CORRECT_SUBTITLE_SYSTEM_PROMPT},
    {"role": "user", "content": user_query}
]

print(f"System prompt length: {len(CORRECT_SUBTITLE_SYSTEM_PROMPT)} chars")
print(f"User query length: {len(user_query)} chars\n")

# 创建客户端
client = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=600)

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
print("Testing NON-STREAMING request...")
print("=" * 60)

# 使用 httpx 直接发送请求以捕获原始响应
try:
    # 构建请求体
    request_body = {
        "model": "google/gemini-2.5-pro",
        "messages": messages,
        "stream": False,
        "response_format": {"type": "json_object"},
        **safety_settings
    }

    # 使用 httpx 发送请求
    with httpx.Client(timeout=600) as http_client:
        response = http_client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json=request_body
        )

        print(f"\nHTTP Status Code: {response.status_code}")
        print(f"Response Headers:")
        for key, value in response.headers.items():
            print(f"  {key}: {value}")

        print(f"\nRaw Response (first 2000 chars):")
        print("=" * 60)
        raw_text = response.text
        print(raw_text[:2000])
        print("=" * 60)

        # 保存完整原始响应
        raw_file = Path("test_mode/raw_response.txt")
        raw_file.write_text(raw_text, encoding="utf-8")
        print(f"\nFull raw response saved to: {raw_file}")

        # 尝试解析 JSON
        try:
            data = response.json()
            print(f"\nJSON parsed successfully!")
            print(f"Response structure: {json.dumps(data, indent=2, ensure_ascii=False)[:1000]}")

            if "choices" in data and len(data["choices"]) > 0:
                content = data["choices"][0]["message"]["content"]
                finish_reason = data["choices"][0]["finish_reason"]

                print(f"\nSuccess!")
                print(f"Finish reason: {finish_reason}")
                print(f"Response length: {len(content)} chars")
                print(f"\nFirst 500 chars of response:")
                print("-" * 60)
                print(content[:500])
                print("-" * 60)

                # 保存结果
                output_file = Path("test_mode/non_stream_full_result.srt")
                output_file.write_text(content, encoding="utf-8")
                print(f"\nResult saved to: {output_file}")
            else:
                print(f"\nUnexpected response format: {data}")

        except json.JSONDecodeError as je:
            print(f"\nJSON Decode Error: {je}")
            print(f"Error at line {je.lineno}, column {je.colno}, position {je.pos}")
            if je.pos > 0:
                start = max(0, je.pos - 100)
                end = min(len(raw_text), je.pos + 100)
                print(f"\nContext around error position:")
                print(raw_text[start:end])

except Exception as e:
    print(f"\nError: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
