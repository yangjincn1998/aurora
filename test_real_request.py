import os
from pathlib import Path

import dotenv
import openai

dotenv.load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
base_url = os.getenv("OPENROUTER_BASE_URL")

client = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=60)

# 读取测试文件
test_file = Path("test_mode/PRED-726-uncensored-nyap2p.com.srt")
test_srt = test_file.read_text(encoding="utf-8")

# 模拟切片
lines = test_srt.split("\n\n")
slice_size = 500
first_block = "\n\n".join(lines[:slice_size])

print(f"Total blocks: {len(lines)}")
print(f"First block size: {len(first_block)} chars")

# 构造消息
SYSTEM_PROMPT = """你是一个字幕校正引擎。请保持SRT格式输出修正后的字幕。"""

USER_QUERY = f"""<command>
请为我校正这份srt字幕
</command>
<metadata>
这部影片的来源是一部日本成人电影
{{"director_jp":"きとるね川口", "director_zh": "基托鲁内 川口", "actors_jp":["星宮一花"], "actors_zh":["星宫一花"]}}
</metadata>
<srt block to be processed>
{first_block}
</srt block to be processed>>"""

messages = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": USER_QUERY}
]

print(f"\nTotal message size: {len(SYSTEM_PROMPT) + len(USER_QUERY)} chars")

safety_settings = {
    "safety_settings": [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
}

print("\nSending request to API...")
try:
    response = client.chat.completions.create(
        model="google/gemini-2.5-pro",
        messages=messages,
        stream=False,
        extra_body=safety_settings
    )
    print("Response received, processing chunks...")
    chunk_count = 0
    content_length = 0
    for chunk in response:
        chunk_count += 1
        if chunk_count % 50 == 0:
            print(f"Chunk {chunk_count}...")
        if chunk.choices and chunk.choices[0].delta.content:
            content_length += len(chunk.choices[0].delta.content)
        if chunk.choices and chunk.choices[0].finish_reason:
            print(f"Finish reason: {chunk.choices[0].finish_reason}")
            break
    print(f"Success! Total chunks: {chunk_count}, content length: {content_length}")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
