import pickle
import os
import re
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from scipy.sparse import csr_matrix
import config
from config import CHUNK_SIZE, CHUNK_OVERLAP, RETRIEVAL_TOP_K, DATA_DIR
import storage

VECTORIZER_PATH = os.path.join(DATA_DIR, "vectorizer.pkl")
MSN_PATTERN = re.compile(
  r"\bMSN\s*[:：]?\s*(\d{4,6})(?:\s*[-–—至]\s*(\d{4,6}))?",
  re.IGNORECASE,
)

_vectorizer = None


def extract_msn_ranges(text):
  ranges = []
  for line in text.splitlines():
    applicability_revision = re.search(r"修订为|改为|变更为", line)
    if "适用性" in line and applicability_revision:
      line = line[applicability_revision.end():]
    for match in MSN_PATTERN.finditer(line):
      start = int(match.group(1))
      end = int(match.group(2) or match.group(1))
      ranges.append((start, end))
  return list(dict.fromkeys(ranges))


def format_msn_ranges(ranges):
  return ", ".join(
    f"MSN {start:05d}" if start == end else f"MSN {start:05d}-{end:05d}"
    for start, end in ranges
  )

def _query_terms(query):
  normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", query.casefold())
  terms = re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]{2,}", normalized)
  stop_phrases = (
    "怎么办", "如何处理", "怎么处理", "是什么", "为什么", "请问", "故障", "问题",
    "如何", "怎么", "处理", "发生", "出现", "有没有", "相关", "手册",
  )
  keywords = []
  for term in terms:
    for stop_phrase in stop_phrases:
      term = term.replace(stop_phrase, " ")
    for keyword in re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]{2,}", term):
      if keyword not in keywords:
        keywords.append(keyword)
  return keywords


def _chunk_document_size(chunks, documents_by_filename):
  if not chunks:
    return 0
  filename = chunks[0].get("filename")
  metadata = documents_by_filename.get(filename, {})
  text_length = metadata.get("text_length")
  if isinstance(text_length, int):
    return text_length
  return sum(len(chunk.get("text", "")) for chunk in chunks)


def get_vectorizer():
  """获取全局TF-IDF向量器。首次调用从磁盘加载，没有则创建新的"""
  global _vectorizer
  if _vectorizer is not None:
    return _vectorizer
  if os.path.exists(VECTORIZER_PATH):
    with open(VECTORIZER_PATH, "rb") as f:
      _vectorizer = pickle.load(f)
  else:
    _vectorizer = TfidfVectorizer(
      analyzer = "char_wb",
      ngram_range = (2, 4),
      max_features = 10000
    )
  return _vectorizer

# 分块函数
def split_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
  """滑动窗口分块：每chunk_size字符一个块，相邻块重叠overlap字符"""
  text = text.strip()
  if not text: return []
  chunks = []
  start = 0
  while start < len(text):
    end = start + chunk_size
    chunk = text[start:end]
    chunks.append(chunk)
    start = end - overlap
    if start >= len(text):
      break
  return chunks

# 文档入库
def index_document(filename, content):
  """分块 → TF-IDF向量化 → 存入DocStore。返回chunk数量"""
  is_large = len(content) >= config.LARGE_DOCUMENT_THRESHOLD
  chunk_size = CHUNK_SIZE if is_large else config.SMALL_CHUNK_SIZE
  chunk_overlap = CHUNK_OVERLAP if is_large else config.SMALL_CHUNK_OVERLAP
  chunks_texts = split_text(content, chunk_size, chunk_overlap)
  if not chunks_texts: return 0

  global _vectorizer
  existing_chunks = [
    chunk for chunk in storage.get_all_chunks()
    if chunk.get("filename") != filename
  ]
  texts = [chunk["text"] for chunk in existing_chunks] + chunks_texts
  _vectorizer = TfidfVectorizer(
    analyzer="char_wb", ngram_range=(2, 4), max_features=10000
  )
  matrices = _vectorizer.fit_transform(texts)
  embeddings = [
    {
      "size": matrices.shape[1],
      "indices": row.indices.tolist(),
      "values": row.data.tolist(),
    }
    for row in matrices
  ]
  storage.add_indexed_document(
    filename,
    chunks_texts,
    embeddings,
    text_length=len(content),
    chunk_size=chunk_size,
    chunk_overlap=chunk_overlap,
  )
  with open(VECTORIZER_PATH, "wb") as f:
    pickle.dump(_vectorizer, f)
  return len(chunks_texts)

