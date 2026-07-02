import { createApp, reactive, ref, onMounted, watch, nextTick } from "https://unpkg.com/vue@3/dist/vue.esm-browser.js";

// ========== API_BASE 策略 ==========
// 开发环境（前端 5173 → 后端 8000 跨域）使用绝对地址
// 生产环境（同源 / 反代）使用相对路径
const DEV_API_BASE = "http://localhost:8001/api/v1";
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

// ========== 多智能体绘本共创 API ==========
const StoryAPI = {
  /** 创建故事（触发多智能体流水线） */
  create: (payload) =>
    api("/stories/create", { method: "POST", body: JSON.stringify(payload) }),

  /** 查询流水线状态 */
  status: (storyId) => api(`/stories/${storyId}/status`),

  /** 获取最终绘本结果 */
  result: (storyId) => api(`/stories/${storyId}/result`),

  /** 提交人工审核决策 */
  review: (storyId, action, comment) =>
    api(`/stories/${storyId}/review`, {
      method: "POST",
      body: JSON.stringify({ action, comment }),
    }),

  /** SSE 流式监听进度（onEvent 回调接收 {type, ...} 对象） */
  streamProgress: async (storyId, onEvent) => {
    const response = await fetch(`${API_BASE}/stories/${storyId}/stream`, {
      headers: { Authorization: `Bearer ${store.token}` },
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(text || `HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
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
            onEvent && onEvent({ type: "done" });
            return;
          }
          try {
            onEvent && onEvent(JSON.parse(raw));
          } catch (_) {}
        }
      }
    } catch (e) {
      console.warn("故事进度流中断:", e);
    }
  },

  /** 触发图片生成 */
  generateImages: (storyId) =>
    api(`/stories/${storyId}/images/generate`, { method: "POST" }),

  /** SSE 流式监听图片生成进度 */
  streamImageProgress: async (storyId, onEvent) => {
    const response = await fetch(`${API_BASE}/stories/${storyId}/images/stream`, {
      headers: { Authorization: `Bearer ${store.token}` },
    });
    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(text || `HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
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
            onEvent && onEvent({ type: "done" });
            return;
          }
          try {
            onEvent && onEvent(JSON.parse(raw));
          } catch (_) {}
        }
      }
    } catch (e) {
      console.warn("图片生成进度流中断:", e);
    }
  },

  /** 获取图片清单 */
  getImages: (storyId) => api(`/stories/${storyId}/images`),

  /** 单张图片文件 URL */
  imageUrl: (storyId, act) =>
    `${API_BASE}/stories/${storyId}/images/${act}/file?_t=${Date.now()}`,

  /** 我的绘本集列表 */
  listStorybooks: () => api(`/stories`),

  /** 打包下载 URL */
  packageUrl: (storyId) =>
    `${API_BASE}/stories/${storyId}/package`,
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
          <a :class="{active: route.path==='/story'}" href="#/story">绘本创作</a>
          <a :class="{active: route.path==='/storybooks'}" href="#/storybooks">我的绘本集</a>
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
        <story-create-page v-else-if="route.path==='/story'" />
        <storybook-list-page v-else-if="route.path==='/storybooks'" />
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

