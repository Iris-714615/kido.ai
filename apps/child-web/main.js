import { createApp, reactive, ref, onMounted, watch, nextTick } from "https://unpkg.com/vue@3/dist/vue.esm-browser.js";

// ========== API_BASE 策略 ==========
// 开发环境（前端 5173 → 后端 8000 跨域）使用绝对地址
// 生产环境（同源 / 反代）使用相对路径
const DEV_API_BASE = "http://localhost:8000/api/v1";
const PROD_API_BASE = "/api/v1";
const API_BASE =
  (location.hostname === "localhost" || location.hostname === "127.0.0.1") && location.port === "5173"
    ? DEV_API_BASE
    : PROD_API_BASE;

// 后端 origin（用于拼接媒体文件等相对路径 URL）
const BACKEND_ORIGIN = API_BASE.replace(/\/api\/v1$/, "");

// 将后端返回的相对路径（如 /media/...）转为完整 URL（跨域时拼接后端 origin）
function assetUrl(url) {
  if (!url) return "";
  if (/^https?:\/\//.test(url)) return url;
  return BACKEND_ORIGIN + url;
}

// ========== 全局状态 ==========
const store = reactive({
  token: localStorage.getItem("kidoai_token") || "",
  user: JSON.parse(localStorage.getItem("kidoai_user") || "null"),
  childProfile: JSON.parse(localStorage.getItem("kidoai_child") || "null"),
});

function persistAuth() {
  if (store.token) localStorage.setItem("kidoai_token", store.token);
  else localStorage.removeItem("kidoai_token");
  if (store.user) localStorage.setItem("kidoai_user", JSON.stringify(store.user));
  else localStorage.removeItem("kidoai_user");
  if (store.childProfile) localStorage.setItem("kidoai_child", JSON.stringify(store.childProfile));
  else localStorage.removeItem("kidoai_child");
}

function clearAuth() {
  store.token = "";
  store.user = null;
  store.childProfile = null;
  persistAuth();
}

// ========== API 封装 ==========
async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (store.token) headers.set("Authorization", `Bearer ${store.token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (response.status === 401) {
    clearAuth();
    location.hash = "#/login";
    throw new Error("登录已过期，请重新登录");
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = data.detail || JSON.stringify(data);
    } catch (_) {
      try { detail = await response.text(); } catch (_) {}
    }
    throw new Error(detail);
  }
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : response.text();
}

const AuthAPI = {
  demo: () => api("/auth/demo"),
  login: (username, password) =>
    api("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  register: (payload) =>
    api("/auth/register", { method: "POST", body: JSON.stringify(payload) }),
  me: () => api("/auth/me"),
};

const ExploreAPI = {
  upload: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return api("/explore/image", { method: "POST", body: fd });
  },
  list: (limit = 20) => api(`/explore/records?limit=${limit}`),
  get: (id) => api(`/explore/records/${id}`),
};

const ChatAPI = {
  createSession: (title) =>
    api("/chat/sessions", { method: "POST", body: JSON.stringify({ title }) }),
  listSessions: () => api("/chat/sessions"),
  getSession: (id) => api(`/chat/sessions/${id}`),
  sendMessage: (sessionId, content) =>
    api(`/chat/sessions/${sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  streamMessage: async (sessionId, content, onChunk, onDone, onError) => {
    const response = await fetch(`${API_BASE}/chat/sessions/${sessionId}/messages/stream`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${store.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ content }),
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(text || `HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let fullText = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith("data: ")) continue;
          const raw = trimmed.slice(6);
          if (raw === "[DONE]") continue;
          try {
            const data = JSON.parse(raw);
            if (data.type === "chunk" && data.text) {
              fullText += data.text;
              onChunk && onChunk(fullText);
            } else if (data.type === "done") {
              onDone && onDone(data);
            }
          } catch (_) {}
        }
      }
    } catch (err) {
      onError && onError(err);
      throw err;
    }
    return fullText;
  },
};

const MemoryAPI = {
  summary: (limit = 10) => api(`/memory/summary?limit=${limit}`),
  events: (limit = 20) => api(`/memory/events?limit=${limit}`),
  entities: (limit = 20) => api(`/memory/entities?limit=${limit}`),
};

// ========== RAG 问答 API（LangChain + 十万个为什么知识库）==========
// 与后端 RAG_HISTORY_MIN_TURNS 对齐，仅用于 UI 提示
const RAG_HISTORY_MIN_TURNS_HINT = 5;

const RAGAPI = {
  /** 流式 RAG 问答（支持多轮历史） */
  streamChat: async (ask, conversationId, onChunk, onMeta, onDone, onError) => {
    const response = await fetch(`${API_BASE}/deep/rag_chat/stream`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${store.token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ask, conversation_id: conversationId || null }),
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(text || `HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let fullText = "";
    let convId = conversationId;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith("data: ")) continue;
          const raw = trimmed.slice(6);
          if (raw === "[DONE]") {
            onDone && onDone({ conversationId: convId });
            continue;
          }
          try {
            const data = JSON.parse(raw);
            if (data.type === "meta") {
              if (data.conversation_id) convId = data.conversation_id;
              onMeta && onMeta({
                conversationId: convId,
                sources: data.sources || [],
              });
            } else if (data.type === "chunk" && data.text) {
              fullText += data.text;
              onChunk && onChunk(fullText, convId);
            } else if (data.type === "error") {
              throw new Error(data.message);
            }
          } catch (e) {
            if (e.message) throw e;
          }
        }
      }
    } catch (err) {
      onError && onError(err);
      throw err;
    }
    return { fullText, conversationId: convId };
  },

  /** 加载历史记录 */
  loadHistory: async (conversationId) => {
    if (!conversationId) return [];
    const r = await fetch(
      `${API_BASE}/deep/rag_history?conversation_id=${encodeURIComponent(conversationId)}`,
      { headers: { Authorization: `Bearer ${store.token}` } }
    );
    if (!r.ok) return [];
    const data = await r.json();
    return data.messages || [];
  },

  /** 清除指定会话的历史记录 */
  clearHistory: async (conversationId) => {
    if (!conversationId) return;
    try {
      await fetch(
        `${API_BASE}/deep/rag_history/${encodeURIComponent(conversationId)}`,
        { method: "DELETE", headers: { Authorization: `Bearer ${store.token}` } }
      );
    } catch (e) {
      console.warn("清除 RAG 历史失败:", e);
    }
  },
};