# —— —— 检索函数 —— ——
def retrieve(query, top_k=None, full_document_search=False):
  """Retrieve a matching document in full, otherwise use size-based top-k."""
  docstore = storage.get_docstore()
  all_chunks = docstore.get("chunks", [])
  if not all_chunks:
    return [], []

  documents_by_filename = {
    document.get("filename"): document
    for document in docstore.get("documents", {}).values()
  }
  chunks_by_filename = {}
  for chunk in all_chunks:
    chunks_by_filename.setdefault(chunk.get("filename", ""), []).append(chunk)

  query_terms = _query_terms(query)
  matched_documents = [
    chunks
    for chunks in chunks_by_filename.values()
    if any(
      term in chunk.get("text", "").casefold()
      for term in query_terms
      for chunk in chunks
    )
  ]
  if full_document_search and matched_documents:
    selected_chunks = [
      chunk for document_chunks in matched_documents for chunk in document_chunks
    ]
    return [
      {
        **chunk,
        "_msn_applicability": _chunk_applicability(chunk),
        "_retrieval_mode": "full_document",
      }
      for chunk in selected_chunks
    ], [1.0] * len(selected_chunks)

  vec = get_vectorizer()
  query_vec = vec.transform([query])
  chunk_embeddings = [chunk["embedding"] for chunk in all_chunks]
  if all(isinstance(embedding, dict) for embedding in chunk_embeddings):
    rows = np.repeat(np.arange(len(chunk_embeddings)), [len(e["indices"]) for e in chunk_embeddings])
    columns = np.concatenate([
      np.asarray(embedding["indices"], dtype=np.int32)
      for embedding in chunk_embeddings
    ])
    values = np.concatenate([
      np.asarray(embedding["values"], dtype=np.float64)
      for embedding in chunk_embeddings
    ])
    chunk_vecs = csr_matrix(
      (values, (rows, columns)),
      shape=(len(chunk_embeddings), chunk_embeddings[0]["size"]),
    )
  else:
    chunk_vecs = csr_matrix(chunk_embeddings)

  # 余弦相似度（TF-IDF向量已经是L2归一化的，所以直接点积即可）
  sims = cosine_similarity(query_vec, chunk_vecs)[0]

  scored_chunks = list(zip(all_chunks, sims))

  if top_k is None:
    scored_by_filename = {}
    for chunk, score in scored_chunks:
      scored_by_filename.setdefault(chunk.get("filename", ""), []).append((chunk, score))
    selected = []
    for filename, document_chunks in chunks_by_filename.items():
      document_top_k = (
        RETRIEVAL_TOP_K
        if _chunk_document_size(document_chunks, documents_by_filename)
        >= config.LARGE_DOCUMENT_THRESHOLD
        else config.SMALL_RETRIEVAL_TOP_K
      )
      ranked_document = sorted(
        scored_by_filename[filename], key=lambda item: item[1], reverse=True
      )
      selected.extend(ranked_document[:document_top_k])
    ranked = sorted(selected, key=lambda item: item[1], reverse=True)
    top = ranked
  else:
    ranked = sorted(scored_chunks, key=lambda item: item[1], reverse=True)
    top = ranked[:top_k]
  retrieved_chunks = [
    {**chunk, "_msn_applicability": _chunk_applicability(chunk)}
    for chunk, _ in top
  ]
  retrieved_scores = [float(score) for _, score in top]
  return retrieved_chunks, retrieved_scores


def _chunk_applicability(chunk):
  text = chunk.get("text", "")
  ranges = extract_msn_ranges(text)
  if not ranges and re.search(r"适用性\s*[:：]\s*ALL\b", text, re.IGNORECASE):
    return "ALL"
  return format_msn_ranges(ranges) or "未标注"