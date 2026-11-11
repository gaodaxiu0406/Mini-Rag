from flask import Flask, request, jsonify, Response, send_from_directory

import json
import config
import llm
import storage
import rag
from document_parser import extract_document_text

app = Flask(__name__, static_folder='static', static_url_path='')

@app.route('/')
def index():
    return send_from_directory("static", "index.html")

@app.route('/favicon.ico')
def favicon():
    return Response(status=204)

@app.route('/api/app-config', methods=['GET'])
def get_app_config():
    return jsonify({
        "has_server_api_key": bool(config.DEEPSEEK_API_KEY),
        "display_max_chars": config.CHAT_DISPLAY_MAX_CHARS,
    })

# 会话接口
@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    # 会话功能
    return jsonify(storage.list_sessions())

# 创建新的会话消息
@app.route('/api/sessions', methods=['POST'])
def new_sessions():
    data = request.get_json(silent=True) or {}
    title = data.get("title", "").strip() or None
    # 调用创建会话方法 返回一个会话实例session
    session = storage.create_session(title)
    return jsonify(session)

# 获取一个单个会话的详细信息
@app.route('/api/sessions/<session_id>', methods=['GET'])
def get_session(session_id):
    s = storage.get_session(session_id)
    if not s:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(s)

# 删除一个会话
@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    ok = storage.delete_session(session_id)
    if not ok:
        return jsonify({"error": "Session not found"}), 404
    return jsonify({"删除": True})

# —— —— 对话接入检索 —— ——
def _build_system_prompt(context_texts, use_knowledge_base=True):
    if context_texts:
        ctx = "\n---\n".join(chunk["text"] for chunk in context_texts)
        return (
            "你是一个通用知识库助手。仅根据提供的参考资料回答；资料未提供答案时，请明确说明，不要编造。"
            "保留资料中的关键术语、名称、编号、条件、限制和引用，不要混淆不同条目中的信息。"
            "仅报告实际检索到的内容，不要声称已覆盖整个文档。\n\n"
            f"【参考资料】\n{ctx}"
        )
    if not use_knowledge_base:
        return "你是一个有帮助的 AI 助手，请直接使用通用知识回答用户问题。"
    return "你是一个知识库助手。知识库当前为空，请告知用户先上传文档。"


def _messages_with_history(history_messages, query, system):
    messages = [{"role": "system", "content": system}]
    role_aliases = {
        "msg--user": "user",
        "msg--ai": "assistant",
        "用户": "user",
        "助手": "assistant",
    }
    for message in history_messages:
        role = role_aliases.get(message["role"], message["role"])
        messages.append({"role": role, "content": message["content"]})
    messages.append({"role": "user", "content": query})
    return messages


def _text_batches(texts, max_chars):
    batches = []
    current = []
    current_length = 0
    for text in texts:
        if current and current_length + len(text) > max_chars:
            batches.append("\n\n---\n\n".join(current))
            current = []
            current_length = 0
        current.append(text)
        current_length += len(text)
    if current:
        batches.append("\n\n---\n\n".join(current))
    return batches


def _complete_summary(messages, api_key=None):
    response = llm.get_client(api_key).chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=messages,
        stream=False,
        temperature=config.DEEPSEEK_TEMPERATURE,
        max_tokens=config.RETRIEVAL_BATCH_MAX_TOKENS,
        extra_body={"thinking": {"type": "disabled"}},
    )
    if not response.choices:
        raise RuntimeError("模型未返回批次归纳结果。")
    text = response.choices[0].message.content
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("模型返回了空的批次归纳结果。")
    return text.strip()


