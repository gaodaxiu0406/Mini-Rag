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
        ctx = "\n---\n".join(context_texts)
        return (
            "你是一个知识库助手。请仅根据以下资料回答用户问题，"
            "如果资料中没有答案，请如实告知用户，而不要编造答案。\n\n"
            f"【参考资料】\n{ctx}"
        )
    if not use_knowledge_base:
        return "你是一个有帮助的 AI 助手，请直接使用通用知识回答用户问题。"
    return "你是一个知识库助手。知识库当前为空，请告知用户先上传文档。"

# —— —— 聊天接口（SSE流式）—— ——
# —— ——对话接入检索 加形参top_k
def _stream_chat(history_messages, query, top_k=None, use_knowledge_base=True):
    try:
        if use_knowledge_base:
            if top_k is None:
                top_k = config.RETRIEVAL_TOP_K
            retrieved, scores = rag.retrieve(query, top_k=top_k)
        else:
            retrieved, scores = [], []
        context_texts = [c["text"] for c in retrieved]
        system = _build_system_prompt(context_texts, use_knowledge_base)

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

        stream = llm.get_client().chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=messages,
            stream=True,
            temperature=config.DEEPSEEK_TEMPERATURE,
            max_tokens=config.DEEPSEEK_MAX_TOKENS,
        )

        # 先发检索元信息
        yield f"data: {json.dumps({'type': 'meta', 'retrieved': context_texts, 'scores': scores}, ensure_ascii=False)}\n\n"

        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                text = delta.content
                payload = json.dumps({"type": "content", "text": text}, ensure_ascii=False)
                yield f"data: {payload}\n\n"

        yield "data: [DONE]\n\n"

    except Exception as e:
        payload = json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False)
        yield f"data: {payload}\n\n"
    finally:
        yield "data: [DONE]\n\n"


@app.route('/api/chat/stream', methods=['POST'])
def chat_stream():
    data = request.get_json(force=True)
    # 获取用户输入的消息和会话ID
    query = data.get("message", "").strip()
    session_id = data.get("session_id", "").strip()
    use_knowledge_base = data.get("use_knowledge_base", True) is True

    # 如果没有当前会话
    if not query:
        # 返回空消息
        return jsonify({"error": "empty message"}), 400

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
        for sse_line in _stream_chat(
            history, query, use_knowledge_base=use_knowledge_base
        ):
            raw = sse_line.removeprefix("data: ").strip()
            if raw and raw != "[DONE]":
                event = json.loads(raw)
                if event.get("type") == "content":
                    full_answer += event.get("text", "")
                elif event.get("type") == "error":
                    failed = True
            yield sse_line

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

    try:
        content = extract_document_text(f.filename, f.read())
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    count = rag.index_document(f.filename, content)
    return jsonify({"filename": f.filename, "chunk_count": count})

@app.route('/api/documents/<filename>', methods=['DELETE'])
def delete_document(filename):
    storage.remove_document(filename)
    return jsonify({"deleted": filename})

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8000, debug=True)