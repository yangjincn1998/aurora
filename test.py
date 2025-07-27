import httpx
from openai import OpenAI

# --- 您的配置 ---
api_key = os.environ.get("OPENAI_API_KEY")
base_url = "https://api.qdgf.top/v1"
model_name = "gemini-2.5-pro"
# -----------------

# --- 伪装的请求头 ---
# 我们将使用一个看起来像普通浏览器的 "名牌" (User-Agent)
custom_headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}
# --------------------

custom_client = None  # 先声明变量
try:
    print("\n正在初始化客户端 (已禁用SSL验证并设置自定义User-Agent)...")

    # 1. 创建一个不验证SSL证书的 httpx 客户端 (解决连接问题)
    custom_client = httpx.Client(verify=False)

    # 2. 初始化 OpenAI 客户端，同时传入自定义 http_client 和伪装的请求头
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        http_client=custom_client,  # <--- SSL证书修复
        default_headers=custom_headers  # <--- Cloudflare防火墙修复
    )

    print("正在向服务器发送请求...")

    chat_completion = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "user", "content": "你好，用一个词回答，你是什么？"}
        ],
        stream=False,
    )

    print("✅ 成功接收到响应！")

    assistant_reply = chat_completion.choices[0].message.content
    print("\n模型回复内容:")
    print("--------------")
    print(assistant_reply)
    print("--------------")

except Exception as e:
    print(f"\n❌ 请求发生错误！")
    print("-----------------")
    print(f"错误类型: {type(e).__name__}")
    print(f"错误详情: {e}")
    print("-----------------")
finally:
    # 确保在使用完后关闭客户端连接
    if custom_client and not custom_client.is_closed:
        custom_client.close()
        print("\n客户端连接已关闭。")