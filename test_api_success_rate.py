"""
批量测试 OpenRouter API 成功率
统计在多次调用中的成功率和平均重试次数
"""
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import dotenv
from services.translation.api_client import OpenRouterClient

from services.translation.prompts import CORRECT_SUBTITLE_SYSTEM_PROMPT, CORRECT_SUBTITLE_USER_QUERY

# 配置日志
logging.basicConfig(
    level=logging.WARNING,  # 只显示警告和错误
    format='%(asctime)s - %(levelname)s - %(message)s'
)

dotenv.load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
base_url = os.getenv("OPENROUTER_BASE_URL")

# 读取测试文件
test_file = Path("test_mode/PRED-726-uncensored-nyap2p.com.srt")
test_srt = test_file.read_text(encoding="utf-8")

# 使用较小的测试样本以加快测试
lines = test_srt.split("\n\n")
# 只使用前 100 个字幕块进行测试
test_subtitle = "\n\n".join(lines[:100])

metadata = {
    "director_jp": "きとるね川口",
    "director_zh": "基托鲁内 川口",
    "actors_jp": ["星宮一花"],
    "actors_zh": ["星宫一花"],
    "categories_jp": ["單體作品", "紧缚", "多P", "中出", "深喉", "女檢察官", "DMM獨家", "高畫質"],
    "categories_zh": ["单体作品", "紧缚", "多P", "中出", "深喉", "女检察官", "DMM独家", "高画质"]
}

# 构建消息
user_query = CORRECT_SUBTITLE_USER_QUERY.format(metadata=metadata, text=test_subtitle)
messages = [
    {"role": "system", "content": CORRECT_SUBTITLE_SYSTEM_PROMPT},
    {"role": "user", "content": user_query}
]

safety_settings = {
    "safety_settings": [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
}

# 测试配置
NUM_TESTS = 5  # 测试次数
MAX_RETRIES = 3  # 每次测试的最大重试次数

print("=" * 60)
print(f"API Success Rate Testing")
print("=" * 60)
print(f"Test subtitle size: {len(test_subtitle)} chars ({len(lines[:100])} blocks)")
print(f"Number of tests: {NUM_TESTS}")
print(f"Max retries per test: {MAX_RETRIES}")
print(f"Delay between tests: 5 seconds")
print("=" * 60)
print()

# 统计数据
results = []
total_attempts = 0
total_invalid_responses = 0

# 创建日志目录
log_dir = Path("test_mode/batch_test_logs")

for i in range(1, NUM_TESTS + 1):
    print(f"\n{'='*60}")
    print(f"Test {i}/{NUM_TESTS}")
    print(f"{'='*60}")

    start_time = time.time()

    with OpenRouterClient(
        base_url=base_url,
        api_key=api_key,
        max_retries=MAX_RETRIES,
        retry_delay=2.0,
        timeout=300.0,
        log_dir=log_dir / f"test_{i}"
    ) as client:
        try:
            # 记录原始的 logger，临时启用 INFO 级别以捕获重试信息
            api_logger = logging.getLogger('services.translation.api_client')
            original_level = api_logger.level
            api_logger.setLevel(logging.INFO)

            response = client.chat_completion(
                model="google/gemini-2.5-pro",
                messages=messages,
                response_format={"type": "json_object"},
                extra_body=safety_settings,
            )

            api_logger.setLevel(original_level)

            elapsed = time.time() - start_time

            # 提取内容
            content = response["choices"][0]["message"]["content"]
            finish_reason = response["choices"][0]["finish_reason"]

            result = {
                "test_num": i,
                "success": True,
                "elapsed_time": elapsed,
                "response_length": len(content),
                "finish_reason": finish_reason,
                "error": None
            }

            print(f"✅ SUCCESS in {elapsed:.1f}s")
            print(f"   Response: {len(content)} chars, finish: {finish_reason}")

        except Exception as e:
            elapsed = time.time() - start_time

            result = {
                "test_num": i,
                "success": False,
                "elapsed_time": elapsed,
                "response_length": 0,
                "finish_reason": None,
                "error": str(e)
            }

            print(f"❌ FAILED after {elapsed:.1f}s")
            print(f"   Error: {type(e).__name__}: {e}")

    results.append(result)

    # 等待一段时间再进行下一次测试
    if i < NUM_TESTS:
        print(f"\nWaiting 5 seconds before next test...")
        time.sleep(5)

# 统计结果
print(f"\n{'='*60}")
print(f"SUMMARY")
print(f"{'='*60}")

successes = sum(1 for r in results if r["success"])
failures = len(results) - successes
success_rate = (successes / len(results)) * 100 if results else 0

print(f"\nTotal tests: {len(results)}")
print(f"Successes: {successes}")
print(f"Failures: {failures}")
print(f"Success rate: {success_rate:.1f}%")

if successes > 0:
    avg_time = sum(r["elapsed_time"] for r in results if r["success"]) / successes
    print(f"Average response time (successful): {avg_time:.1f}s")

print(f"\nDetailed results:")
print(f"{'Test':<6} {'Status':<10} {'Time':<10} {'Response':<12} {'Finish':<10}")
print("-" * 60)

for r in results:
    status = "✅ SUCCESS" if r["success"] else "❌ FAILED"
    time_str = f"{r['elapsed_time']:.1f}s"
    response_str = f"{r['response_length']} chars" if r["success"] else "N/A"
    finish_str = r["finish_reason"] or "N/A"

    print(f"{r['test_num']:<6} {status:<10} {time_str:<10} {response_str:<12} {finish_str:<10}")

# 保存统计报告
report_file = log_dir / f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
with open(report_file, 'w') as f:
    f.write(f"API Success Rate Test Report\n")
    f.write(f"{'='*60}\n")
    f.write(f"Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write(f"Test subtitle size: {len(test_subtitle)} chars\n")
    f.write(f"Number of tests: {NUM_TESTS}\n")
    f.write(f"Max retries per test: {MAX_RETRIES}\n\n")
    f.write(f"Results:\n")
    f.write(f"  Total tests: {len(results)}\n")
    f.write(f"  Successes: {successes}\n")
    f.write(f"  Failures: {failures}\n")
    f.write(f"  Success rate: {success_rate:.1f}%\n\n")

    if successes > 0:
        f.write(f"  Average response time: {avg_time:.1f}s\n")

print(f"\nReport saved to: {report_file}")
print(f"Logs saved to: {log_dir}")
