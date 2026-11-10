// 工具函数与全局状态
(
    function() {
        const API = "/api"

        let state = {
            session: [],
            activeSessionId: null,
            streamingAbort: null,
            apiKey: sessionStorage.getItem("deepseekApiKey") || "",
            serverHasApiKey: false,
            displayMaxChars: 4000,
            uploadQueue: [],
            uploadItems: [],
            uploadNotices: [],
            uploadInProgress: false,
            documentDeleteInProgress: false,
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
        const documentActionStatus = $("#document-action-status");
        const btnUpload = $("#btn-upload");
        const knowledgeBaseNotice = $("#knowledge-base-notice");
        const answerModeOptions = document.querySelectorAll('input[name="answer-mode"]');
        const knowledgeModeInput = $("#answer-mode-knowledge");
        const deepseekModeInput = $("#answer-mode-deepseek");
        const fullDocumentSearch = $("#full-document-search");
        const fullResponse = $("#full-response");
        const fullResponseLabel = fullResponse.closest("label");
        const authDialog = $("#auth-dialog");
        const authForm = $("#auth-form");
        const authButton = $("#btn-auth");
        const authInput = $("#api-key-input");
        const authStatus = $("#auth-status");
        const deleteKeyButton = $("#btn-auth-delete");
        const menuButton = $("#btn-menu");
        const sidebarBackdrop = $("#sidebar-backdrop");
        const app = $(".app");
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

        function hasApiKey() {
            return Boolean(state.apiKey || state.serverHasApiKey);
        }

        function getAnswerMode() {
            return document.querySelector('input[name="answer-mode"]:checked').value;
        }

        function setAnswerMode(mode) {
            knowledgeModeInput.checked = mode === "knowledge";
            deepseekModeInput.checked = mode === "deepseek";
        }

        function displayAnswer(content) {
            const characters = Array.from(content);
            if (fullResponse.checked || characters.length <= state.displayMaxChars) {
                return content;
            }
            return `${characters.slice(0, state.displayMaxChars).join("")}\n\n（页面仅显示前 ${state.displayMaxChars} 字；勾选“完整显示回复”可查看全部内容。）`;
        }

        function refreshAuthUI() {
            const hasClientKey = Boolean(state.apiKey);
            authButton.textContent = hasClientKey
                ? "已登录"
                : state.serverHasApiKey ? "服务器密钥已配置" : "登录 DeepSeek";
            authStatus.textContent = state.serverHasApiKey
                ? "服务器已配置默认密钥；您也可以使用自己的密钥覆盖。"
                : hasClientKey ? "当前浏览器会话已保存密钥。" : "";
            deleteKeyButton.hidden = !hasClientKey;
            deleteKeyButton.textContent = "删除已保存密钥";
            deepseekModeInput.disabled = !hasApiKey();
            if (!hasApiKey()) {
                setAnswerMode("knowledge");
            } else if (state.documentsAvailable === false) {
                setAnswerMode("deepseek");
            }
        }

        function syncAnswerOptions(reset = false) {
            const isDeepseekMode = getAnswerMode() === "deepseek";
            const previousFullResponse = fullResponse.checked;
            let shouldRenderAnswers = false;
            fullDocumentSearch.disabled =
                !state.documentsAvailable || isDeepseekMode;
            fullResponse.disabled = isDeepseekMode;
            fullResponseLabel.classList.toggle("is-disabled", isDeepseekMode);
            if (reset) {
                fullDocumentSearch.checked = false;
                fullResponse.checked = isDeepseekMode;
                localStorage.setItem("showFullResponse", String(fullResponse.checked));
                shouldRenderAnswers = true;
            } else if (isDeepseekMode) {
                fullResponse.checked = true;
            }
            if (previousFullResponse !== fullResponse.checked) {
                shouldRenderAnswers = true;
            }
            if (shouldRenderAnswers) {
                renderCurrentAnswers();
            }
        }

        function renderCurrentAnswers() {
            messagesEl.querySelectorAll(".msg--ai .msg__bubble").forEach((bubble) => {
                bubble.textContent = displayAnswer(bubble.dataset.fullContent || "");
            });
        }

        function setSidebarOpen(isOpen) {
            app.classList.toggle("is-sidebar-open", isOpen);
            sidebarBackdrop.hidden = !isOpen;
            menuButton.setAttribute("aria-expanded", String(isOpen));
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
        if (state.streamingAbort) state.streamingAbort.abort();
        setSidebarOpen(false);
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
        divContent.dataset.fullContent = content;
        divContent.textContent = roleClass === "msg--ai" ? displayAnswer(content) : content;
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
        const hadDocuments = state.documentsAvailable;
        documentNames = new Set(
            docs.map((document) => document.filename.normalize("NFC").toLocaleLowerCase())
        );
        docList.innerHTML = "";
        docs.forEach((d) => {
            const li = document.createElement("li");
            const name = document.createElement("span");
            name.textContent = `${d.filename} (${d.chunk_count}块)`;
            li.appendChild(name);
            const deleteStatus = document.createElement("span");
            deleteStatus.className = "doc-item__status";
            deleteStatus.textContent = "正在删除…";
            li.appendChild(deleteStatus);
            const del = document.createElement("button");
            del.className = "doc-item__close";
            del.type = "button";
            del.textContent = "×";
            del.setAttribute("aria-label", `删除文件 ${d.filename}`);
            del.disabled = state.documentDeleteInProgress;
            del.addEventListener("click", async (e) => {
                e.stopPropagation();
                if (state.documentDeleteInProgress) return;
                if (!window.confirm(`确认删除文件“${d.filename}”吗？此操作无法撤销。`)) {
                    return;
                }
                state.documentDeleteInProgress = true;
                li.classList.add("is-deleting");
                li.setAttribute("aria-busy", "true");
                documentActionStatus.hidden = false;
                documentActionStatus.classList.add("is-pending");
                documentActionStatus.setAttribute("aria-busy", "true");
                documentActionStatus.textContent = `正在删除“${d.filename}”… 文件较大时可能需要一些时间，请勿重复操作。`;
                docList.querySelectorAll(".doc-item__close").forEach((button) => {
                    button.disabled = true;
                });
                let deleted = false;
                try {
                    await api("DELETE", `/documents/${encodeURIComponent(d.id)}`);
                    deleted = true;
                    li.remove();
                    await loadDocuments();
                    documentActionStatus.textContent = "";
                    documentActionStatus.hidden = true;
                } catch (error) {
                    documentActionStatus.hidden = false;
                    documentActionStatus.textContent = deleted
                        ? `文件“${d.filename}”已删除，但刷新列表失败：${error.message}`
                        : `删除“${d.filename}”失败：${error.message}。可以稍后重试。`;
                } finally {
                    state.documentDeleteInProgress = false;
                    documentActionStatus.classList.remove("is-pending");
                    documentActionStatus.setAttribute("aria-busy", "false");
                    docList.querySelectorAll(".doc-item__close").forEach((button) => {
                        button.disabled = false;
                    });
                    docList.querySelectorAll(".doc-item.is-deleting").forEach((item) => {
                        item.classList.remove("is-deleting");
                        item.removeAttribute("aria-busy");
                    });
                }
            });
            li.appendChild(del);
            docList.appendChild(li);
        })
        const hasDocuments = docs.length > 0;
        knowledgeBaseNotice.hidden = hasDocuments && hasApiKey();
        knowledgeBaseNotice.textContent = !hasDocuments
            ? hasApiKey()
                ? "当前知识库为空，请上传文档；也可以选择使用 DeepSeek 模型回答问题。"
                : "当前知识库为空，请上传文档。配置 DeepSeek API Key 后可启用通用回答。"
            : hasApiKey()
                ? ""
                : "未配置 DeepSeek API Key：当前只能进行本地知识库检索，无法使用 DeepSeek 生成回答。";
        state.documentsAvailable = hasDocuments;
        refreshAuthUI();
        const uploadedFirstDocument =
            hadDocuments === false && hasDocuments && getAnswerMode() === "deepseek";
        if (uploadedFirstDocument) {
            setAnswerMode("knowledge");
        }
        syncAnswerOptions(uploadedFirstDocument);
    }

    answerModeOptions.forEach((option) => {
        option.addEventListener("change", () => {
            syncAnswerOptions(true);
        });
    });

    authButton.addEventListener("click", () => {
        authInput.value = state.apiKey;
        authDialog.showModal();
        authInput.focus();
    });

    authForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const key = authInput.value.trim();
        if (!key) {
            authStatus.textContent = "请输入 DeepSeek API Key。";
            authInput.focus();
            return;
        }
        state.apiKey = key;
        sessionStorage.setItem("deepseekApiKey", key);
        refreshAuthUI();
        loadDocuments().catch((error) => {
            uploadStatus.textContent = `加载失败：${error.message}`;
        });
        authDialog.close();
    });

    deleteKeyButton.addEventListener("click", () => {
        sessionStorage.removeItem("deepseekApiKey");
        state.apiKey = "";
        authInput.value = "";
        refreshAuthUI();
        loadDocuments().catch((error) => {
            uploadStatus.textContent = `加载失败：${error.message}`;
        });
        authDialog.close();
    });

    $("#btn-auth-cancel").addEventListener("click", () => authDialog.close());
    authDialog.addEventListener("click", (event) => {
        if (event.target === authDialog) authDialog.close();
    });

    fullResponse.checked = localStorage.getItem("showFullResponse") === "true";
    fullResponse.addEventListener("change", () => {
        localStorage.setItem("showFullResponse", String(fullResponse.checked));
        renderCurrentAnswers();
    });

    menuButton.addEventListener("click", () => {
        setSidebarOpen(!app.classList.contains("is-sidebar-open"));
    });
    sidebarBackdrop.addEventListener("click", () => setSidebarOpen(false));

    btnUpload.addEventListener("click", () => fileInput.click());

    function renderUploadStatus() {
        const activeCount = state.uploadItems.filter((item) => item.status === "uploading").length;
        const queuedCount = state.uploadQueue.length;
        const hasPending = activeCount > 0 || queuedCount > 0;
        const failedItems = state.uploadItems.filter((item) => item.status === "error");
        uploadStatus.hidden = !hasPending && failedItems.length === 0 && state.uploadNotices.length === 0;
        uploadStatus.classList.toggle("is-uploading", hasPending);
        uploadStatus.setAttribute("aria-busy", String(hasPending));
        uploadStatus.replaceChildren();

        if (uploadStatus.hidden) return;

        const summary = document.createElement("p");
        summary.className = "upload-status__summary";
        summary.textContent = hasPending
            ? activeCount
                ? `正在上传并建立索引；另有 ${queuedCount} 个文件排队中。可继续添加文件。`
                : `${queuedCount} 个文件等待上传；可继续添加文件。`
            : failedItems.length
                ? `上传完成，${failedItems.length} 个文件未能上传。`
                : "检测到重复文件，已跳过上传。";
        uploadStatus.appendChild(summary);

        failedItems.forEach((item) => {
            const failure = document.createElement("p");
            failure.className = "upload-status__notice";
            failure.textContent = item.message;
            uploadStatus.appendChild(failure);
        });

        state.uploadNotices.forEach((filename) => {
            const notice = document.createElement("p");
            notice.className = "upload-status__notice";
            notice.textContent = `文件“${filename}”已存在，请勿重复上传。`;
            uploadStatus.appendChild(notice);
        });

        state.uploadItems.filter((item) => item.status === "queued" || item.status === "uploading").forEach((item) => {
            const row = document.createElement("div");
            row.className = `upload-status__item upload-status__item--${item.status}`;
            row.title = item.message || item.file.name;
            const filename = document.createElement("span");
            filename.className = "upload-status__filename";
            filename.textContent = item.file.name;
            const status = document.createElement("span");
            status.className = "upload-status__state";
            status.textContent = item.status === "uploading"
                ? "上传中"
                : item.status === "queued"
                    ? "排队中"
                    : item.status === "success"
                        ? "已完成"
                        : "失败";
            row.append(filename, status);
            uploadStatus.appendChild(row);
        });
    }

    function addDuplicateUploadNotice(filename) {
        const normalizedFilename = filename.normalize("NFC").toLocaleLowerCase();
        if (!state.uploadNotices.some(
            (notice) => notice.normalize("NFC").toLocaleLowerCase() === normalizedFilename
        )) {
            state.uploadNotices.push(filename);
        }
    }

    async function processUploadQueue() {
        if (state.uploadInProgress) return;
        state.uploadInProgress = true;
        btnUpload.textContent = "继续添加文件";
        try {
            while (state.uploadQueue.length) {
                const item = state.uploadQueue.shift();
                item.status = "uploading";
                renderUploadStatus();
                try {
                    const formData = new FormData();
                    formData.append("file", item.file);
                    const res = await fetch(API + "/documents/upload", {
                        method: "POST",
                        body: formData
                    });
                    const data = await res.json();
                    if (res.status === 409) {
                        addDuplicateUploadNotice(item.file.name);
                        state.uploadItems = state.uploadItems.filter((uploadItem) => uploadItem !== item);
                    } else {
                        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                        item.status = "success";
                        item.message = `上传成功：${data.filename}（${data.chunk_count}块）`;
                        try {
                            await loadDocuments();
                        } catch (error) {
                            item.message += `；刷新文档列表失败：${error.message}`;
                        }
                    }
                } catch (error) {
                    item.status = "error";
                    item.message = `上传失败：${error.message}`;
                }
                renderUploadStatus();
            }
        } finally {
            state.uploadInProgress = false;
            btnUpload.textContent = "上传文档";
            renderUploadStatus();
        }
    }

    fileInput.addEventListener("change", () => {
        const files = Array.from(fileInput.files);
        fileInput.value = "";
        if (!files.length) return;
        state.uploadNotices = [];

        const queuedNames = new Set(
            state.uploadItems
                .filter((item) => item.status === "queued" || item.status === "uploading")
                .map((item) => item.file.name.normalize("NFC").toLocaleLowerCase())
        );
        files.forEach((file) => {
            const normalizedFilename = file.name.normalize("NFC").toLocaleLowerCase();
            if (documentNames.has(normalizedFilename) || queuedNames.has(normalizedFilename)) {
                addDuplicateUploadNotice(file.name);
                return;
            }
            queuedNames.add(normalizedFilename);
            const item = { file, status: "queued", message: "" };
            state.uploadItems.push(item);
            state.uploadQueue.push(item);
        });
        renderUploadStatus();
        processUploadQueue();
    });

    // —— —— 聊天功能 —— ——
    // 点击“发送”按钮触发该方法
    async function sendMessage() {
        if (state.streamingAbort) {
            state.streamingAbort.abort();
            return;
        }
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

        const ctrl = new AbortController();
        state.streamingAbort = ctrl;
        btnSend.textContent = "停止";
        btnSend.classList.add("is-stopping");
        let receivedText = "";

        // 向后端发送流式输入请求
        try {
            const res = await fetch(API + "/chat/stream", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(state.apiKey ? {"X-DeepSeek-API-Key": state.apiKey} : {}),
                },
                body: JSON.stringify({
                    message: query,
                    session_id: state.activeSessionId,
                    use_knowledge_base: getAnswerMode() === "knowledge",
                    full_document_search: fullDocumentSearch.checked,
                }),
                signal: ctrl.signal
            });
            if (!res.ok) {
                const errorData = await res.json().catch(() => ({}));
                throw new Error(errorData.error || `聊天请求失败（HTTP ${res.status}）`);
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
                        receivedText = "";
                        started = true;
                    }
                    receivedText += data.text;
                    botDiv.dataset.fullContent = receivedText;
                    botDiv.textContent = displayAnswer(receivedText);
                    scrollBottom();
                } else if (data.type === "error") {
                    if (!started) {
                        receivedText = "";
                        started = true;
                    }
                    receivedText += `[错误：${data.message}]`;
                    botDiv.dataset.fullContent = receivedText;
                    botDiv.textContent = displayAnswer(receivedText);
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
                botDiv.dataset.fullContent = receivedText;
                botDiv.textContent = `${displayAnswer(receivedText)}\n\n（已停止生成）`;
            } else {
                botDiv.dataset.fullContent = `请求失败：${err.message}`;
                botDiv.textContent = displayAnswer(botDiv.dataset.fullContent);
            }
        } finally {
            state.streamingAbort = null;
            btnSend.textContent = "发送";
            btnSend.classList.remove("is-stopping");
            botDiv.removeAttribute("id")
        }
    }

    // —— —— 事件绑定与初始化 —— ——
    btnNew.addEventListener("click", async () => {
        if (state.streamingAbort) state.streamingAbort.abort();
        setSidebarOpen(false);
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
        sendMessage();
    });

    userInput.addEventListener("input", () => {
        userInput.style.height = "auto";
        userInput.style.height = Math.min(userInput.scrollHeight);
    })
    // 初始加载
    async function init() {
        try {
            const appConfig = await api("GET", "/app-config");
            state.serverHasApiKey = appConfig.has_server_api_key;
            state.displayMaxChars = Math.max(1, appConfig.display_max_chars);
            refreshAuthUI();
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