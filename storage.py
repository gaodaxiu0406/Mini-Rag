import json
import os
import uuid
from datetime import datetime
from config import DATA_DIR

# 设置会话记录保存的位置
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
DOCSTORE_PATH = os.path.join(DATA_DIR, "docstore.json")
os.makedirs(SESSIONS_DIR, exist_ok=True)

# 读取JSON文件
def _load_json(path,default=None):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}

# 写入JSON文件
def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# 生成会话路径，下面的新建会话create_session需要用到
def get_session_path(session_id):
    return os.path.join(SESSIONS_DIR, f"{session_id}.json")

# 新建会话
def create_session(title=""):
    session_id = str(uuid.uuid4())[:8]
    session={
        "id": session_id,
        "title": title or f"会话 {session_id}",
        "created_at": datetime.now().isoformat(),
        "messages": []
    }
    # 保存
    _save_json(get_session_path(session_id), session)
    return session

# 读取单个会话
def get_session(session_id):
    path = get_session_path(session_id)
    if not os.path.exists(path):
        return None
    return _load_json(path)

# 更新会话
def save_session(session):
    _save_json(get_session_path(session["id"]), session)

# 列出所有会话
def list_sessions():
    sessions = []
    if not os.path.exists(SESSIONS_DIR):
        return sessions
    for fname in os.listdir(SESSIONS_DIR):
        if fname.endswith(".json"):
            s = _load_json(os.path.join(SESSIONS_DIR, fname))
            if s:
                sessions.append({
                    "id": s["id"],
                    "title": s["title"],
                    "created_at": s["created_at"],
                    "message_count": len(s.get("messages", [])),
                })
    # 根据会话时间，对当前的会话列表进行排序
    sessions.sort(key=lambda x: x["created_at"], reverse=True)
    return sessions

# 删除会话
def delete_session(session_id):
    path = get_session_path(session_id)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False

# —— —— 文档分块与入库 —— ——
def get_docstore():
    return _load_json(DOCSTORE_PATH, {"documents": {}, "chunks": []})

def save_docstore(docstore):
    _save_json(DOCSTORE_PATH, docstore)

# 添加文档
def add_document(filename, chunks):
    """添加一个文档及其所有chunk。chunks是列表，每一项 = {text, embedding}"""
    ds = get_docstore()
    # 当前文件id 随机生成
    doc_id = str(uuid.uuid4())[:8]
    ds["documents"][doc_id] = {
        "filename": filename,
        "chunk_count": len(chunks),
        "uploaded_at": datetime.now().isoformat()
    }
    for i, chunk in enumerate(chunks):
        ds["chunks"].append({
            "doc_id": doc_id,
            "filename": filename,
            "chunk_index": i,
            "text": chunk["text"],
            "embedding": chunk["embedding"]
        })
    save_docstore(ds)
    return doc_id

def update_chunk_embeddings(embeddings):
    """Replace all chunk embeddings and persist the docstore once."""
    ds = get_docstore()
    if len(embeddings) != len(ds["chunks"]):
        raise ValueError("Embedding count does not match the stored chunk count.")
    for chunk, embedding in zip(ds["chunks"], embeddings):
        chunk["embedding"] = embedding
    save_docstore(ds)

# 删除
def remove_document(filename):
    """按文件名删除文档及其所有chunk"""
    ds = get_docstore()
    ds["chunks"] = [c for c in ds["chunks"] if c["filename"] != filename]
    ds["documents"] = {
        k: v for k, v in ds["documents"].items() if v["filename"] != filename
    }
    save_docstore(ds)

def list_documents():
    """列出所有已入库的文档"""
    ds = get_docstore()
    return list(ds["documents"].values())

def get_all_chunks():
    """获取全部chunk，供检索使用"""
    ds = get_docstore()
    return ds["chunks"]