import json
import os
import tempfile
import uuid
import unicodedata
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
    directory = os.path.dirname(path)
    fd, temporary_path = tempfile.mkstemp(dir=directory, prefix=".json-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
        raise

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
        "updated_at": datetime.now().isoformat(),
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
    session["updated_at"] = datetime.now().isoformat()
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
                    "updated_at": s.get("updated_at", s["created_at"]),
                    "message_count": len(s.get("messages", [])),
                })
    # 根据会话时间，对当前的会话列表进行排序
    sessions.sort(
        key=lambda x: x.get("updated_at") or x["created_at"],
        reverse=True,
    )
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

def add_indexed_document(
    filename,
    chunk_texts,
    embeddings,
    text_length=None,
    chunk_size=None,
    chunk_overlap=None,
):
    """Add a document and its re-encoded chunks in one docstore write."""
    ds = get_docstore()
    ds["chunks"] = [
        chunk for chunk in ds["chunks"] if chunk.get("filename") != filename
    ]
    ds["documents"] = {
        doc_id: document
        for doc_id, document in ds["documents"].items()
        if document.get("filename") != filename
    }
    existing_count = len(ds["chunks"])
    if len(embeddings) != existing_count + len(chunk_texts):
        raise ValueError("Embedding count does not match the stored and new chunks.")

    for chunk, embedding in zip(ds["chunks"], embeddings[:existing_count]):
        chunk["embedding"] = embedding

    doc_id = str(uuid.uuid4())[:8]
    document = {
        "filename": filename,
        "chunk_count": len(chunk_texts),
        "uploaded_at": datetime.now().isoformat()
    }
    if text_length is not None:
        document["text_length"] = text_length
    if chunk_size is not None:
        document["chunk_size"] = chunk_size
    if chunk_overlap is not None:
        document["chunk_overlap"] = chunk_overlap
    ds["documents"][doc_id] = document
    for i, text in enumerate(chunk_texts):
        ds["chunks"].append({
            "doc_id": doc_id,
            "filename": filename,
            "chunk_index": i,
            "text": text,
            "embedding": embeddings[existing_count + i]
        })
    save_docstore(ds)
    return doc_id

# 删除
def remove_document(doc_id):
    """Remove one document and only the chunks belonging to its ID."""
    ds = get_docstore()
    if doc_id not in ds["documents"]:
        return False
    ds["chunks"] = [chunk for chunk in ds["chunks"] if chunk.get("doc_id") != doc_id]
    del ds["documents"][doc_id]
    save_docstore(ds)
    return True

def list_documents():
    """列出所有已入库的文档"""
    ds = get_docstore()
    return [
        {"id": doc_id, **document}
        for doc_id, document in ds["documents"].items()
    ]


def has_document(filename):
    normalized_name = unicodedata.normalize("NFC", filename).casefold()
    return any(
        unicodedata.normalize("NFC", document.get("filename", "")).casefold()
        == normalized_name
        for document in get_docstore()["documents"].values()
    )


def get_all_chunks():
    """获取全部chunk，供检索使用"""
    ds = get_docstore()
    return ds["chunks"]