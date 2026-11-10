import os
from openai import OpenAI

import config

_clients = {}

def get_client(api_key=None):
    key = api_key or config.DEEPSEEK_API_KEY
    if not key:
        raise ValueError("未配置 DeepSeek API Key，请登录后输入密钥。")
    if key not in _clients:
        _clients[key] = OpenAI(api_key=key, base_url=config.DEEPSEEK_BASE_URL)
    return _clients[key]

# 对话方法
def chat_stream(messages):
    stream = get_client().chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=messages,
        stream=True,
        temperature=0.7,
        max_tokens=2048,
    )

    # 按照流式方式一个字节一个字节的返回
    for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            yield delta.content