from llm import chat_stream

def main():
    print("deepseek 控制台对话，输入exit退出")
    messages = [
      {"role": "system", "content": "你是助手，请用简体中文回答用户的问题。"}
    ]
    while True:
        user_input = input("用户: ").strip()
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            print("退出对话。")
            break
        messages.append({"role": "user", "content": user_input})
        print("助手: ", end="", flush=True)
        full_answer = ""
        for token in chat_stream(messages):
            print(token, end="", flush=True)
            full_answer += token
        print()  # 换行

        messages.append({"role": "assistant", "content":full_answer})

if __name__ == "__main__":
    main()