// ========== 绘本共创页面组件（多智能体） ==========
app.component("story-create-page", {
  template: `
    <section class="story-page">
      <div class="rag-header">
        <h2>🎨 绘本共创</h2>
        <p>AI 帮你创作专属中文绘本，适合 3-6 岁小朋友 🌈</p>
      </div>

      <!-- 输入区 -->
      <div class="story-input-card" v-if="!currentStoryId">
        <h3>💭 想听什么样的故事呢？</h3>
        <textarea v-model="prompt" rows="3" placeholder="比如：小兔子在森林里迷路了..." :disabled="creating"></textarea>
        <div class="story-options">
          <label>年龄段
            <select v-model="targetAge" :disabled="creating">
              <option value="3-6">3-6 岁（推荐）</option>
              <option value="6-10">6-10 岁</option>
            </select>
          </label>
          <label>主题
            <select v-model="theme" :disabled="creating">
              <option value="adventure">冒险探索</option>
              <option value="friendship">友情互助</option>
              <option value="warm">温暖治愈</option>
              <option value="courage">勇敢成长</option>
              <option value="share">分享快乐</option>
            </select>
          </label>
        </div>
        <div class="story-suggestions">
          <span>💡 试试：</span>
          <button v-for="s in suggestions" :key="s" class="suggestion-chip" @click="useSuggestion(s)" :disabled="creating">{{ s }}</button>
        </div>
        <button class="primary-btn big" :disabled="creating || !prompt.trim()" @click="createStory">
          {{ creating ? "✨ 正在启动创作..." : "🚀 开始创作绘本" }}
        </button>
        <p v-if="createError" class="auth-error">{{ createError }}</p>
      </div>

      <!-- 进度区 -->
      <div class="story-progress-card" v-if="currentStoryId">
        <h3>📖 正在创作绘本...</h3>
        <div class="story-progress-list">
          <div v-for="(p, i) in progressList" :key="i" class="progress-item" :class="p.state">
            <span class="progress-icon">{{ p.icon }}</span>
            <span class="progress-label">{{ p.label }}</span>
            <span class="progress-state">{{ p.stateText }}</span>
          </div>
        </div>
        <p class="story-tip" v-if="statusText">{{ statusText }}</p>
        <p class="story-error" v-if="progressError">{{ progressError }}</p>
      </div>

      <!-- 人工审核区 -->
      <div class="story-review-card" v-if="pendingReview">
        <h3>✋ 需要家长确认一下</h3>
        <p>AI 觉得这个故事还不错，但想请家长帮忙看看。</p>
        <input v-model="reviewComment" placeholder="修改建议（可选，修订时必填）" />
        <div class="story-review-btns">
          <button class="primary-btn" @click="submitReview('approve')" :disabled="reviewing">✅ 批准发布</button>
          <button class="ghost-btn" @click="submitReview('revise')" :disabled="reviewing">✏️ 修订</button>
          <button class="ghost-btn" @click="submitReview('reject')" :disabled="reviewing">❌ 拒绝</button>
        </div>
        <p v-if="reviewError" class="auth-error">{{ reviewError }}</p>
      </div>

      <!-- 结果区 -->
      <div class="story-result-card" v-if="result">
        <h3>🎉 绘本创作完成！</h3>
        <div class="story-meta">
          <span class="story-title">《{{ result.metadata.title }}》</span>
          <span class="badge" :class="result.metadata.risk_level">{{ result.metadata.risk_level }}</span>
          <span class="story-score">安全分 {{ result.metadata.safety_score }}</span>
        </div>
        <div class="story-content">
          <h4>📝 故事正文</h4>
          <pre class="story-text">{{ result.story_text }}</pre>
        </div>
        <div class="story-images" v-if="result.image_prompts && result.image_prompts.prompts">
          <h4>🎨 配图描述（共 {{ result.image_prompts.prompts.length }} 幕）</h4>
          <div v-for="(img, i) in result.image_prompts.prompts" :key="i" class="image-prompt-item">
            <div class="image-scene">第{{ img.act }}幕：{{ img.scene_cn }}</div>
            <div class="image-prompt-en">{{ img.prompt_en }}</div>
          </div>
        </div>
        <div class="story-safety" v-if="result.safety_report">
          <details>
            <summary>🛡️ 安全审核报告</summary>
            <pre class="story-text">{{ JSON.stringify(result.safety_report, null, 2) }}</pre>
          </details>
        </div>

        <!-- 图片生成区（image_generator agent） -->
        <div class="story-image-gen">
          <div class="image-gen-head">
            <h4>🎨 生成绘本图片</h4>
            <button class="primary-btn" @click="generateImages" :disabled="imageGenerating">
              {{ imageGenerating ? '正在生成…' : (imageSummary ? '重新生成图片' : '生成绘本图片') }}
            </button>
          </div>
          <div class="image-gen-tip" v-if="!imageSummary && !imageGenerating">
            点击按钮，AI 画师将为每幕故事绘制插图，过程实时显示
          </div>
          <div class="image-gen-error" v-if="imageError">⚠️ {{ imageError }}</div>

          <div class="image-grid" v-if="imageEvents.length">
            <div v-for="evt in imageEvents" :key="evt.act" class="image-cell" :class="evt.status">
              <div class="image-cell-head">
                <span class="image-cell-act">第 {{ evt.act }} 幕</span>
                <span class="image-cell-scene">{{ evt.scene_cn }}</span>
                <span class="image-cell-state">
                  <template v-if="evt.status === 'succeeded'">✅</template>
                  <template v-else-if="evt.status === 'failed'">❌</template>
                  <template v-else>⏳</template>
                </span>
              </div>
              <div class="image-cell-body">
                <img v-if="evt.status === 'succeeded'" :src="imageUrl(evt.act)" :alt="evt.scene_cn" />
                <div v-else-if="evt.status === 'failed'" class="image-cell-err">{{ evt.error }}</div>
                <div v-else class="image-cell-loading">正在绘制…</div>
              </div>
            </div>
          </div>

          <div class="image-gen-summary" v-if="imageSummary">
            <span>共 {{ imageSummary.total }} 幕 · 成功 {{ imageSummary.succeeded }} · 失败 {{ imageSummary.failed }}</span>
            <button class="ghost-btn" @click="openPackage" :disabled="imageSummary.succeeded === 0">
              📦 打包下载绘本
            </button>
          </div>
        </div>

        <button class="primary-btn" @click="resetAll">✨ 再创作一个</button>
      </div>
    </section>
  `,
  setup() {
    const prompt = ref("");
    const targetAge = ref("3-6");
    const theme = ref("adventure");
    const creating = ref(false);
    const createError = ref("");
    const currentStoryId = ref(null);
    const progressList = ref([
      { icon: "✍️", label: "规划故事大纲", state: "pending", stateText: "等待中" },
      { icon: "🚀", label: "撰写故事 + 生成配图", state: "pending", stateText: "等待中" },
      { icon: "🔍", label: "内容安全审核", state: "pending", stateText: "等待中" },
      { icon: "🎉", label: "绘本发布", state: "pending", stateText: "等待中" },
    ]);
    const statusText = ref("");
    const progressError = ref("");
    const pendingReview = ref(false);
    const reviewComment = ref("");
    const reviewing = ref(false);
    const reviewError = ref("");
    const result = ref(null);
    // 图片生成相关
    const imageGenerating = ref(false);
    const imageEvents = ref([]);   // [{act, status, image_url, local_path, error, finished, total}]
    const imageSummary = ref(null); // {total, succeeded, failed}
    const imageError = ref("");
    let pollTimer = null;
    const suggestions = [
      "小狐狸找朋友",
      "月亮忘了发光",
      "小熊的蜂蜜罐",
      "会飞的小鱼",
    ];

    function useSuggestion(s) {
      prompt.value = s;
    }

    function stageIndex(stage) {
      if (stage === "planning_done") return 0;
      if (stage === "creation_done") return 1;
      if (stage === "safety_checking" || stage === "run_safety_check") return 2;
      if (stage === "published" || stage === "publish_story") return 3;
      return -1;
    }

    function updateProgress(stage) {
      const idx = stageIndex(stage);
      progressList.value.forEach((p, i) => {
        if (i < idx) {
          p.state = "done";
          p.stateText = "完成 ✓";
        } else if (i === idx) {
          p.state = "active";
          p.stateText = "进行中...";
        } else {
          p.state = "pending";
          p.stateText = "等待中";
        }
      });
    }

    async function createStory() {
      const ask = prompt.value.trim();
      if (!ask || creating.value) return;
      creating.value = true;
      createError.value = "";
      result.value = null;
      pendingReview.value = false;
      try {
        const data = await StoryAPI.create({
          child_id: String(store.childProfile?.id || 1),
          story_prompt: ask,
          target_age: targetAge.value,
          preferred_theme: theme.value,
        });
        currentStoryId.value = data.story_id;
        statusText.value = data.message;
        startPolling();
      } catch (e) {
        createError.value = e.message;
      } finally {
        creating.value = false;
      }
    }

    function startPolling() {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = setInterval(pollStatus, 3000);
      pollStatus();
    }

    async function pollStatus() {
      if (!currentStoryId.value) return;
      try {
        const data = await StoryAPI.status(currentStoryId.value);
        if (data.stage && data.stage !== "init") updateProgress(data.stage);
        const score = data.safety_score ?? "-";
        const risk = data.risk_level ?? "-";
        statusText.value = "阶段: " + data.stage + "  ·  得分: " + score + "  ·  等级: " + risk;
        if (data.pending_review) {
          pendingReview.value = true;
          clearInterval(pollTimer);
          pollTimer = null;
        }
        if (["published", "rejected", "failed"].includes(data.stage)) {
          clearInterval(pollTimer);
          pollTimer = null;
          if (data.stage === "published") fetchResult();
        }
      } catch (e) {
        progressError.value = "查询状态失败: " + e.message;
      }
    }

    async function fetchResult() {
      try {
        result.value = await StoryAPI.result(currentStoryId.value);
      } catch (e) {
        progressError.value = "获取结果失败: " + e.message;
      }
    }

    async function submitReview(action) {
      if (!currentStoryId.value) return;
      if (action === "revise" && !reviewComment.value.trim()) {
        reviewError.value = "修订时请填写修改建议";
        return;
      }
      reviewing.value = true;
      reviewError.value = "";
      try {
        await StoryAPI.review(currentStoryId.value, action, reviewComment.value);
        pendingReview.value = false;
        reviewComment.value = "";
        startPolling();
      } catch (e) {
        reviewError.value = e.message;
      } finally {
        reviewing.value = false;
      }
    }

    function resetAll() {
      prompt.value = "";
      currentStoryId.value = null;
      result.value = null;
      pendingReview.value = false;
      progressError.value = "";
      statusText.value = "";
      reviewComment.value = "";
      reviewError.value = "";
      imageGenerating.value = false;
      imageEvents.value = [];
      imageSummary.value = null;
      imageError.value = "";
      progressList.value.forEach((p) => {
        p.state = "pending";
        p.stateText = "等待中";
      });
    }

    // 触发图片生成并订阅 SSE 流
    async function generateImages() {
      if (!currentStoryId.value || imageGenerating.value) return;
      imageGenerating.value = true;
      imageError.value = "";
      imageEvents.value = [];
      imageSummary.value = null;
      try {
        // 先触发任务（POST），再订阅流（SSE）
        await StoryAPI.generateImages(currentStoryId.value);
        // 订阅流式进度
        await StoryAPI.streamImageProgress(currentStoryId.value, (evt) => {
          if (evt.type === "start") {
            // 初始化占位
            imageEvents.value = (evt.acts || []).map((a) => ({
              act: a.act, scene_cn: a.scene_cn, status: "pending",
              progress: 0, image_url: null, local_path: null, error: null,
            }));
          } else if (evt.type === "image_done") {
            const idx = imageEvents.value.findIndex((e) => e.act === evt.act);
            if (idx >= 0) {
              imageEvents.value[idx] = {
                ...imageEvents.value[idx],
                status: evt.status,
                progress: evt.progress,
                image_url: evt.image_url,
                local_path: evt.local_path,
                error: evt.error,
              };
            }
          } else if (evt.type === "complete") {
            imageSummary.value = {
              total: evt.total,
              succeeded: evt.succeeded,
              failed: evt.failed,
            };
          } else if (evt.type === "done") {
            imageGenerating.value = false;
          } else if (evt.type === "error") {
            imageError.value = evt.message || "图片生成失败";
            imageGenerating.value = false;
          }
        });
      } catch (e) {
        imageError.value = e.message || "图片生成失败";
        imageGenerating.value = false;
      }
    }

    function imageUrl(act) {
      if (!currentStoryId.value) return "";
      return StoryAPI.imageUrl(currentStoryId.value, act);
    }

    function openPackage() {
      if (!currentStoryId.value) return;
      const url = StoryAPI.packageUrl(currentStoryId.value);
      // 带 token 下载（fetch 后转 blob）
      fetch(url, { headers: { Authorization: `Bearer ${store.token}` } })
        .then((r) => r.blob())
        .then((b) => {
          const a = document.createElement("a");
          a.href = URL.createObjectURL(b);
          a.download = `storybook_${currentStoryId.value}.zip`;
          a.click();
          URL.revokeObjectURL(a.href);
        })
        .catch((e) => { imageError.value = "下载失败: " + e.message; });
    }

    return {
      prompt,
      targetAge,
      theme,
      creating,
      createError,
      currentStoryId,
      progressList,
      statusText,
      progressError,
      pendingReview,
      reviewComment,
      reviewing,
      reviewError,
      result,
      suggestions,
      useSuggestion,
      createStory,
      submitReview,
      resetAll,
      generateImages,
      imageUrl,
      openPackage,
      imageGenerating,
      imageEvents,
      imageSummary,
      imageError,
    };
  },
});

