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
                deleteSession(s.id);
            });

            li.appendChild(span);
            li.appendChild(del);
            sessionList.appendChild(li);
        });
    }

    // 切换会话按钮
    async function switchSession(id) {
        state.activeSessionId = id;
        // 根据会话id获取会话数据
        const sess = await api("GET", `/sessions/${id}`);
        messagesEl.innerHTML = "";
        if (sess && sess.messages) {
            sess.messages.forEach(msg => addMessage(msg.role, msg.content));
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
            messagesEl.innerHTML = "";
            sessionTitle.textContent = "选择一个会话";
            btnSend.disabled = true;
        }
        await loadSessions();
    }

    // —— —— 消息渲染辅助函数 —— ——
    function addMessage(role, content, idHint) {
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
                await api("DELETE", `/documents/${encodeURIComponent(d.filename)}`);
                await loadDocuments();
            });
            li.appendChild(del);
            docList.appendChild(li);
        })
    }

    btnUpload.addEventListener("click", () => fileInput.click());

    fileInput.addEventListener("change", async () => {
        const file = fileInput.files[0];
        if (!file) return;
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
                }),
                signal: ctrl.signal
            });

            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            let started = false;

            // 对于返回的每一个字节依次处理
            while(true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop(); // 保留未完成的行

                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    const raw = line.slice(6).trim();
                    if (!raw || raw === "[DONE]") continue;
                    try {
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
                            botDiv.textContent += `[错误：${data.message}]`
                        } else if (data.type === "meta"){
                        // 检索元信息，不渲染文本
                        }
                    } catch (e) {}
                }
            }
            
            if (!started) botDiv.textContent = "(已终止回答)";
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
        messagesEl.innerHTML = "";
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

    userInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (!btnSend.disabled) sendMessage();
        }
    });

    userInput.addEventListener("input", () => {
        userInput.style.height = "auto";
        userInput.style.height = Math.min(userInput.scrollHeight);
    })
    // 初始加载
    async function init() {
        // 刷新会话列表
        await loadSessions();
        // 刷新文档列表
        await loadDocuments();
    }

    init();

})()