def _summarize_full_document(retrieved, query, history_messages, api_key=None):
    chunk_texts = [
        (
            f"【文件：{chunk.get('filename', '未知')}；"
            f"片段：{chunk.get('chunk_index', index)}】\n"
            f"{chunk['text']}"
        )
        for index, chunk in enumerate(retrieved, 1)
    ]
    batches = _text_batches(chunk_texts, config.RETRIEVAL_BATCH_CHARS)
    summaries = []
    for index, batch in enumerate(batches, 1):
        yield {
            "type": "progress",
            "text": f"已检索到 {len(retrieved)} 个片段，正在分批分析第 {index}/{len(batches)} 批。",
        }
        summary = _complete_summary([
            {
                "role": "system",
                "content": (
                    "你是一个通用知识库资料归纳助手。只保留与用户问题直接相关的内容；"
                    "保留原文中的关键术语、名称、编号、条件、限制和引用，并区分不同对象或条目。"
                    "不得补充原文没有的信息。"
                    "若本批无相关资料，只输出 NO_RELEVANT_INFO。"
                ),
            },
            {
                "role": "user",
                "content": f"问题：{query}\n\n请分析以下手册片段：\n{batch}",
            },
        ], api_key)
        if summary != "NO_RELEVANT_INFO":
            summaries.append(summary)

    previous_length = len("\n\n".join(summaries))
    while previous_length > config.RETRIEVAL_BATCH_CHARS:
        summary_batches = _text_batches(summaries, config.RETRIEVAL_BATCH_CHARS)
        reduced = []
        for index, batch in enumerate(summary_batches, 1):
            yield {
                "type": "progress",
                "text": f"正在合并第 {index}/{len(summary_batches)} 组归纳结果。",
            }
            reduced.append(_complete_summary([
                {
                    "role": "system",
                    "content": (
                        "合并这些知识库资料归纳。保留所有不同对象或条目的关键信息、条件、限制和引用；"
                        "不得混淆其差异或编造内容。"
                    ),
                },
                {"role": "user", "content": batch},
            ], api_key))
        reduced_length = len("\n\n".join(reduced))
        if reduced_length >= previous_length:
            raise RuntimeError("批次归纳结果未能缩短，无法在模型上下文限制内继续。")
        summaries = reduced
        previous_length = reduced_length

    if not summaries:
        answer_system = (
            "你是一个通用知识库助手。已检查相关文档的全部片段，但没有找到与问题直接相关的内容。"
            "请如实告知用户，并建议核对问题描述或资料；不得编造答案。"
        )
    else:
        summary_context = "\n\n---\n\n".join(summaries)
        answer_system = (
            "你是一个通用知识库助手。以下内容是对相关文档全部片段进行分批分析后的归纳。"
            "仅根据归纳资料回答，保留相关对象或条目之间的区别，不得编造。"
            "资料未覆盖的内容必须明确说明。\n\n"
            f"【分批归纳资料】\n{summary_context}"
        )

    messages = _messages_with_history(history_messages, query, answer_system)
    stream = llm.get_client(api_key).chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=messages,
        stream=True,
        temperature=config.DEEPSEEK_TEMPERATURE,
        max_tokens=config.DEEPSEEK_MAX_TOKENS,
        extra_body={"thinking": {"type": "disabled"}},
    )
    has_content = False
    try:
        for chunk in stream:
            if not chunk.choices:
                continue
            text = chunk.choices[0].delta.content
            if isinstance(text, str) and text:
                has_content = True
                yield {"type": "content", "text": text}
    finally:
        stream.close()
    if not has_content:
        raise RuntimeError("模型未返回最终回答内容。")


# —— —— 聊天接口（SSE流式）—— ——
# —— ——对话接入检索 加形参top_k
def _stream_chat(
    history_messages,
    query,
    top_k=None,
    use_knowledge_base=True,
    full_document_search=False,
    api_key=None,
):
    stream = None
    try:
        if use_knowledge_base:
            retrieved, _ = rag.retrieve(
                query,
                top_k=top_k,
                full_document_search=full_document_search,
            )
        else:
            retrieved = []
        full_document_match = bool(
            retrieved and retrieved[0].get("_retrieval_mode") == "full_document"
        )
        yield f"data: {json.dumps({'type': 'meta', 'retrieved_count': len(retrieved)}, ensure_ascii=False)}\n\n"
        if not full_document_match:
            progress = {
                "type": "progress",
                "text": f"已检索到 {len(retrieved)} 个片段，正在分批分析第 1/1 批。",
            }
            yield f"data: {json.dumps(progress, ensure_ascii=False)}\n\n"
        if not api_key and not config.DEEPSEEK_API_KEY:
            if not retrieved:
                answer = "未配置 DeepSeek API Key，当前仅支持本地知识库检索；知识库中也没有找到相关片段。"
            else:
                snippets = retrieved[:8]
                answer = (
                    "未配置 DeepSeek API Key，当前仅展示本地知识库检索结果。"
                    "登录 DeepSeek 后可生成完整回答。\n\n"
                    +                     "\n\n---\n\n".join(
                        f"【{chunk.get('filename', '未知文件')}】\n"
                        f"{chunk.get('text', '')[:1200]}"
                        for chunk in snippets
                    )
                )
            yield f"data: {json.dumps({'type': 'content', 'text': answer}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return
        if full_document_match:
            has_content = False
            events = _summarize_full_document(retrieved, query, history_messages, api_key)
            try:
                for event in events:
                    if event["type"] == "content":
                        has_content = True
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            finally:
                events.close()
            if not has_content:
                raise RuntimeError("模型未返回最终回答内容。")
            yield "data: [DONE]\n\n"
            return

        system = _build_system_prompt(retrieved, use_knowledge_base)
        messages = _messages_with_history(history_messages, query, system)

        stream = llm.get_client(api_key).chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=messages,
            stream=True,
            temperature=config.DEEPSEEK_TEMPERATURE,
            max_tokens=config.DEEPSEEK_MAX_TOKENS,
            extra_body={"thinking": {"type": "disabled"}},
        )

        has_content = False
        saw_reasoning = False
        finish_reason = None
        for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if getattr(delta, "reasoning_content", None):
                saw_reasoning = True
            if choice.finish_reason:
                finish_reason = choice.finish_reason
            text = delta.content
            if isinstance(text, str) and text:
                has_content = True
                payload = json.dumps({"type": "content", "text": text}, ensure_ascii=False)
                yield f"data: {payload}\n\n"

        if not has_content:
            if saw_reasoning:
                message = "模型只返回了推理过程，没有生成最终答案。"
            else:
                message = "模型没有返回文本内容"
            if finish_reason:
                message += f"（结束原因：{finish_reason}）"
            payload = json.dumps({"type": "error", "message": message}, ensure_ascii=False)
            yield f"data: {payload}\n\n"

    except Exception as e:
        payload = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
        yield f"data: {payload}\n\n"
    finally:
        if stream is not None:
            stream.close()
    yield "data: [DONE]\n\n"


