import os
from openai import OpenAI

import config

# 创建全局
_client = None

def get_client():
    global _client
    if _client is None:
        key = config.DEEPSEEK_API_KEY
        if not key:
            raise ValueError("DEEPSEEK_API_KEY 未配置，请先创建 .env 文件并设置 DEEPSEEK_API_KEY")
        _client = OpenAI(api_key=key, base_url=config.DEEPSEEK_BASE_URL)
    return _client

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