// ========== 我的绘本集组件 ==========
app.component("storybook-list-page", {
  template: `
    <section class="storybook-page">
      <div class="list-head">
        <h2>📚 我的绘本集</h2>
        <div class="head-actions">
          <button class="ghost-btn" @click="loadList">刷新</button>
          <a class="primary-btn" href="#/story">✨ 创作新绘本</a>
        </div>
      </div>
      <div v-if="loading" class="empty">加载中…</div>
      <div v-else-if="error" class="empty err">⚠️ {{ error }}</div>
      <div v-else-if="!items.length" class="empty">
        <p>还没有绘本呢，去创作第一个吧！</p>
        <a class="primary-btn" href="#/story">✨ 开始创作</a>
      </div>
      <div v-else class="storybook-grid">
        <div v-for="book in items" :key="book.story_id" class="storybook-card" @click="openBook(book)">
          <div class="storybook-cover">
            <img v-if="book.cover_image_path" :src="coverUrl(book.story_id)" :alt="book.title" />
            <div v-else class="storybook-cover-placeholder">📖</div>
          </div>
          <div class="storybook-info">
            <div class="storybook-title">《{{ book.title }}》</div>
            <div class="storybook-meta">
              <span class="badge age">年龄 {{ book.target_age }}</span>
              <span class="badge" :class="book.risk_level">{{ book.risk_level }}</span>
              <span class="storybook-score" v-if="book.safety_score">安全 {{ book.safety_score }}</span>
            </div>
            <div class="storybook-meta">
              <span>🖼️ {{ book.image_count || 0 }} 幕</span>
              <span>{{ formatDate(book.updated_at) }}</span>
            </div>
          </div>
          <div class="storybook-actions">
            <button class="ghost-btn" @click.stop="downloadBook(book)">📦 下载</button>
          </div>
        </div>
      </div>
    </section>
  `,
  setup() {
    const loading = ref(true);
    const error = ref("");
    const items = ref([]);

    async function loadList() {
      loading.value = true;
      error.value = "";
      try {
        const data = await StoryAPI.listStorybooks();
        items.value = data.items || [];
      } catch (e) {
        error.value = e.message || "加载失败";
      } finally {
        loading.value = false;
      }
    }

    function coverUrl(storyId) {
      return \`\${DEV_API_BASE}/stories/\${storyId}/images/1/file?_t=\${Date.now()}\`;
    }

    function formatDate(s) {
      if (!s) return "";
      return s.replace("T", " ").slice(0, 16);
    }

    function openBook(book) {
      // 跳转到绘本创作页并加载该 story
      location.hash = `#/story?story_id=\${book.story_id}`;
    }

    function downloadBook(book) {
      const url = StoryAPI.packageUrl(book.story_id);
      fetch(url, { headers: { Authorization: \`Bearer \${store.token}\` } })
        .then((r) => r.blob())
        .then((b) => {
          const a = document.createElement("a");
          a.href = URL.createObjectURL(b);
          a.download = \`storybook_\${book.story_id}.zip\`;
          a.click();
          URL.revokeObjectURL(a.href);
        })
        .catch((e) => { error.value = "下载失败: " + e.message; });
    }

    loadList();

    return {
      loading, error, items,
      loadList, coverUrl, formatDate, openBook, downloadBook,
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
