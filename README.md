# Mini-RAG · 本地知识库问答（RAG 全链路实现）

> ⭐ 如果这个项目对你有帮助，欢迎点一个 **Star**——你的一个星，是对独立开发者最直接的鼓励；发现问题或有想法，也欢迎提 Issue。

基于 **Flask + DeepSeek** 的轻量 RAG（检索增强生成）问答系统：上传文档 → 滑窗切分 → TF-IDF 向量化 → 余弦相似度 TopK 召回 → 拼装提示词 → 流式回答。前端为仿 DeepSeek 风格的单页界面，纯 HTML / CSS / JS 实现，无框架依赖。

![界面截图](docs/screenshot.png)

## 特性

- **完整 RAG 链路**：文档上传、滑动窗口分块（chunk / overlap 可配）、TF-IDF 向量化（中文 char n-gram 2–4）、余弦相似度 TopK 召回（可调 k）
- **SSE 流式输出**：先以 `meta` 事件下发检索到的片段与相似度，再逐 token 下发回答内容，前端边收边渲染
- **可解释性**：每次回答都能看到"依据的是哪几段、相似度多少"，而不是黑盒输出
- **防编造**：提示词约束「仅依据资料回答，资料中没有答案就如实告知」，抑制模型幻觉
- **检索一致性**：新增文档时在全量语料上重建词汇表并重编码全部 chunk，保证跨文档处于同一向量空间
- **会话管理**：多会话、自动以首问前 30 字命名、JSON 持久化，刷新不丢
- **零重型依赖**：不依赖向量数据库 / GPU / 外部检索服务，`pip install` 后即可运行

## 架构

```
浏览器（static/index.html + js/app.js）
   │  POST /api/chat/stream        （SSE，text/event-stream）
   ▼
Flask app.py
   ├── rag.py       滑动窗口切分 → TF-IDF 向量化 → 余弦相似度 TopK 召回
   ├── storage.py   docstore.json（文档与 chunk）/ sessions/*.json（会话）
   └── llm.py       OpenAI SDK（DeepSeek 兼容接口）→ 流式生成
```

**一次问答的数据流：**

1. 用户提问 → 问题向量化（TF-IDF）
2. 与全部 chunk 的向量计算余弦相似度，取 Top K（默认 4）
3. 命中片段拼进 system prompt，连同历史消息发给 DeepSeek
4. 先推送 `meta` 事件（片段 + 分数），再逐 token 推送 `content`
5. 会话落盘，自动命名

## 快速开始

要求：Python 3.9+

```bash
git clone https://github.com/gaodaxiu0406/Mini-Rag.git
cd mini-rag

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env             # 填入你的 DEEPSEEK_API_KEY
python app.py                    # 默认 http://localhost:8000
```

首次启动会自动创建 `data/` 目录。打开页面 → 上传一个纯文本文件 → 直接提问即可。

## 环境变量（.env）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | 必填，DeepSeek 控制台申请 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容接口地址 |
| `DEEPSEEK_MODEL` | `deepseek-v4-flash` | 对话模型名，换模型只改配置 |
| `CHUNK_SIZE` | `400` | 切块长度（字符） |
| `CHUNK_OVERLAP` | `100` | 相邻块重叠字符数 |
| `RETRIEVAL_TOP_K` | `4` | 每次召回片段数 |

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/sessions` | 会话列表（按时间倒序） |
| `POST` | `/api/sessions` | 新建会话 |
| `GET` | `/api/sessions/{id}` | 会话详情（含历史消息） |
| `DELETE` | `/api/sessions/{id}` | 删除会话 |
| `POST` | `/api/chat/stream` | 流式对话；会话不存在时自动创建 |
| `GET` | `/api/documents` | 已入库文档列表 |
| `POST` | `/api/documents/upload` | 上传文档（multipart/form-data，字段名 `file`） |
| `DELETE` | `/api/documents/{filename}` | 删除文档及其全部 chunk |

**SSE 事件格式**（`POST /api/chat/stream`）：

```
data: {"type": "meta", "retrieved": ["片段1", "片段2"], "scores": [0.42, 0.31]}

data: {"type": "content", "text": "根据资料，"}

data: {"type": "error", "message": "..."}

data: [DONE]
```

## 目录结构

```
mini-rag/
├── app.py            # Flask 入口：路由、SSE 流式对话、文档上传
├── config.py         # .env 配置集中管理
├── llm.py            # DeepSeek 客户端（OpenAI SDK 兼容层）
├── rag.py            # 切分 / TF-IDF 向量化 / 余弦 TopK 检索
├── storage.py        # 会话与文档库的 JSON 持久化
├── requirements.txt
├── .env.example
├── static/
│   ├── index.html    # 仿 DeepSeek 单页界面
│   ├── css/style.css
│   └── js/app.js
└── data/             # 运行时生成（已 gitignore）
    ├── docstore.json     # 文档与 chunk（含向量）
    ├── vectorizer.pkl    # TF-IDF 词汇表
    └── sessions/         # 会话记录
```

## 设计取舍

**为什么用 TF-IDF 而不是 embedding？**
轻量起步：无 GPU、无外部向量服务，中文用 `char_wb` + n-gram(2–4) 对分词不敏感、部署零成本。代价是没有语义理解——问"退款"找不到写"退钱"的段落。

**为什么每次入库都重建词汇表？**
TF-IDF 的向量维度依赖语料词汇表。新增文档若只对新 chunk 编码，新旧向量不在同一空间，余弦相似度会失真。因此入库时在全量语料上重建词汇表，并重编码所有历史 chunk——用一次性成本换检索正确性。

**为什么先发 meta 再发内容？**
检索结果与分数先到前端，用户能立刻看到"正在依据哪几段回答"，既缓解等待焦虑，也让答案可溯源。

## 已知限制 / Roadmap

- [ ] TF-IDF 检索改为 embedding（bge / m3e）+ 向量库（FAISS / Chroma），解决同义改写召回
- [ ] 支持 PDF / Word / Markdown 解析，目前仅纯文本
- [ ] 增加 rerank 重排，提升 TopK 精度
- [ ] 存储从 JSON 迁移到 SQLite / PostgreSQL，支持并发与多用户
- [ ] 文档级权限与引用跳转（点击出处定位原文）

## License

MIT
