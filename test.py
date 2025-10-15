from openai import OpenAI
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key="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")

result=client.chat.completions.create(
    model="qwen/qwen3-235b-a22b:free",
    messages=[{"role": "user", "content": "写一个关于春天的诗歌"}],
)

print(result.choices[0].message.content)

