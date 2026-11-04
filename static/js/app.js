// 工具函数与全局状态
(
    function() {
        const API = "/api"

        let state = {
            session: [],
            activeSessionId: null,
            streamingAbort: null,
        };
        const $ = (sel) => document.querySelector(sel);
        const sessionList = $("#session-list");
        const messagesEl = $("#chat");
        const userInput = $("#user-input");
        const btnSend = $("#btn-send");
        const composerForm = $(".composer__inner");
        const btnNew = $("#btn-new-session");
        const sessionTitle = $("#current-session-title");
        // — —— 对话接入检索 —— ——
        const docList = $("#doc-list");
        const fileInput = $("#file-input");
        const uploadStatus = $("#upload-status");
        const btnUpload = $("#btn-upload");
        const knowledgeBaseNotice = $("#knowledge-base-notice");
        const answerMode = $("#answer-mode");
        const fullDocumentSearch = $("#full-document-search");
        let documentNames = new Set();

        /**
         * api请求方法
         * @param {*} method 方法
         * @param {*} path 路径
         * @param {*} body 请求体
         * @returns 
         */
        async function api(method, path, body) {
            const opts = { method, headers: { "Content-Type": "application/json" } };
            if (body) opts.body = JSON.stringify(body);
            // 原生fetch请求向后端发送请求
            const res = await fetch(API + path, opts);
            if (!res.headers.get("content-type")?.includes("application/json")) {
                throw new Error(`服务器返回非 JSON 响应（HTTP ${res.status}）`);
            }
            const data = await res.json();
            if (!res.ok) {
                throw new Error(data.error || `HTTP ${res.status}`);
            }
            return data;
        }

    // —— —— 会话管理 —— ——
    // 加载会话
    async function loadSessions() {
        // 接收在会话列表中获取后台所有会话数据
        state.session = await api("GET", "/sessions");
        // 刷新会话列表
        await renderSessions();
    }
    // 刷新会话列表
    function renderSessions() {
        sessionList.innerHTML = "";
        state.session.forEach(s => {
            const li = document.createElement("div");
            li.className = "session-item";
            li.dataset.id = s.id;
            if (s.id === state.activeSessionId) li.classList.add("is-active");

            const span = document.createElement("span");
            span.textContent = s.title || "未命名";
            span.style.flex = 1;
            
            span.addEventListener("click", () => {
                switchSession(s.id);
            });
            const del = document.createElement("b");
            del.className = "session-item__close";
            del.textContent = "×";
            del.addEventListener("click", (e) => {
                e.stopPropagation();
                if (!window.confirm(`确认删除会话“${s.title || "未命名"}”吗？此操作无法撤销。`)) {
                    return;
                }
                deleteSession(s.id);
            });

            li.appendChild(span);
            li.appendChild(del);
            sessionList.appendChild(li);
        });
    }

    function renderEmptyChat(message) {
        messagesEl.innerHTML = "";
        const emptyState = document.createElement("div");
        emptyState.className = "empty-state";
        const text = document.createElement("p");
        text.className = "empty-state__text";
        text.textContent = message;
        emptyState.appendChild(text);
        messagesEl.appendChild(emptyState);
    }

    // 切换会话按钮
    async function switchSession(id) {
        const sess = await api("GET", `/sessions/${id}`);
        state.activeSessionId = id;
        messagesEl.innerHTML = "";
        if (sess && sess.messages) {
            if (sess.messages.length) {
                sess.messages.forEach(msg => addMessage(msg.role, msg.content));
            } else {
                renderEmptyChat("这是一个新会话，输入问题开始对话。");
            }
            sessionTitle.textContent = sess ? sess.title : "Mini-RAG";
            scrollBottom();
            btnSend.disabled = false;
            renderSessions();
        }
    }

    // 删除会话按钮
    async function deleteSession(id) {
        await api("DELETE", `/sessions/${id}`);
        if (state.activeSessionId === id) {
            state.activeSessionId = null;
            renderEmptyChat("选择一个会话，或点击「新会话」开始提问。");
            sessionTitle.textContent = "选择一个会话";
            btnSend.disabled = false;
        }
        await loadSessions();
        if (!state.activeSessionId && state.session.length) {
            await switchSession(state.session[0].id);
        }
    }

    // —— —— 消息渲染辅助函数 —— ——
    function addMessage(role, content, idHint) {
        messagesEl.querySelector(".empty-state")?.remove();
        const div = document.createElement("div");
        const divContent = document.createElement("div");
        const roleClass = {
            user: "msg--user",
            assistant: "msg--ai",
            "msg--user": "msg--user",
            "msg--ai": "msg--ai",
        }[role] || role;
        div.className = `msg ${roleClass}`;
        divContent.className = "msg__bubble";
        if (idHint) divContent.id = idHint;
        divContent.textContent = content;
        div.appendChild(divContent);
        messagesEl.appendChild(div);
        scrollBottom();
        return divContent;
    }
    function scrollBottom() {
        messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // —— —— 对话接入检索 —— ——
    async function loadDocuments() {
        const docs = await api("GET", "/documents");
        documentNames = new Set(
            docs.map((document) => document.filename.normalize("NFC").toLocaleLowerCase())
        );
        docList.innerHTML = "";
        docs.forEach((d) => {
            const li = document.createElement("li");
            const name = document.createElement("span");
            name.textContent = `${d.filename} (${d.chunk_count}块)`;
            li.appendChild(name);
            const del = document.createElement("b");
            del.className = "doc-item__close";
            del.textContent = "×";
            del.addEventListener("click", async (e) => {
                e.stopPropagation();
                if (!window.confirm(`确认删除文件“${d.filename}”吗？此操作无法撤销。`)) {
                    return;
                }
                await api("DELETE", `/documents/${encodeURIComponent(d.id)}`);
                await loadDocuments();
            });
            li.appendChild(del);
            docList.appendChild(li);
        })
        const hasDocuments = docs.length > 0;
        knowledgeBaseNotice.hidden = hasDocuments;
        answerMode.querySelector('option[value="knowledge"]').disabled = !hasDocuments;
        if (!hasDocuments) {
            answerMode.value = "deepseek";
        } else if (answerMode.value === "deepseek" && state.documentsAvailable === false) {
            answerMode.value = "knowledge";
        }
        fullDocumentSearch.disabled = !hasDocuments || answerMode.value !== "knowledge";
        state.documentsAvailable = hasDocuments;
    }

    answerMode.addEventListener("change", () => {
        fullDocumentSearch.disabled =
            !state.documentsAvailable || answerMode.value !== "knowledge";
    });

    btnUpload.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", async () => {
        const file = fileInput.files[0];
        if (!file) return;
        const normalizedFilename = file.name.normalize("NFC").toLocaleLowerCase();
        if (documentNames.has(normalizedFilename)) {
            uploadStatus.textContent = `文件“${file.name}”已存在（文件名和类型相同），请勿重复上传；如需更新请先删除已有文件。`;
            fileInput.value = "";
            return;
        }
        uploadStatus.textContent = "上传中...";
        try {
            const formData = new FormData();
            formData.append("file", file);
            const res = await fetch(API + "/documents/upload", {
                method: "POST",
                body: formData
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
            uploadStatus.textContent = `上传成功：${data.filename}（${data.chunk_count}块）`;
            await loadDocuments();
        } catch (error) {
            uploadStatus.textContent = `上传失败：${error.message}`;
        } finally {
            fileInput.value = "";
        }
    });

    // —— —— 聊天功能 —— ——
    // 点击“发送”按钮触发该方法
    async function sendMessage() {
        const query = userInput.value.trim();
        if(!query) return;

        // 没有活跃会话时自动创建
        if(!state.activeSessionId) {
            const sess = await api("POST", "/sessions");
            state.activeSessionId = sess.id;
            sessionTitle.textContent = sess.title;
            await loadSessions();
        }
        addMessage("user", query);
        userInput.value = "";
        userInput.style.height = "auto";

        // 创建一个占位机器人气泡
        const botDiv = addMessage("assistant", "思考中...", "stream")
        btnSend.disabled = true;

        const ctrl = new AbortController();
        state.streamingAbort = ctrl;

        // 向后端发送流式输入请求
        try {
            const res = await fetch(API + "/chat/stream", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    message: query,
                    session_id: state.activeSessionId,
                    use_knowledge_base: answerMode.value === "knowledge",
                    full_document_search: fullDocumentSearch.checked,
                }),
                signal: ctrl.signal
            });
            if (!res.ok) {
                throw new Error(`聊天请求失败（HTTP ${res.status}）`);
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            let started = false;
            let completed = false;

            const processLine = (line) => {
                if (!line.startsWith("data: ")) return;
                const raw = line.slice(6).trim();
                if (!raw) return;
                if (raw === "[DONE]") {
                    completed = true;
                    return;
                }

                const data = JSON.parse(raw);
                if (data.type === "content") {
                    if (!started) {
                        botDiv.textContent = "";
                        started = true;
                    }
                    botDiv.textContent += data.text;
                    scrollBottom();
                } else if (data.type === "error") {
                    if (!started) {
                        botDiv.textContent = "";
                        started = true;
                    }
                    botDiv.textContent += `[错误：${data.message}]`;
                } else if (data.type === "progress" && !started) {
                    botDiv.textContent = data.text;
                }
            };

            while (true) {
                const { done, value } = await reader.read();
                if (done) {
                    buffer += decoder.decode();
                    break;
                }

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop(); // 保留未完成的行

                for (const line of lines) {
                    try {
                        processLine(line);
                    } catch (error) {
                        throw new Error(`无法解析流式响应：${error.message}`);
                    }
                }
            }

            if (buffer.trim()) {
                try {
                    processLine(buffer);
                } catch (error) {
                    throw new Error(`无法解析流式响应：${error.message}`);
                }
            }
            if (!started) {
                botDiv.textContent = completed
                    ? "模型未返回文本内容。"
                    : "连接已结束，但未收到回答内容。";
            }
        } catch (err) {
            if (err.name === "AbortError") {
                botDiv.textContent += "\n(已终止回答)";
            } else {
                botDiv.textContent = `请求失败：${err.message}`;
            }
        } finally {
            state.streamingAbort = null;
            btnSend.disabled = false;
            botDiv.removeAttribute("id")
        }
    }

    // —— —— 事件绑定与初始化 —— ——
    btnNew.addEventListener("click", async () => {
        const sess = await api("POST", "/sessions");
        state.activeSessionId = sess.id;
        renderEmptyChat("这是一个新会话，输入问题开始对话。");
        sessionTitle.textContent = sess.title || "Mini-RAG";
        btnSend.disabled = false;
        // 异步刷新
        await loadSessions();
    });
    // Prevent the form's default POST to the current page and handle it as chat.
    composerForm.addEventListener("submit", (e) => {
        e.preventDefault();
        if (!btnSend.disabled) sendMessage();
    });

    userInput.addEventListener("input", () => {
        userInput.style.height = "auto";
        userInput.style.height = Math.min(userInput.scrollHeight);
    })
    // 初始加载
    async function init() {
        try {
            await loadSessions();
            if (state.session.length) {
                await switchSession(state.session[0].id);
            } else {
                state.activeSessionId = null;
                sessionTitle.textContent = "Mini-RAG";
                renderEmptyChat("还没有对话记录，点击「新会话」或输入问题开始。");
                btnSend.disabled = false;
            }
            await loadDocuments();
        } catch (error) {
            console.error("页面初始化失败：", error);
            uploadStatus.textContent = `加载失败：${error.message}`;
        }
    }

    init();

})()