@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    data = request.get_json(force=True)
    # 获取用户输入的消息和会话ID
    query = data.get("message", "").strip()
    session_id = data.get("session_id", "").strip()
    use_knowledge_base = data.get("use_knowledge_base", True) is True
    full_document_search = data.get("full_document_search", False) is True
    api_key = request.headers.get("X-DeepSeek-API-Key", "").strip() or None

    # 如果没有当前会话
    if not query:
        # 返回空消息
        return jsonify({"error": "empty message"}), 400
    if not use_knowledge_base and not (api_key or config.DEEPSEEK_API_KEY):
        return jsonify({"error": "请先登录并配置 DeepSeek API Key，或切换到知识库问答。"}), 401
    # 没传session_id 或 session不存在 → 自动创建
    if not session_id:
        s = storage.create_session()
        session_id = s["id"]
    elif not storage.get_session(session_id):
        s = storage.create_session()
        session_id = s["id"]

    # 内部方法：生成器
    def generate():
        session = storage.get_session(session_id)
        # 获取当前会话的历史消息
        history = session.get("messages", []) if session else []

        # 定义完整回复
        full_answer = ""
        failed = False

        # 详细处理SSE每一段消息
        events = _stream_chat(
            history,
            query,
            use_knowledge_base=use_knowledge_base,
            full_document_search=full_document_search,
            api_key=api_key,
        )
        try:
            for sse_line in events:
                raw = sse_line.removeprefix("data: ").strip()
                if raw and raw != "[DONE]":
                    event = json.loads(raw)
                    if event.get("type") == "content":
                        full_answer += event.get("text", "")
                    elif event.get("type") == "error":
                        failed = True
                yield sse_line
        finally:
            events.close()

        if failed or not session:
            return

        # 将会话追踪到消息列表中
        session["messages"].append({"role": "user", "content": query})
        session["messages"].append({"role": "assistant", "content": full_answer})

        if not session.get("title") or session["title"].startswith("会话 "):
            # 将会话的前30个字符作为标题使用,如果超过30个字符就用...代替
            session["title"] = query[:30]+("..." if len(query)>30 else "")
        # 最终会话存储到消息列表中
        storage.save_session(session)

    # 返回响应
    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

# @app.route('/api/documents', methods=['GET'])
# def list_documents():
#     # 文档功能
#     return jsonify([])

# —— —— 新增文档的REST接口 —— ——
@app.route('/api/documents', methods=['GET'])
def list_documents():
    return jsonify(storage.list_documents())

@app.route('/api/documents/upload', methods=['POST'])
def upload_document():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    f = request.files['file']
    if not f.filename:
        return jsonify({"error": "No filename"}), 400
    if storage.has_document(f.filename):
        return jsonify({
            "error": f"文件“{f.filename}”已存在（文件名和类型相同），请勿重复上传。"
        }), 409

    try:
        content = extract_document_text(f.filename, f.read())
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    count = rag.index_document(f.filename, content)
    return jsonify({"filename": f.filename, "chunk_count": count})

@app.route('/api/documents/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    if not storage.remove_document(doc_id):
        return jsonify({"error": "Document not found"}), 404
    return jsonify({"deleted": doc_id})

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8000, debug=True)