// ========== 路由 ==========
const route = reactive({ path: location.hash.replace(/^#/, "") || "/" });
window.addEventListener("hashchange", () => {
  route.path = location.hash.replace(/^#/, "") || "/";
});

// ========== 工具 ==========
function fmtTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  } catch (_) {
    return iso;
  }
}

function scrollToBottom(el) {
  if (el) el.scrollTop = el.scrollHeight;
}

// ========== Vue 应用 ==========
const app = createApp({
  template: `
    <main class="app-shell">
      <header class="topbar" v-if="store.token">
        <div class="brand-block">
          <div class="eyebrow">KidoAI</div>
          <h1>儿童探索乐园</h1>
        </div>
        <nav class="nav">
          <a :class="{active: route.path==='/'}" href="#/">主页</a>
          <a :class="{active: route.path==='/explore'}" href="#/explore">探索记录</a>
          <a :class="{active: route.path==='/chat'}" href="#/chat">我的对话</a>
          <a :class="{active: route.path==='/rag-chat'}" href="#/rag-chat">RAG问答</a>
          <a :class="{active: route.path==='/memory'}" href="#/memory">我的记忆</a>
        </nav>
        <div class="user-block">
          <div class="user-info" v-if="store.childProfile">
            <strong>{{ store.childProfile.nickname }}</strong>
            <span>{{ store.childProfile.age }}岁 · Lv{{ store.childProfile.current_level }} · {{ store.childProfile.token_balance }}币</span>
          </div>
          <button class="ghost-btn" @click="logout">退出</button>
        </div>
      </header>

      <section v-if="autoLoggingIn" class="auth-page">
        <div class="auth-card"><p style="text-align:center;padding:40px 0;">正在自动登录...</p></div>
      </section>

      <section v-else-if="!store.token" class="auth-page">
        <div class="auth-card">
          <div class="auth-tabs">
            <button :class="{active: authTab==='demo'}" @click="authTab='demo'">体验账号</button>
            <button :class="{active: authTab==='login'}" @click="authTab='login'">登录</button>
            <button :class="{active: authTab==='register'}" @click="authTab='register'">注册</button>
          </div>

          <div v-if="authTab==='demo'" class="auth-form">
            <p class="auth-tip">一键获取演示账号，立即体验全部功能。</p>
            <button class="primary-btn big" :disabled="authLoading" @click="doDemo">
              {{ authLoading ? "正在登录..." : "开始体验" }}
            </button>
            <p v-if="authError" class="auth-error">{{ authError }}</p>
          </div>

          <div v-else-if="authTab==='login'" class="auth-form">
            <input v-model="loginForm.username" type="text" placeholder="用户名" autocomplete="username" />
            <input v-model="loginForm.password" type="password" placeholder="密码" autocomplete="current-password" />
            <button class="primary-btn big" :disabled="authLoading" @click="doLogin">
              {{ authLoading ? "登录中..." : "登录" }}
            </button>
            <p v-if="authError" class="auth-error">{{ authError }}</p>
          </div>

          <div v-else class="auth-form">
            <input v-model="regForm.username" type="text" placeholder="用户名 (≥3字符)" autocomplete="username" />
            <input v-model="regForm.password" type="password" placeholder="密码 (≥6字符)" autocomplete="new-password" />
            <input v-model="regForm.nickname" type="text" placeholder="昵称（可选）" />
            <input v-model.number="regForm.age" type="number" min="3" max="12" placeholder="年龄 (3-12)" />
            <button class="primary-btn big" :disabled="authLoading" @click="doRegister">
              {{ authLoading ? "注册中..." : "注册儿童账号" }}
            </button>
            <p v-if="authError" class="auth-error">{{ authError }}</p>
          </div>
        </div>
      </section>

      <template v-else>
        <home-page v-if="route.path==='/'" />
        <explore-list-page v-else-if="route.path==='/explore'" />
        <chat-list-page v-else-if="route.path==='/chat'" />
        <rag-chat-page v-else-if="route.path==='/rag-chat'" />
        <memory-page v-else-if="route.path==='/memory'" />
        <not-found v-else />
      </template>
    </main>
  `,
  setup() {
    const authTab = ref("demo");
    const authLoading = ref(false);
    const authError = ref("");
    const autoLoggingIn = ref(false);
    const loginForm = reactive({ username: "", password: "" });
    const regForm = reactive({ username: "", password: "", nickname: "", age: 6 });

    // 开发模式：自动 demo 登录
    async function autoDemoLogin() {
      if (store.token) return;
      autoLoggingIn.value = true;
      try {
        const data = await AuthAPI.demo();
        setAuth(data);
        location.hash = "#/";
      } catch (e) {
        console.error("Auto demo login failed:", e.message);
      } finally {
        autoLoggingIn.value = false;
      }
    }

    function setAuth(data) {
      store.token = data.access_token;
      store.user = data.user;
      store.childProfile = data.child_profile;
      persistAuth();
    }

    async function doDemo() {
      authLoading.value = true;
      authError.value = "";
      try {
        const data = await AuthAPI.demo();
        setAuth(data);
        location.hash = "#/";
      } catch (e) {
        authError.value = e.message;
      } finally {
        authLoading.value = false;
      }
    }

    async function doLogin() {
      authLoading.value = true;
      authError.value = "";
      try {
        const data = await AuthAPI.login(loginForm.username, loginForm.password);
        setAuth(data);
        location.hash = "#/";
      } catch (e) {
        authError.value = e.message;
      } finally {
        authLoading.value = false;
      }
    }

    async function doRegister() {
      authLoading.value = true;
      authError.value = "";
      try {
        const payload = {
          username: regForm.username,
          password: regForm.password,
          role: "CHILD",
          nickname: regForm.nickname || undefined,
          age: regForm.age || undefined,
        };
        const data = await AuthAPI.register(payload);
        setAuth(data);
        location.hash = "#/";
      } catch (e) {
        authError.value = e.message;
      } finally {
        authLoading.value = false;
      }
    }

    function logout() {
      clearAuth();
      location.hash = "#/login";
    }

    watch(
      () => route.path,
      (p) => {
        if (store.token && p === "/login") location.hash = "#/";
        if (!store.token && p !== "/login") location.hash = "#/login";
      },
      { immediate: true }
    );

    onMounted(async () => {
      if (store.token) {
        try {
          const data = await AuthAPI.me();
          if (data.user) {
            store.user = data.user;
            store.childProfile = data.child_profile;
            persistAuth();
          }
        } catch (_) {
          clearAuth();
          location.hash = "#/login";
        }
      } else {
        location.hash = "#/login";
      }
    });

    return {
      store,
      route,
      authTab,
      authLoading,
      authError,
      autoLoggingIn,
      loginForm,
      regForm,
      doDemo,
      doLogin,
      doRegister,
      logout,
      autoDemoLogin,
    };
  },
  mounted() {
    this.autoDemoLogin();
  },
});

// ========== 主页组件 ==========
app.component("home-page", {
  template: `
    <section class="home-grid">
      <div class="panel explore-panel">
        <div class="panel-head">
          <h2>拍照探索</h2>
          <p>上传一张图片，AI 会告诉你它是什么。</p>
        </div>
        <label class="upload-box" for="exploreFile">
          <input id="exploreFile" type="file" accept="image/*" @change="onFileChange" />
          <span>{{ selectedFileName || "点击选择图片" }}</span>
        </label>
        <button class="primary-btn" :disabled="!selectedFile || uploading" @click="doExplore">
          {{ uploading ? "正在分析..." : "开始探索" }}
        </button>
        <div v-if="exploreResult" class="result-box">
          <div class="result-row"><span class="label">对象</span><strong>{{ exploreResult.object_name }}</strong></div>
          <div class="result-row"><span class="label">维度</span><span class="tag-dim">{{ exploreResult.growth_dimension }}</span></div>
          <div class="result-row"><span class="label">加分</span><strong class="score">+{{ exploreResult.score_delta }}</strong></div>
          <p class="fact">{{ exploreResult.scientific_fact }}</p>
          <img v-if="exploreResult.file_url" :src="assetUrl(exploreResult.file_url)" class="preview" />
        </div>
        <div v-else class="result-box empty">还没有探索记录，快上传一张图片试试吧！</div>
      </div>

      <div class="panel chat-panel">
        <div class="panel-head">
          <h2>AI 聊天</h2>
          <p>和 AI 一起探索世界，它会记住你说过的话。</p>
        </div>
        <div class="chat-thread" ref="chatThread">
          <div v-for="(msg, i) in chatMessages" :key="i" class="bubble" :class="msg.role">
            {{ msg.text }}
          </div>
          <div v-if="chatLoading && !streamingText" class="bubble assistant loading">AI 正在思考...</div>
        </div>
        <form class="chat-form" @submit.prevent="doChat">
          <input v-model="chatInput" type="text" placeholder="输入你的问题..." autocomplete="off" :disabled="chatLoading" />
          <button class="primary-btn" type="submit" :disabled="chatLoading || !chatInput.trim()">发送</button>
        </form>
      </div>

      <div class="panel memory-panel">
        <div class="panel-head">
          <h2>我的记忆</h2>
          <p>AI 记住的关于你的事。</p>
        </div>
        <div v-if="memoryEvents.length || memoryEntities.length" class="memory-box">
          <div v-if="memoryEvents.length" class="mem-section">
            <h3>最近事件</h3>
            <div v-for="e in memoryEvents.slice(0,5)" :key="e.id" class="mem-item">
              <span class="mem-type">{{ e.event_type }}</span>
              <span class="mem-time">{{ fmtTime(e.created_at) }}</span>
            </div>
          </div>
          <div v-if="memoryEntities.length" class="mem-section">
            <h3>记住的实体</h3>
            <div class="entity-chips">
              <span v-for="en in memoryEntities.slice(0,8)" :key="en.id" class="entity-chip">
                {{ en.entity_name }}
              </span>
            </div>
          </div>
        </div>
        <div v-else class="memory-box empty">还没有记忆数据，去探索或聊天吧！</div>
      </div>
    </section>
  `,
  setup() {
    const selectedFile = ref(null);
    const selectedFileName = ref("");
    const uploading = ref(false);
    const exploreResult = ref(null);
    const chatInput = ref("");
    const chatMessages = ref([]);
    const chatLoading = ref(false);
    const streamingText = ref("");
    const sessionId = ref(null);
    const memoryEvents = ref([]);
    const memoryEntities = ref([]);
    const chatThread = ref(null);

    function onFileChange(e) {
      const f = e.target.files?.[0] || null;
      selectedFile.value = f;
      selectedFileName.value = f?.name || "";
    }

    async function ensureSession() {
      if (sessionId.value) return sessionId.value;
      const s = await ChatAPI.createSession("主页对话");
      sessionId.value = s.id;
      return sessionId.value;
    }

    /** 加载会话的历史消息 */
    async function loadChatHistory() {
      try {
        // 先尝试找已有的"主页对话"session
        const sessions = await ChatAPI.listSessions();
        const homeSession = sessions.find((s) => s.title === "主页对话");
        if (homeSession) {
          sessionId.value = homeSession.id;
          // 获取完整 session 数据（含 messages）
          const detail = await ChatAPI.getSession(homeSession.id);
          if (detail.messages && detail.messages.length) {
            chatMessages.value = detail.messages.map((m) => ({
              role: m.role,
              text: m.content,
            }));
            await nextTick();
            scrollToBottom(chatThread.value);
          }
          return;
        }
      } catch (_) {}
      // 没有就新建
      await ensureSession();
    }

    async function doExplore() {
      if (!selectedFile.value) return;
      uploading.value = true;
      try {
        const result = await ExploreAPI.upload(selectedFile.value);
        exploreResult.value = result.record;
        selectedFile.value = null;
        selectedFileName.value = "";
        const f = document.getElementById("exploreFile");
        if (f) f.value = "";
        const me = await AuthAPI.me();
        if (me.child_profile) {
          store.childProfile = me.child_profile;
          persistAuth();
        }
        await loadMemory();
      } catch (e) {
        alert("探索失败：" + e.message);
      } finally {
        uploading.value = false;
      }
    }

    async function doChat() {
      const msg = chatInput.value.trim();
      if (!msg || chatLoading.value) return;
      chatInput.value = "";
      chatLoading.value = true;
      chatMessages.value.push({ role: "user", text: msg });
      chatMessages.value.push({ role: "assistant", text: "" });
      await nextTick();
      scrollToBottom(chatThread.value);
      const idx = chatMessages.value.length - 1;
      try {
        const sid = await ensureSession();
        await ChatAPI.streamMessage(
          sid,
          msg,
          (full) => {
            chatMessages.value[idx].text = full;
            streamingText.value = full;
            scrollToBottom(chatThread.value);
          },
          null,
          null
        );
        streamingText.value = "";
        await loadMemory();
      } catch (e) {
        chatMessages.value[idx].text = "请求失败：" + e.message;
      } finally {
        chatLoading.value = false;
        streamingText.value = "";
      }
    }

    async function loadMemory() {
      try {
        const data = await MemoryAPI.summary(8);
        memoryEvents.value = data.events || [];
        memoryEntities.value = data.entities || [];
      } catch (_) {}
    }

    onMounted(async () => {
      await loadMemory();
      await loadChatHistory();
    });

    return {
      selectedFile,
      selectedFileName,
      uploading,
      exploreResult,
      chatInput,
      chatMessages,
      chatLoading,
      streamingText,
      memoryEvents,
      memoryEntities,
      chatThread,
      onFileChange,
      doExplore,
      doChat,
      fmtTime,
      assetUrl,
    };
  },
});

// ========== 探索记录列表组件 ==========
app.component("explore-list-page", {
  template: `
    <section class="list-page">
      <div class="list-head">
        <h2>探索记录</h2>
        <button class="ghost-btn" @click="load">刷新</button>
      </div>
      <div v-if="loading" class="empty-state">加载中...</div>
      <div v-else-if="!records.length" class="empty-state">还没有探索记录，去主页上传一张图片吧！</div>
      <div v-else class="record-grid">
        <div v-for="r in records" :key="r.id" class="record-card">
          <img v-if="r.file_url" :src="assetUrl(r.file_url)" class="record-thumb" />
          <div class="record-body">
            <div class="record-head">
              <h3>{{ r.object_name }}</h3>
              <span class="tag-dim">{{ r.growth_dimension }}</span>
              <span class="score">+{{ r.score_delta }}</span>
            </div>
            <p>{{ r.scientific_fact }}</p>
            <span class="record-time">{{ fmtTime(r.created_at) }}</span>
          </div>
        </div>
      </div>
    </section>
  `,
  setup() {
    const records = ref([]);
    const loading = ref(false);

    async function load() {
      loading.value = true;
      try {
        records.value = await ExploreAPI.list(50);
      } catch (e) {
        alert("加载失败：" + e.message);
      } finally {
        loading.value = false;
      }
    }

    onMounted(load);
    return { records, loading, load, fmtTime, assetUrl };
  },
});

// ========== 聊天会话列表组件 ==========
app.component("chat-list-page", {
  template: `
    <section class="chat-page">
      <div class="chat-sidebar">
        <div class="list-head">
          <h2>对话</h2>
          <button class="primary-btn small" @click="newSession">+ 新对话</button>
        </div>
        <div v-if="!sessions.length" class="empty-state">还没有对话</div>
        <ul v-else class="session-list">
          <li v-for="s in sessions" :key="s.id" :class="{active: currentId===s.id}" @click="selectSession(s.id)">
            <div class="session-title">{{ s.title }}</div>
            <div class="session-time">{{ fmtTime(s.last_message_at || s.updated_at) }}</div>
          </li>
        </ul>
      </div>
      <div class="chat-main">
        <div v-if="!currentId" class="empty-state full">选择一个对话或新建对话</div>
        <template v-else>
          <div class="chat-thread big" ref="chatThread">
            <div v-for="(msg, i) in messages" :key="i" class="bubble" :class="msg.role">
              <div class="bubble-meta">{{ msg.role === 'user' ? '我' : 'AI' }}</div>
              {{ msg.content }}
            </div>
            <div v-if="chatLoading && !streamingText" class="bubble assistant loading">AI 正在思考...</div>
          </div>
          <form class="chat-form" @submit.prevent="doChat">
            <input v-model="input" type="text" placeholder="输入你的问题..." :disabled="chatLoading" />
            <button class="primary-btn" type="submit" :disabled="chatLoading || !input.trim()">发送</button>
          </form>
        </template>
      </div>
    </section>
  `,
  setup() {
    const sessions = ref([]);
    const currentId = ref(null);
    const messages = ref([]);
    const input = ref("");
    const chatLoading = ref(false);
    const streamingText = ref("");
    const chatThread = ref(null);

    async function loadSessions() {
      try {
        sessions.value = await ChatAPI.listSessions();
      } catch (_) {}
    }

    async function selectSession(id) {
      currentId.value = id;
      messages.value = [];
    }

    async function newSession() {
      try {
        const s = await ChatAPI.createSession("新的对话");
        sessions.value.unshift(s);
        currentId.value = s.id;
        messages.value = [];
      } catch (e) {
        alert("创建失败：" + e.message);
      }
    }

    async function doChat() {
      const msg = input.value.trim();
      if (!msg || chatLoading.value || !currentId.value) return;
      input.value = "";
      chatLoading.value = true;
      messages.value.push({ role: "user", content: msg });
      messages.value.push({ role: "assistant", content: "" });
      await nextTick();
      scrollToBottom(chatThread.value);
      const idx = messages.value.length - 1;
      try {
        await ChatAPI.streamMessage(
          currentId.value,
          msg,
          (full) => {
            messages.value[idx].content = full;
            streamingText.value = full;
            scrollToBottom(chatThread.value);
          },
          null,
          null
        );
      } catch (e) {
        messages.value[idx].content = "请求失败：" + e.message;
      } finally {
        chatLoading.value = false;
        streamingText.value = "";
        await loadSessions();
      }
    }

    onMounted(loadSessions);
    return {
      sessions,
      currentId,
      messages,
      input,
      chatLoading,
      streamingText,
      chatThread,
      loadSessions,
      selectSession,
      newSession,
      doChat,
      fmtTime,
    };
  },
});

// ========== RAG 问答页面组件 ==========
app.component("rag-chat-page", {
  template: `
    <section class="rag-chat-page">
      <div class="rag-header">
        <h2>🤖 RAG 智能问答</h2>
        <p>基于《十万个为什么》知识库 + 大模型，回答你的科普问题（保留最近 ${RAG_HISTORY_MIN_TURNS_HINT} 轮对话）</p>
        <button v-if="messages.length" class="new-chat-btn" @click="startNewChat" :disabled="loading">
          ✨ 开始新对话
        </button>
      </div>

      <div class="rag-suggestions" v-if="!messages.length">
        <h3>💡 试试这些问题：</h3>
        <div class="suggestion-chips">
          <button v-for="q in suggestions" :key="q" class="suggestion-chip" @click="quickAsk(q)">
            {{ q }}
          </button>
        </div>
      </div>

      <div class="chat-thread big rag-thread" ref="chatThread">
        <div v-for="(msg, i) in messages" :key="i" class="bubble" :class="msg.role">
          <div class="bubble-meta">{{ msg.role === 'user' ? '🧒 我' : '🤖 探索小助手' }}</div>
          <div class="bubble-content">{{ msg.content }}</div>
          <div v-if="msg.sources && msg.sources.length" class="rag-sources">
            <details>
              <summary>📚 参考来源 ({{ msg.sources.length }})</summary>
              <div v-for="(src, si) in msg.sources" :key="si" class="source-item">{{ src }}</div>
            </details>
          </div>
        </div>
        <div v-if="loading && !streamingText" class="bubble assistant loading">
          <div class="bubble-meta">🤖 探索小助手</div>
          正在从知识库中检索答案...
        </div>
      </div>

      <form class="chat-form rag-form" @submit.prevent="doAsk">
        <input v-model="input" type="text" placeholder="问一个为什么..." :disabled="loading" />
        <button class="primary-btn" type="submit" :disabled="loading || !input.trim()">
          {{ loading ? '回答中...' : '提问' }}
        </button>
      </form>
    </section>
  `,
  setup() {
    const input = ref("");
    const messages = ref([]);
    const loading = ref(false);
    const streamingText = ref("");
    const chatThread = ref(null);
    const conversationId = ref(null);
    const suggestions = [
      "为什么天空是蓝色的？",
      "为什么月亮会发光？",
      "为什么星星会一闪一闪？",
      "为什么会有日食和月食？",
      "为什么太阳会发光发热？",
    ];

    // 加载历史记录（如果有会话ID，从 localStorage 恢复）
    async function restoreHistory() {
      const savedId = localStorage.getItem("rag_conversation_id");
      if (!savedId) return;
      conversationId.value = savedId;
      try {
        const history = await RAGAPI.loadHistory(savedId);
        if (history && history.length) {
          messages.value = history.map((m) => ({
            role: m.role,
            content: m.content,
            sources: [],
          }));
          await nextTick();
          scrollToBottom(chatThread.value);
        }
      } catch (e) {
        console.warn("加载 RAG 历史失败:", e);
      }
    }

    async function doAsk() {
      const ask = input.value.trim();
      if (!ask || loading.value) return;
      input.value = "";
      loading.value = true;
      messages.value.push({ role: "user", content: ask });
      messages.value.push({ role: "assistant", content: "", sources: [] });
      await nextTick();
      scrollToBottom(chatThread.value);
      const idx = messages.value.length - 1;

      try {
        await RAGAPI.streamChat(
          ask,
          conversationId.value,
          (full) => {
            messages.value[idx].content = full;
            streamingText.value = full;
            scrollToBottom(chatThread.value);
          },
          (meta) => {
            if (meta.conversationId) {
              conversationId.value = meta.conversationId;
              localStorage.setItem("rag_conversation_id", meta.conversationId);
            }
            messages.value[idx].sources = meta.sources || [];
          },
          null,
          null
        );
      } catch (e) {
        messages.value[idx].content = "抱歉，出错了：" + e.message;
      } finally {
        loading.value = false;
        streamingText.value = "";
      }
    }

    function quickAsk(q) {
      input.value = q;
      doAsk();
    }

    // 开始新对话：清除当前会话历史 + 重置前端状态
    async function startNewChat() {
      if (loading.value) return;
      const oldId = conversationId.value;
      conversationId.value = null;
      messages.value = [];
      localStorage.removeItem("rag_conversation_id");
      if (oldId) {
        await RAGAPI.clearHistory(oldId);
      }
    }

    onMounted(restoreHistory);

    return {
      input,
      messages,
      loading,
      streamingText,
      chatThread,
      conversationId,
      suggestions,
      doAsk,
      quickAsk,
      restoreHistory,
      startNewChat,
    };
  },
});

// ========== 记忆页面组件 ==========
app.component("memory-page", {
  template: `
    <section class="memory-page">
      <div class="list-head">
        <h2>我的记忆</h2>
        <button class="ghost-btn" @click="loadAll">刷新</button>
      </div>
      <div class="mem-grid">
        <div class="panel">
          <h3>事件流</h3>
          <div v-if="!events.length" class="empty-state">暂无事件</div>
          <ul v-else class="event-list">
            <li v-for="e in events" :key="e.id">
              <div class="event-head">
                <span class="event-type">{{ e.event_type }}</span>
                <span class="event-time">{{ fmtTime(e.created_at) }}</span>
              </div>
              <pre class="event-payload">{{ JSON.stringify(e.payload_json, null, 2) }}</pre>
            </li>
          </ul>
        </div>
        <div class="panel">
          <h3>实体库</h3>
          <div v-if="!entities.length" class="empty-state">暂无实体</div>
          <div v-else class="entity-grid">
            <div v-for="en in entities" :key="en.id" class="entity-card">
              <span class="entity-type">{{ en.entity_type }}</span>
              <strong>{{ en.entity_name }}</strong>
              <span class="entity-time">{{ fmtTime(en.created_at) }}</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  `,
  setup() {
    const events = ref([]);
    const entities = ref([]);

    async function loadAll() {
      try {
        const [ev, en] = await Promise.all([MemoryAPI.events(50), MemoryAPI.entities(50)]);
        events.value = ev;
        entities.value = en;
      } catch (e) {
        alert("加载失败：" + e.message);
      }
    }

    onMounted(loadAll);
    return { events, entities, loadAll, fmtTime };
  },
});

// ========== 404 ==========
app.component("not-found", {
  template: `<section class="empty-state full"><h2>页面不存在</h2><a href="#/">返回主页</a></section>`,
});

app.mount("#app");
