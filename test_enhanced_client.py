"""
测试增强的 API 客户端
"""
import logging
import os
from pathlib import Path

import dotenv
from services.translation.api_client import OpenRouterClient

from services.translation.prompts import CORRECT_SUBTITLE_SYSTEM_PROMPT, CORRECT_SUBTITLE_USER_QUERY

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

dotenv.load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
base_url = os.getenv("OPENROUTER_BASE_URL")

# 读取测试文件
test_file = Path("test_mode/PRED-726-uncensored-nyap2p.com.srt")
test_srt = test_file.read_text(encoding="utf-8")

# 测试完整字幕
lines = test_srt.split("\n\n")
full_subtitle = test_srt

print(f"Total subtitle blocks: {len(lines)}")
print(f"Testing with FULL subtitle (no slicing)")
print(f"Full subtitle size: {len(full_subtitle)} chars\n")

# 使用与 test_orchestrator.py 一致的 metadata
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
print("Testing with enhanced API client...")
print("=" * 60)

# 使用增强的客户端
log_dir = Path("test_mode/enhanced_client_logs")
with OpenRouterClient(
    base_url=base_url,
    api_key=api_key,
    max_retries=5,  # 最多重试 5 次
    retry_delay=3.0,  # 每次重试间隔 3 秒
    timeout=600.0,
    log_dir=log_dir
) as client:
    try:
        response = client.chat_completion(
            model="google/gemini-2.5-pro",
            messages=messages,
            response_format={"type": "json_object"},
            extra_body=safety_settings,
        )

        # 提取内容
        content = response["choices"][0]["message"]["content"]
        finish_reason = response["choices"][0]["finish_reason"]

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
        output_file = Path("test_mode/enhanced_client_result.srt")
        output_file.write_text(content, encoding="utf-8")
        print(f"\nResult saved to: {output_file}")

        # 尝试解析 JSON
        try:
            import json
            parsed = json.loads(content)
            print(f"\nJSON structure:")
            print(f"  - success: {parsed.get('success')}")
            print(f"  - has content: {'content' in parsed}")
            if 'content' in parsed:
                print(f"  - content length: {len(parsed['content'])} chars")
        except json.JSONDecodeError as je:
            print(f"\nWarning: Response is not valid JSON: {je}")

    except Exception as e:
        print(f"\n{'='*60}")
        print(f"FAILED!")
        print(f"{'='*60}")
        print(f"Error: {type(e).__name__}: {e}")

        import traceback
        traceback.print_exc()

print("\nTest completed!")
print(f"Logs saved to: {log_dir}")
