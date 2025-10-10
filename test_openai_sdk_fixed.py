"""
测试使用 OpenAI SDK 并配置自定义 HTTP 客户端来避免空行问题
"""
import os
import dotenv
import openai
import httpx
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

# 方法 1: 使用自定义 httpx 客户端 (推荐)
print("=" * 60)
print("Method 1: Using custom httpx client with OpenAI SDK")
print("=" * 60)

# 创建自定义 httpx 客户端,配置更宽松的解析规则
custom_http_client = httpx.Client(
    timeout=httpx.Timeout(600.0, connect=60.0),
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
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

    print(f"\nSuccess!")
    print(f"Finish reason: {finish_reason}")
    print(f"Response length: {len(content)} chars")
    print(f"\nFirst 500 chars of response:")
    print("-" * 60)
    print(content[:500])
    print("-" * 60)

    # 保存结果
    output_file = Path("test_mode/openai_sdk_fixed_result.srt")
    output_file.write_text(content, encoding="utf-8")
    print(f"\nResult saved to: {output_file}")

except Exception as e:
    print(f"\nError: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

finally:
    # 关闭自定义客户端
    custom_http_client.close()
