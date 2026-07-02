import { createApp, reactive, ref, onMounted, computed, watch } from "https://unpkg.com/vue@3/dist/vue.esm-browser.js";

// ========== API 配置 ==========
const DEV_API_BASE = "http://localhost:8001/api/v1";
const PROD_API_BASE = "/api/v1";
const API_BASE =
  (location.hostname === "localhost" || location.hostname === "127.0.0.1")
    ? DEV_API_BASE : PROD_API_BASE;
const BACKEND_ORIGIN = API_BASE.replace(/\/api\/v1$/, "");

function assetUrl(url) {
  if (!url) return "";
  if (/^https?:\/\//.test(url)) return url;
  return BACKEND_ORIGIN + url;
}

// ========== 全局状态 ==========
const store = reactive({
  token: localStorage.getItem("kidoai_parent_token") || "",
  user: JSON.parse(localStorage.getItem("kidoai_parent_user") || "null"),
  currentChildId: null,
});

function setAuth(token, user) {
  store.token = token;
  store.user = user;
  localStorage.setItem("kidoai_parent_token", token);
  localStorage.setItem("kidoai_parent_user", JSON.stringify(user));
}

function clearAuth() {
  store.token = "";
  store.user = null;
  localStorage.removeItem("kidoai_parent_token");
  localStorage.removeItem("kidoai_parent_user");
}

// ========== 路由（基于 hash）==========
const route = reactive({ path: location.hash.replace(/^#/, "") || "/growth", tab: "growth" });
window.addEventListener("hashchange", () => {
  const hash = location.hash.replace(/^#/, "") || "/growth";
  const [path, tab] = hash.split("?");
  route.path = path;
  route.tab = tab || path.slice(1) || "growth";
});

function navigate(path) {
  location.hash = path;
}

function switchTab(tab) {
  route.tab = tab;
  navigate("/" + tab);
}

// ========== API 封装 ==========
async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (store.token) headers.set("Authorization", `Bearer ${store.token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (response.status === 401) { clearAuth(); navigate("/login"); throw new Error("未登录或登录已过期"); }
  const ctype = response.headers.get("content-type") || "";
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    if (ctype.includes("application/json")) { const err = await response.json(); detail = err.detail || JSON.stringify(err); }
    throw new Error(detail);
  }
  if (ctype.includes("application/json")) return response.json();
  return response.text();
}

// ========== 工具函数 ==========
function fmtTime(t) {
  if (!t) return "";
  const d = new Date(t);
  if (isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function fmtDate(d) {
  if (!d) return "";
  const date = new Date(d);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
function fmtRelative(t) {
  if (!t) return "";
  const diff = Date.now() - new Date(t).getTime();
  const min = Math.floor(diff / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min}分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}小时前`;
  return fmtDate(t);
}

// ========== 应用根组件 ==========
const app = createApp({
  setup() {
    const isLoggedIn = computed(() => !!store.token && store.user?.role === "PARENT");
    const loginReady = ref(false);

    // 开发模式：未登录时自动注册/登录家长 demo 账号
    async function autoLoginIfNeed() {
      if (store.token && store.user?.role === "PARENT") { loginReady.value = true; return; }
      const DEMO_PARENT = { username: "parent_demo", password: "demo123456", role: "PARENT" };
      try {
        await api("/auth/register", {
          method: "POST",
          body: JSON.stringify({ ...DEMO_PARENT, nickname: "测试家长" }),
        });
      } catch (_) { /* 已存在 */ }
      try {
        const data = await api("/auth/login", {
          method: "POST",
          body: JSON.stringify({ username: DEMO_PARENT.username, password: DEMO_PARENT.password }),
        });
        setAuth(data.access_token, data.user);
      } catch (_) { /* 保持未登录 */ }
      loginReady.value = true;
    }

    return { isLoggedIn, loginReady, route, store, autoLoginIfNeed };
  },
  async mounted() {
    await this.autoLoginIfNeed();
  },
  template: `
    <div class="app-shell">
      <div v-if="!loginReady" class="loading-spinner">加载中...</div>
      <template v-else>
        <component :is="currentView"></component>
        <bottom-nav v-if="isLoggedIn" />
      </template>
    </div>
  `,
  computed: {
    currentView() {
      if (!this.isLoggedIn) return "auth-page";
      switch (route.tab) {
        case "growth": return "growth-page";
        case "moments": return "moments-page";
        case "location": return "location-page";
        case "video": return "video-page";
        case "subscription": return "subscription-page";
        default: return "growth-page";
      }
    },
  },
});

// ========== 底部导航栏 ==========
app.component("bottom-nav", {
  template: `
    <nav class="bottom-nav">
      <button v-for="item in navItems" :key="item.key"
        class="nav-item" :class="{active: route.tab === item.key}"
        @click="switchTab(item.key)">
        <span class="nav-icon">{{ item.icon }}</span>
        <span class="nav-label">{{ item.label }}</span>
        <div class="nav-highlight"></div>
      </button>
    </nav>`,
  setup() {
    const navItems = [
      { key: "growth", label: "成长一览", icon: "\u{1F4CA}" },
      { key: "moments", label: "惊喜时刻", icon: "\u{2B50}" },
      { key: "location", label: "实时定位", icon: "\u{1F4CD}" },
      { key: "video", label: "视频沟通", icon: "\u{1F4F1}" },
      { key: "subscription", label: "订阅", icon: "\u{1F48E}" },
    ];
    return { navItems, switchTab, route };
  },
});

// ========== 登录/注册页 ==========
app.component("auth-page", {
  template: `
    <section class="auth-page">
      <div class="auth-card">
        <h1 class="auth-title">KidoAI 家长端</h1>
        <p class="auth-sub">陪伴孩子探索世界</p>
        <div class="tabs">
          <button :class="{active: mode==='login'}" @click="mode='login'">账号登录</button>
          <button :class="{active: mode==='register'}" @click="mode='register'">注册</button>
          <button :class="{active: mode==='otp'}" @click="mode='otp'">验证码登录</button>
        </div>
        <!-- 账号登录/注册 -->
        <form v-if="mode !== 'otp'" @submit.prevent="submit">
          <div class="field">
            <label>用户名</label>
            <input v-model="form.username" required minlength="3" maxlength="50" placeholder="3-50 字符" />
          </div>
          <div class="field">
            <label>密码</label>
            <input v-model="form.password" type="password" required minlength="6" maxlength="128" placeholder="至少 6 位" />
          </div>
          <button class="btn-primary" type="submit" :disabled="loading">
            {{ loading ? "处理中..." : (mode === "login" ? "登录" : "注册") }}
          </button>
          <p v-if="error" class="error">{{ error }}</p>
        </form>
        <!-- 验证码登录 -->
        <form v-else @submit.prevent="submitOtp">
          <div class="field">
            <label>手机号</label>
            <input v-model="otpForm.phone" required pattern="^1[3-9]\\d{9}$" maxlength="11" placeholder="中国大陆手机号" />
          </div>
          <div class="field otp-row">
            <label>验证码</label>
            <div class="otp-input-row">
              <input v-model="otpForm.code" required maxlength="6" pattern="\\d{6}" placeholder="6 位数字" />
              <button type="button" class="btn-otp" @click="sendOtp" :disabled="otpCooldown > 0 || sendingOtp">
                {{ otpCooldown > 0 ? otpCooldown + 's' : (sendingOtp ? '发送中' : '获取验证码') }}
              </button>
            </div>
          </div>
          <button class="btn-primary" type="submit" :disabled="loading">
            {{ loading ? "验证中..." : "验证码登录" }}
          </button>
          <p v-if="error" class="error">{{ error }}</p>
          <p v-if="otpHint" class="hint">{{ otpHint }}</p>
        </form>
      </div>
    </section>`,
  setup() {
    const mode = ref("login");
    const form = reactive({ username: "", password: "" });
    const loading = ref(false);
    const error = ref("");
    // OTP 相关
    const otpForm = reactive({ phone: "", code: "" });
    const otpCooldown = ref(0);
    const sendingOtp = ref(false);
    const otpHint = ref("");
    let cooldownTimer = null;

    async function submit() {
      loading.value = true; error.value = "";
      try {
        const endpoint = mode.value === "login" ? "/auth/login" : "/auth/register";
        const body = { ...form, role: "PARENT" };
        const data = await api(endpoint, { method: "POST", body: JSON.stringify(body) });
        if (data.user.role !== "PARENT") { error.value = "该账号不是家长角色"; loading.value = false; return; }
        setAuth(data.access_token, data.user);
        switchTab("growth");
      } catch (e) { error.value = e.message; } finally { loading.value = false; }
    }

    async function sendOtp() {
      if (!/^1[3-9]\d{9}$/.test(otpForm.phone)) {
        error.value = "请输入正确的手机号";
        return;
      }
      error.value = ""; otpHint.value = "";
      sendingOtp.value = true;
      try {
        await api("/notify/send-otp", {
          method: "POST",
          body: JSON.stringify({ phone: otpForm.phone }),
        });
        // 启动 60s 倒计时
        otpCooldown.value = 60;
        cooldownTimer = setInterval(() => {
          otpCooldown.value--;
          if (otpCooldown.value <= 0) {
            clearInterval(cooldownTimer);
          }
        }, 1000);
        otpHint.value = "验证码已发送，5 分钟内有效（开发 Mock 模式接受 123456）";
      } catch (e) {
        if (e.message.includes("429") || e.message.includes("频繁")) {
          error.value = "发送过于频繁，请稍后再试";
        } else {
          error.value = "验证码发送失败: " + e.message;
        }
      } finally {
        sendingOtp.value = false;
      }
    }

    async function submitOtp() {
      loading.value = true; error.value = "";
      try {
        // 1. 先校验验证码
        await api("/notify/verify-otp", {
          method: "POST",
          body: JSON.stringify({ phone: otpForm.phone, code: otpForm.code }),
        });
        // 2. 校验通过 → 用手机号登录（若不存在则注册）
        try {
          const data = await api("/auth/login", {
            method: "POST",
            body: JSON.stringify({ username: otpForm.phone, password: "otp_" + otpForm.code, role: "PARENT" }),
          });
          setAuth(data.access_token, data.user);
          switchTab("growth");
        } catch (loginErr) {
          // 账号不存在 → 自动注册
          try {
            const data = await api("/auth/register", {
              method: "POST",
              body: JSON.stringify({ username: otpForm.phone, password: "otp_" + otpForm.code, role: "PARENT", nickname: "家长" + otpForm.phone.slice(-4) }),
            });
            setAuth(data.access_token, data.user);
            switchTab("growth");
          } catch (regErr) {
            error.value = "注册失败: " + regErr.message;
          }
        }
      } catch (e) {
        error.value = e.message || "验证码校验失败";
      } finally {
        loading.value = false;
      }
    }

    return { mode, form, loading, error, submit, switchTab,
             otpForm, otpCooldown, sendingOtp, otpHint, sendOtp, submitOtp };
  },
});

// ========== 页面1：成长一览（Dashboard）==========
app.component("growth-page", {
  template: `
    <section class="page growth-page">
      <!-- 顶部区域 -->
      <div class="growth-header">
        <div class="status-bar">
          <span>{{ nowTime }}</span>
          <span>\u22EE \u22C6</span>
        </div>
        <div class="growth-top-row">
          <div class="greeting-text">
            <span class="hi">Hi</span>
            <span class="sub">{{ greetingText }}</span>
          </div>
          <div class="top-actions">
            <button class="icon-btn" title="通知">\u{1F514}</button>
            <button class="icon-btn" title="更多">\u22EF</button>
          </div>
        </div>

        <!-- 孩子卡片 -->
        <div v-if="child" class="child-card-main">
          <div class="child-avatar-lg">
            {{ child.nickname.charAt(0) }}
            <div class="child-avatar-badge">\u2705</div>
          </div>
          <div class="child-info-main">
            <div class="child-name-row">
              <h3>{{ child.nickname }}</h3>
              <span class="child-tag">{{ child.age }}岁</span>
            </div>
            <div class="child-detail-row">
              <span class="child-detail-item">\u2605 Lv.{{ child.current_level ?? 1 }}</span>
              <span class="child-detail-item">\u{1F31F} {{ child.explore_count ?? 0 }} 探索</span>
              <span class="child-detail-item">\uD83D\uDCAC {{ child.chat_session_count ?? 0 }} 对话</span>
            </div>
          </div>
          <div class="child-actions-col">
            <button class="action-circle-btn btn-call" @click="switchTab('video')" title="视频通话">\u{1F4DE}</button>
            <button class="action-circle-btn btn-msg" @click="switchTab('moments')" title="惊喜时刻">\u{1F4AC}</button>
          </div>
        </div>

        <!-- AI 对话气泡 -->
        <div v-if="aiSummary" class="ai-bubble-section">
          <div class="ai-bubble-arrow"></div>
          <div class="ai-bubble">
            <div class="ai-bubble-icon">\u{1F916}</div>
            <div class="ai-bubble-body">
              <div class="ai-bubble-label">AI 问答</div>
              <div class="ai-bubble-text">{{ aiSummary }}</div>
            </div>
          </div>
        </div>

        <!-- 今日统计 -->
        <div class="stats-row">
          <div class="stat-card-warm">
            <div class="stat-card-header">
              <div class="stat-card-icon orange">\u{1F3AF}</div>
              <span class="stat-card-title">累计探索</span>
            </div>
            <div class="stat-card-value">{{ stats.total_explore }}<span> 次</span></div>
            <div class="stat-card-desc">{{ stats.exploreDesc }}</div>
          </div>
          <div class="stat-card-warm">
            <div class="stat-card-header">
              <div class="stat-card-icon blue">\u{1F4DD}</div>
              <span class="stat-card-title">AI 对话</span>
            </div>
            <div class="stat-card-value">{{ stats.total_chat_sessions }}<span> 次</span></div>
            <div class="stat-card-desc">{{ stats.chatDesc }}</div>
          </div>
          <div class="stat-card-warm">
            <div class="stat-card-header">
              <div class="stat-card-icon green">\u{1F4B0}</div>
              <span class="stat-card-title">获得积分</span>
            </div>
            <div class="stat-card-value">{{ stats.total_tokens_earned ?? 0 }}<span> 分</span></div>
            <div class="stat-card-desc">探索越多积分越高</div>
          </div>
        </div>

        <!-- 成长档案（AI 分析报告） -->
        <div v-if="growthReport" class="growth-report-section">
          <div class="report-header-row">
            <h3>\u{1F4C8} 成长档案</h3>
            <span class="report-date-badge">{{ growthReport.report_date }}</span>
            <button v-if="!reportExpanded" class="btn-ghost-sm" @click="reportExpanded = true">展开详情</button>
            <button v-else class="btn-ghost-sm" @click="reportExpanded = false">收起</button>
          </div>

          <!-- AI 分析摘要 -->
          <div v-if="growthReport.ai_analysis" class="ai-analysis-box">
            <div class="analysis-label">\u{1F916} AI 智能分析</div>
            <div class="analysis-text" :class="{collapsed: !reportExpanded}">
              {{ formatMarkdown(growthReport.ai_analysis) }}
            </div>
          </div>

          <!-- 引导建议 -->
          <div v-if="growthReport.ai_suggestions && growthReport.ai_suggestions.length" class="suggestions-box">
            <div class="analysis-label">\u{1F4A1} 引导建议</div>
            <ul class="suggestion-list">
              <li v-for="(s, si) in growthReport.ai_suggestions" :key="si">{{ s }}</li>
            </ul>
          </div>

          <!-- 维度分布 -->
          <div v-if="growthReport.dimensions && growthReport.dimensions.length" class="dimensions-box">
            <div class="analysis-label">\u{1F3AF} 探索维度分布</div>
            <div class="dim-bars">
              <div v-for="(d, di) in growthReport.dimensions" :key="di" class="dim-bar-item">
                <span class="dim-name">{{ d.dimension }}</span>
                <div class="dim-bar-track">
                  <div class="dim-bar-fill" :style="{width: dimBarWidth(d.count)}"></div>
                </div>
                <span class="dim-count">{{ d.count }}次</span>
              </div>
            </div>
          </div>

          <!-- 最近探索 -->
          <div v-if="growthReport.recent_explore && growthReport.recent_explore.length" class="recent-explore-box">
            <div class="analysis-label">\u{1F50D} 最近探索记录</div>
            <div class="recent-list">
              <div v-for="(r, ri) in growthReport.recent_explore" :key="ri" class="recent-item">
                <span class="recent-object">{{ r.object_name }}</span>
                <span class="recent-dim tag-mini orange">{{ r.growth_dimension }}</span>
                <span class="recent-score green">+{{ r.score_delta }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 加载中 -->
        <div v-else-if="loadingReport" class="loading-report">
          <div class="loading-spinner"></div>
          <p>正在生成成长档案...</p>
        </div>

        <!-- 无数据提示 -->
        <div v-else-if="child && !loadingReport" class="empty-report">
          <p>\u{1F4CB} 暂无成长档案</p>
          <p class="hint">让孩子去探索新事物，系统会自动生成成长分析</p>
        </div>
      </div>

      <!-- 无孩子时显示添加入口 -->
      <div v-if="!loading && !child" class="page-content">
        <div class="empty-state" style="padding-top:80px;">
          <p style="font-size:48px;margin-bottom:12px;">\u{1F476}</p>
          <p>还没有绑定儿童账号</p>
          <button class="btn-primary" style="margin-top:16px;max-width:200px;" @click="showCreate = true">+ 添加儿童</button>
        </div>
      </div>

      <!-- 创建儿童弹窗 -->
      <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
        <div class="modal-card">
          <h3>创建儿童账号</h3>
          <form @submit.prevent="createChild">
            <div class="field"><label>用户名</label><input v-model="createForm.username" required placeholder="儿童登录用" /></div>
            <div class="field"><label>密码</label><input v-model="createForm.password" type="password" required placeholder="至少 6 位" /></div>
            <div class="field"><label>昵称</label><input v-model="createForm.nickname" required placeholder="孩子的小名" /></div>
            <div class="field"><label>年龄</label><input v-model.number="createForm.age" type="number" min="3" max="12" required /></div>
            <div class="modal-actions">
              <button type="button" class="btn-ghost" @click="showCreate = false">取消</button>
              <button type="submit" class="btn-primary" :disabled="creating" style="width:auto;padding:8px 20px;">
                {{ creating ? "创建中..." : "创建" }}
              </button>
            </div>
            <p v-if="createError" class="error">{{ createError }}</p>
          </form>
        </div>
      </div>
    </section>`,
  setup() {
    const children = ref([]);
    const child = ref(null);
    const loading = ref(false);
    const showCreate = ref(false);
    const creating = ref(false);
    const createError = ref("");
    const createForm = reactive({ username: "", password: "", nickname: "", age: 6 });
    const aiSummary = ref("");
    const nowTime = ref("");
    const stats = reactive({ total_explore: 0, total_chat_sessions: 0, total_tokens_earned: 0, exploreDesc: "", chatDesc: "" });
    // 成长档案相关
    const growthReport = ref(null);
    const loadingReport = ref(false);
    const reportExpanded = ref(false);

    // 更新时间
    function updateClock() {
      const d = new Date();
      nowTime.value = `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
    }

    const greetingText = computed(() => {
      const h = new Date().getHours();
      if (h < 6) return "夜深了，注意休息";
      if (h < 11) return "美好的一天开始了";
      if (h < 14) return "中午好";
      if (h < 18) return "下午好";
      return "晚上好";
    });

    async function loadChildren() {
      loading.value = true;
      try {
        children.value = await api("/parent/children");
        if (children.value.length > 0) {
          child.value = children.value[0];
          store.currentChildId = child.value.id;
          loadStats();
          loadGrowthReport();
        } else {
          // 开发模式：自动创建一个儿童账号
          try {
            await api("/parent/children", {
              method: "POST",
              body: JSON.stringify({
                username: "child_demo_" + Date.now(),
                password: "demo123456",
                nickname: "小探索家",
                age: 6,
              }),
            });
            // 重新加载
            children.value = await api("/parent/children");
            if (children.value.length > 0) {
              child.value = children.value[0];
              store.currentChildId = child.value.id;
              loadStats();
              loadGrowthReport();
            }
          } catch (_) { /* 创建失败 */ }
        }
      } catch (e) { console.error(e); } finally { loading.value = false; }
    }

    async function loadStats() {
      if (!child.value) return;
      try {
        const r = await api(`/parent/children/${child.value.id}/report`);
        stats.total_explore = r.total_explore ?? 0;
        stats.total_chat_sessions = r.total_chat_sessions ?? 0;
        stats.total_tokens_earned = r.total_tokens_earned ?? 0;
        stats.exploreDesc = child.value.nickname + "累计探索了 " + stats.total_explore + " 个新事物";
        stats.chatDesc = "完成 " + stats.total_chat_sessions + " 次AI对话";
      } catch (e) { /* 静默 */ }
    }

    async function loadGrowthReport() {
      if (!child.value) return;
      loadingReport.value = true;
      try {
        const r = await api(`/parent/children/${child.value.id}/report/ai`);
        growthReport.value = r;
        // 同时更新 aiSummary（兼容旧逻辑）
        if (r.ai_analysis) {
          const lines = r.ai_analysis.split("\n").filter(l => l.trim() && !l.startsWith("##"));
          aiSummary.value = lines[0]?.replace(/\*\*/g, "").slice(0, 80) || "";
        }
      } catch (e) {
        growthReport.value = null;
      } finally {
        loadingReport.value = false;
      }
    }

    /** 简单格式化 markdown 文本 */
    function formatMarkdown(text) {
      if (!text) return "";
      return text.replace(/#{1,3}\s/g, "").replace(/\*\*(.+?)\*\*/g, "$1").replace(/\n{2,}/g, "\n").trim();
    }

    /** 计算维度条宽度百分比 */
    function dimBarWidth(count) {
      if (!growthReport.value?.dimensions?.length) return "0%";
      const max = Math.max(...growthReport.value.dimensions.map(d => d.count), 1);
      return Math.round((count / max) * 100) + "%";
    }

    async function createChild() {
      creating.value = true; createError.value = "";
      try {
        await api("/parent/children", { method: "POST", body: JSON.stringify(createForm) });
        showCreate.value = false;
        createForm.username = ""; createForm.password = ""; createForm.nickname = ""; createForm.age = 6;
        await loadChildren();
      } catch (e) { createError.value = e.message; } finally { creating.value = false; }
    }

    let clockTimer;
    onMounted(() => {
      updateClock();
      clockTimer = setInterval(updateClock, 30000);
      loadChildren();
    });

    return { child, loading, showCreate, creating, createError, createForm,
             aiSummary, nowTime, greetingText, stats,
             growthReport, loadingReport, reportExpanded,
             formatMarkdown, dimBarWidth, loadGrowthReport, createChild, switchTab };
  },
});

// ========== 页面2：惊喜时刻（时间线）==========
app.component("moments-page", {
  template: `
    <section class="page moments-page">
      <div class="moments-header">
        <div class="status-bar"><span>{{ nowTime }}</span><span>\u22EE \u22C6</span></div>
        <h2>足迹</h2>
        <div class="moments-date-row">
          <span>\u{1F4C5}</span><span>{{ todayStr }}</span>
        </div>
      </div>

      <!-- 时间线 -->
      <div class="timeline" v-if="moments.length">
        <div v-for="(m, idx) in moments" :key="idx" class="timeline-item">
          <div class="timeline-time">{{ m.time }}</div>
          <div class="timeline-dot" :class="m.type"></div>
          <div class="timeline-bubble" :class="{self: m.self}">
            <!-- 聊天类型：显示头像+名字+消息 -->
            <template v-if="m.type === 'chat'">
              <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                <span style="font-size:16px;">{{ m.self ? '\u{1F476}' : '\u{1F916}' }}</span>
                <span style="font-size:11px;font-weight:600;color:var(--muted);">{{ m.self ? m.childName : '探索小助手' }}</span>
              </div>
              <div class="timeline-bubble-msg">{{ m.text }}</div>
              <!-- AI 回复带反应按钮 -->
              <div v-if="!m.self && m.text" class="timeline-bubble-meta" style="margin-top:8px;">
                <button v-for="emoji in ['\u2764\uFE0F','\u{1F44D}','\u{1F440}','\u2B50','\u{1F389}']"
                  :key="emoji" class="reaction-btn" @click="toggleReaction(idx, emoji)"
                  :class="{active: m.reactions?.includes(emoji)}">{{ emoji }}</button>
              </div>
            </template>
            <!-- 探索类型：显示图片+描述 -->
            <template v-else>
              <img v-if="m.img" :src="assetUrl(m.img)" class="timeline-bubble-img" />
              <div class="timeline-bubble-msg">{{ m.text }}</div>
              <div v-if="m.tags && m.tags.length" class="timeline-bubble-meta">
                <span v-for="(t, ti) in m.tags" :key="ti" class="tag-mini" :class="t.color">{{ t.text }}</span>
              </div>
            </template>
          </div>
        </div>
      </div>

      <div v-else-if="!loadingMoments" class="empty-state">
        <p style="font-size:40px;margin-bottom:8px;">\u2728</p>
        <p>还没有探索记录哦<br/>快去和孩子一起探索吧！</p>
      </div>
      <div v-else class="empty-state"><div class="loading-spinner"></div><p style="margin-top:10px;">加载中...</p></div>

      <!-- 底部操作栏（设计稿风格） -->
      <div class="moments-actions-bar">
        <button class="btn-action-outline" @click="refreshMoments">\u{1F504} 刷新</button>
        <button class="btn-action-primary" @click="switchTab('growth')">\u{1F4CA} 查看报告</button>
      </div>
    </section>`,
  setup() {
    const moments = ref([]);
    const loadingMoments = ref(false);
    const nowTime = ref("");
    const childName = ref("小探索家");

    function updateClock() {
      const d = new Date();
      nowTime.value = `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
    }

    const todayStr = computed(() => {
      const d = new Date();
      return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
    });

    function toggleReaction(idx, emoji) {
      const m = moments.value[idx];
      if (!m.reactions) m.reactions = [];
      const i = m.reactions.indexOf(emoji);
      if (i >= 0) m.reactions.splice(i, 1);
      else m.reactions.push(emoji);
    }

    async function refreshMoments() {
      if (!store.currentChildId) return;
      loadingMoments.value = true;
      try {
        const cid = store.currentChildId;
        // 加载探索记录
        let exploreList = [];
        try { exploreList = await api(`/parent/children/${cid}/explore-records`); } catch (e) { /* skip */ }
        // 加载聊天会话列表
        let sessions = [];
        try { sessions = await api(`/parent/children/${cid}/chat-sessions`); } catch (e) { /* skip */ }
        const list = [];

        // 探索记录 → 时间线条目
        for (const r of (exploreList || []).slice(0, 10)) {
          list.push({
            type: "explore",
            time: fmtTime(r.created_at),
            text: r.scientific_fact || `探索了「${r.object_name || '未知物体'}」`,
            img: r.file_url || null,
            self: false,
            tags: [
              { text: r.growth_dimension || "SCIENCE", color: "orange" },
              { text: "+" + (r.score_delta || 5), color: "green" },
            ],
            reactions: [],
          });
        }

        // 聊天会话 → 时间线条目（取每个session的最后一条）
        for (const s of (sessions || []).slice(0, 5)) {
          const isUser = s.title?.includes("主页对话");
          list.push({
            type: "chat",
            time: fmtTime(s.updated_at || s.created_at),
            text: isUser ? "今天问了好多有趣的问题呢~" : "你对什么感兴趣呢？我们一起去探索吧！",
            img: null,
            self: isUser,
            childName: childName.value,
            reactions: isUser ? [] : ["\u2764\uFE0F", "\u{1F44D}"],
          });
        }

        // 按时间倒序排列
        list.sort((a, b) => {
          const ta = a.time.split(":").map(Number), tb = b.time.split(":").map(Number);
          return (tb[0] * 60 + tb[1]) - (ta[0] * 60 + ta[1]);
        });

        moments.value = list;
      } catch (e) { console.error(e); } finally { loadingMoments.value = false; }
    }

    onMounted(() => { updateClock(); refreshMoments(); setInterval(updateClock, 30000); });
    watch(() => store.currentChildId, () => { refreshMoments(); });

    return { moments, loadingMoments, nowTime, todayStr, childName, refreshMoments, toggleReaction, switchTab, assetUrl };
  },
});

// ========== 页面3：实时定位（地图）==========
app.component("location-page", {
  template: `
    <section class="page location-page">
      <div class="location-header">
        <div class="status-bar"><span>{{ nowTime }}</span><span>\u22EE \u22C6</span></div>
        <h2>定位</h2>
      </div>

      <!-- 安全提醒横幅 -->
      <div class="alert-banner" :class="{warning: !isSafe}">
        <span class="alert-icon">{{ isSafe ? '\u{1F3D3}\uFE0F' : '\u26A0\uFE0F' }}</span>
        <span>{{ alertMsg }}</span>
      </div>

      <!-- 地图区域 -->
      <div class="map-container">
        <div class="map-placeholder">
          <span style="font-size:48px;margin-bottom:8px;">\u{1F5FA}</span>
          <span>地图加载中...</span>
        </div>
        <!-- 模拟标记点 -->
        <div class="map-marker map-marker-child" :style="{left: childPos.x + '%', top: childPos.y + '%'}">\u{1F476}</div>
        <div class="map-marker map-marker-home">\u{1F3E0}</div>
        <div class="map-marker map-marker-school">\u{1F393}</div>
        <div class="map-marker map-marker-park">\u{1F3DE}</div>
        <!-- 图例 -->
        <div class="map-legend">
          <div class="legend-item"><span>\u{1F476}</span> 当前位置</div>
          <div class="legend-item"><span>\u{1F3E0}</span> 家</div>
          <div class="legend-item"><span>\u{1F393}</span> 学校</div>
          <div class="legend-item"><span>\u{1F3DE}</span> 公园</div>
        </div>
      </div>

      <!-- 位置信息卡片 -->
      <div class="location-info-card">
        <div class="location-info-row">
          <div class="location-avatar-s">{{ childName.charAt(0) }}</div>
          <div class="location-info-text">
            <h4>{{ childName }}</h4>
            <p>{{ locationAddress }}</p>
            <p style="font-size:11px;color:var(--muted);margin-top:2px;">{{ lastUpdate }}</p>
          </div>
          <span class="location-status-tag" :class="isSafe ? 'status-safe' : 'status-warning'">
            {{ isSafe ? '\u2705 在安全区域内' : '\u26A0\uFE0F 已离开安全区' }}
          </span>
        </div>
        <!-- 电量条 -->
        <div style="display:flex;align-items:center;gap:8px;margin-top:10px;padding-top:8px;border-top:1px solid var(--line);">
          <span style="font-size:12px;">\uD83D\uDD0B 电量</span>
          <div style="flex:1;height:6px;background:#EEE;border-radius:3px;overflow:hidden;">
            <div style="height:100%;width:64%;background:var(--success);border-radius:3px;transition:width 0.3s;"></div>
          </div>
          <span style="font-size:11px;font-weight:600;color:var(--success);">64%</span>
        </div>
      </div>

      <!-- 底部操作栏 -->
      <div class="moments-actions-bar">
        <button class="btn-action-outline" @click="refreshLocation">\u{1F504} 刷新位置</button>
        <button class="btn-action-primary" @click="switchTab('video')">\u{1F4DE} 视频通话</button>
      </div>
    </section>`,
  setup() {
    const nowTime = ref("");
    const lastUpdate = ref("");
    const childName = ref("小探索家");
    const locationAddress = ref("正在获取位置...");
    const alertMsg = ref("\u{1F3D3}\uFE0F 您的小朋友现在很安全！");
    const isSafe = ref(true);
    const childPos = reactive({ x: 45, y: 55 });

    const locations = [
      "阳光小区北门附近", "幸福路和建设街交叉口",
      "中心公园游乐区", "学校门口等待区", "社区图书馆旁",
    ];

    function updateClock() {
      const d = new Date();
      nowTime.value = `${String(d.getHours()).padStart(2,"0")}:${String(d.getMinutes()).padStart(2,"0")}`;
      lastUpdate.value = `${nowTime.value} 更新`;
    }

    function updateLocationInfo() {
      if (store.user?.username) childName.value = store.user.username;
      locationAddress.value = locations[Math.floor(Math.random() * locations.length)];
      // 模拟孩子位置微动
      childPos.x = 40 + Math.random() * 20;
      childPos.y = 45 + Math.random() * 20;
      // 随机安全状态
      isSafe.value = Math.random() > 0.15;
      alertMsg.value = isSafe.value
        ? `\u{1F3D3}\uFE0F 您的小朋友现在很安全！${nowTime.value} 已离开安全区`.replace("已离开", "在")
        : `\u26A0\uFE0F 您的小朋友离开了安全区域！${nowTime.value} 请关注`;
    }

    function refreshLocation() { updateLocationInfo(); }

    onMounted(() => {
      updateClock();
      updateLocationInfo();
      setInterval(updateClock, 30000);
      setInterval(updateLocationInfo, 60000);
    });

    return { nowTime, lastUpdate, childName, locationAddress, alertMsg, isSafe, childPos, refreshLocation, switchTab };
  },
});

// ========== 页面4：视频沟通（视频通话界面）==========
app.component("video-page", {
  template: `
    <section class="video-page">
      <div class="video-fullscreen">
        <!-- 顶部栏 -->
        <div class="video-topbar">
          <div class="video-timer">{{ callTimer }}</div>
          <button class="btn-ghost" style="color:#fff;border-color:rgba(255,255,255,0.3);" @click="minimizeCall">\u25BC</button>
        </div>

        <!-- 主画面（孩子端视频）-->
        <div style="text-align:center;width:100%;">
          <div class="video-placeholder-bg">\u{1F476}</div>
        </div>

        <!-- 画中画（家长摄像头预览）-->
        <div class="video-pip">
          <div style="width:100%;height:100%;background:#bbb;display:flex;align-items:center;justify-content:center;font-size:32px;color:#999;">\u{1F464}</div>
        </div>

        <!-- 控制标签 -->
        <div class="video-labels">
          <div class="video-label">看到我了吗</div>
          <div class="video-label">拍摄照片</div>
          <div class="video-label">录制时刻</div>
        </div>

        <!-- 控制按钮 -->
        <div class="video-controls">
          <div style="display:flex;flex-direction:column;align-items:center;gap:4px;">
            <button class="video-ctrl-btn ctrl-mic" :class="{off:!micOn}" @click="micOn=!micOn">
              {{ micOn ? '\u{1F3A4}' : '\u{1F507}' }}
            </button>
            <span class="video-label">看到我了吗</span>
          </div>
          <div style="display:flex;flex-direction:column;align-items:center;gap:4px;">
            <button class="video-ctrl-btn ctrl-camera" :class="{off:!cameraOn}" @click="cameraOn=!cameraOn">
              {{ cameraOn ? '\u{1F4F7}' : '\u{1F534}' }}
            </button>
            <span class="video-label">拍摄照片</span>
          </div>
          <div style="display:flex;flex-direction:column;align-items:center;gap:4px;">
            <button class="video-ctrl-btn ctrl-switch" @click="toggleCamera">\u{1F504}</button>
            <span class="video-label">录制时刻</span>
          </div>
          <div style="display:flex;flex-direction:column;align-items:center;gap:4px;">
            <button class="video-ctrl-btn ctrl-end" @click="endCall">\u{1F4DE}</button>
          </div>
        </div>
      </div>
    </section>`,
  setup() {
    const micOn = ref(true);
    const cameraOn = ref(true);
    const callActive = ref(true);
    const seconds = ref(0);

    let timerInterval;

    const callTimer = computed(() => {
      const m = Math.floor(seconds.value / 60);
      const s = seconds.value % 60;
      return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    });

    function startTimer() {
      timerInterval = setInterval(() => { seconds.value++; }, 1000);
    }

    function endCall() {
      clearInterval(timerInterval);
      alert("通话已结束");
      switchTab("growth");
    }

    function minimizeCall() {
      alert("最小化到后台");
    }

    function toggleCamera() {
      // 切换前后摄像头
      cameraOn.value = !cameraOn.value;
      setTimeout(() => { cameraOn.value = true; }, 200);
    }

    onMounted(startTimer);

    return { micOn, cameraOn, callActive, callTimer, endCall, minimizeCall, toggleCamera, switchTab };
  },
});

// ========== 订阅页面 ==========
app.component("subscription-page", {
  template: `
    <section class="subscription-page">
      <header class="sub-header">
        <h1>\u{1F48E} 升级会员</h1>
        <p class="sub-subtitle">解锁全部功能，给孩子更好的成长体验</p>
      </header>

      <!-- 当前订阅状态 -->
      <div class="sub-current-card" v-if="currentSub">
        <div class="sub-current-info">
          <span class="sub-current-badge" :class="currentSub.plan?.tier">
            {{ currentSub.plan?.name || '免费版' }}
          </span>
          <span class="sub-current-status" v-if="currentSub.status === 'ACTIVE'">\u2705 已激活</span>
          <span class="sub-current-status" v-else>\u26A0\uFE0F {{ currentSub.status }}</span>
        </div>
        <div class="sub-current-expire" v-if="currentSub.plan?.tier !== 'FREE'">
          到期时间：{{ formatDate(currentSub.expire_at) }}
        </div>
        <div class="sub-current-expire" v-else>
          免费版 · 每日{{ currentSub.plan?.features_json?.explore_daily_limit || 3 }}次探索
        </div>
      </div>

      <!-- 套餐选择 -->
      <div class="sub-section-title">选择套餐</div>
      <div class="sub-plans-grid">
        <div v-for="plan in paidPlans" :key="plan.code"
          class="sub-plan-card"
          :class="{selected: selectedPlanCode === plan.code, popular: plan.code === 'yearly_standard'}"
          @click="selectedPlanCode = plan.code">
          <div class="sub-plan-popular" v-if="plan.code === 'yearly_standard'">\u{1F525} 推荐</div>
          <div class="sub-plan-name">{{ plan.name }}</div>
          <div class="sub-plan-price">
            <span class="price-symbol">\u00A5</span>
            <span class="price-amount">{{ (plan.price_cents / 100).toFixed(0) }}</span>
            <span class="price-cycle">/{{ plan.billing_cycle === 'MONTHLY' ? '月' : '年' }}</span>
          </div>
          <div class="sub-plan-features">
            <div v-if="plan.tier === 'STANDARD'">
              <p>\u2705 无限AI探索</p>
              <p>\u2705 无限AI对话</p>
              <p>\u2705 完整成长报告</p>
              <p>\u2705 90天数据保留</p>
            </div>
            <div v-else>
              <p>\u2705 无限AI探索</p>
              <p>\u2705 无限AI对话</p>
              <p>\u2705 完整成长报告</p>
              <p>\u2705 \u{1F4CD} 实时定位</p>
              <p>\u2705 \u{1F4F1} 视频沟通</p>
              <p>\u2705 最多{{ plan.max_children }}个孩子</p>
              <p>\u2705 永久数据保留</p>
            </div>
          </div>
        </div>
      </div>

      <!-- 支付方式 -->
      <div class="sub-section-title">支付方式</div>
      <div class="sub-pay-methods">
        <label class="sub-pay-option" :class="{selected: payChannel === 'ALIPAY'}">
          <input type="radio" v-model="payChannel" value="ALIPAY" />
          <span class="pay-icon">\u{1F4B3}</span>
          <span>支付宝</span>
        </label>
        <label class="sub-pay-option" :class="{selected: payChannel === 'WECHAT'}">
          <input type="radio" v-model="payChannel" value="WECHAT" />
          <span class="pay-icon">\u{1F4F1}</span>
          <span>微信支付</span>
        </label>
      </div>

      <!-- 确认按钮 -->
      <button class="sub-pay-btn" :disabled="!selectedPlanCode || paying"
        @click="handleCreateOrder">
        <span v-if="paying">处理中...</span>
        <span v-else>立即订阅 \u00A5{{ selectedPlanPrice }}</span>
      </button>

      <!-- 支付弹窗 -->
      <div class="sub-pay-modal" v-if="payModal.show">
        <div class="sub-pay-modal-content">
          <div class="sub-pay-modal-header">
            <h3>{{ payModal.channel === 'ALIPAY' ? '\u{1F4B3} 支付宝支付' : '\u{1F4F1} 微信支付' }}</h3>
            <button @click="closePayModal" class="modal-close">\u2716</button>
          </div>
          <div class="sub-pay-modal-body">
            <div class="pay-amount">\u00A5{{ (payModal.amount / 100).toFixed(2) }}</div>
            <p class="pay-plan-name">{{ payModal.planName }}</p>

            <!-- 支付宝：跳转链接 -->
            <div v-if="payModal.channel === 'ALIPAY' && payModal.payUrl" class="pay-alipay">
              <a :href="payModal.payUrl" target="_blank" class="pay-go-btn">
                \u{1F4B3} 点击前往支付宝支付
              </a>
              <p class="pay-tip">支付完成后请点击下方"我已支付"</p>
            </div>

            <!-- 微信：二维码 -->
            <div v-if="payModal.channel === 'WECHAT' && payModal.qrCode" class="pay-wechat">
              <div class="pay-qr-placeholder">
                <div class="qr-code-display">{{ payModal.qrCode }}</div>
                <p class="pay-tip">请用微信扫码支付</p>
              </div>
            </div>

            <!-- Mock 模式提示 -->
            <div v-if="payModal.mock" class="pay-mock-tip">
              \u{1F4E2} 开发模式：点击下方按钮模拟支付成功
            </div>

            <!-- 轮询状态 -->
            <div class="pay-polling" v-if="polling">
              <span class="polling-spinner"></span> 等待支付结果...
            </div>

            <div class="pay-actions">
              <button class="pay-check-btn" @click="checkPayResult" :disabled="polling">
                我已支付
              </button>
              <button v-if="payModal.mock" class="pay-mock-btn" @click="mockPay">
                \u{1F680} 模拟支付成功
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 订单历史 -->
      <div class="sub-section-title" v-if="orders.length">订单记录</div>
      <div class="sub-orders" v-if="orders.length">
        <div v-for="o in orders" :key="o.order_no" class="sub-order-item">
          <div class="order-info">
            <span class="order-plan">{{ o.plan_name }}</span>
            <span class="order-amount">\u00A5{{ (o.amount_cents / 100).toFixed(2) }}</span>
          </div>
          <div class="order-meta">
            <span class="order-channel">{{ o.channel === 'ALIPAY' ? '\u{1F4B3} 支付宝' : '\u{1F4F1} 微信' }}</span>
            <span class="order-status" :class="o.status.toLowerCase()">{{ orderStatusText(o.status) }}</span>
          </div>
        </div>
      </div>

      <div style="height: 80px"></div>

      <!-- 退出登录 -->
      <div class="sub-section-title">账号</div>
      <div class="sub-notify-card">
        <button class="btn-notify logout-btn" @click="handleLogout">退出登录</button>
      </div>

      <!-- 通知测试区 -->
      <div class="sub-section-title">通知测试</div>
      <div class="sub-notify-card">
        <p class="notify-desc">测试短信/邮件通知系统是否正常工作</p>
        <div class="notify-tabs">
          <button :class="{active: notifyTab==='sms'}" @click="notifyTab='sms'">短信验证码</button>
          <button :class="{active: notifyTab==='email'}" @click="notifyTab='email'">测试邮件</button>
        </div>
        <!-- 短信测试 -->
        <div v-if="notifyTab==='sms'" class="notify-form">
          <input v-model="notifyPhone" placeholder="手机号" pattern="^1[3-9]\d{9}$" maxlength="11" />
          <button class="btn-notify" @click="sendTestOtp" :disabled="notifySending">
            {{ notifySending ? '发送中...' : '发送验证码' }}
          </button>
          <p v-if="notifyMsg" class="notify-msg" :class="{err: notifyErr}">{{ notifyMsg }}</p>
        </div>
        <!-- 邮件测试 -->
        <div v-else class="notify-form">
          <input v-model="testEmail.to" placeholder="收件邮箱" type="email" />
          <input v-model="testEmail.subject" placeholder="邮件主题" />
          <textarea v-model="testEmail.body" placeholder="邮件正文" rows="3"></textarea>
          <button class="btn-notify" @click="sendTestEmail" :disabled="notifySending">
            {{ notifySending ? '发送中...' : '发送测试邮件' }}
          </button>
          <p v-if="notifyMsg" class="notify-msg" :class="{err: notifyErr}">{{ notifyMsg }}</p>
        </div>
      </div>
    </section>
  `,
  setup() {
    const plans = ref([]);
    const currentSub = ref(null);
    const orders = ref([]);
    const selectedPlanCode = ref("yearly_standard");
    const payChannel = ref("ALIPAY");
    const paying = ref(false);
    const polling = ref(false);
    const payModal = reactive({
      show: false,
      orderNo: "",
      channel: "",
      amount: 0,
      planName: "",
      payUrl: "",
      qrCode: "",
      mock: false,
    });
    let pollTimer = null;

    const paidPlans = computed(() => plans.value.filter(p => p.price_cents > 0));
    const selectedPlanPrice = computed(() => {
      const p = plans.value.find(p => p.code === selectedPlanCode.value);
      return p ? (p.price_cents / 100).toFixed(0) : "0";
    });

    async function loadPlans() {
      try {
        plans.value = await api("/subscription/plans");
      } catch (e) { console.error("loadPlans:", e); }
    }

    async function loadCurrentSub() {
      try {
        currentSub.value = await api("/subscription/current");
      } catch (e) { console.error("loadCurrentSub:", e); }
    }

    async function loadOrders() {
      try {
        orders.value = await api("/subscription/orders");
      } catch (e) { console.error("loadOrders:", e); }
    }

    async function handleCreateOrder() {
      if (!selectedPlanCode.value) return;
      paying.value = true;
      try {
        const res = await api("/payment/create-order", {
          method: "POST",
          body: JSON.stringify({
            plan_code: selectedPlanCode.value,
            channel: payChannel.value,
          }),
        });
        payModal.show = true;
        payModal.orderNo = res.order_no;
        payModal.channel = res.channel;
        payModal.amount = res.amount_cents;
        payModal.planName = res.plan_name;
        payModal.payUrl = res.pay_url || "";
        payModal.qrCode = res.qr_code || "";
        payModal.mock = res.pay_url?.startsWith("mock://") || res.qr_code?.startsWith("mock://");

        // 开始轮询订单状态
        startPolling(res.order_no);
      } catch (e) {
        alert("创建订单失败: " + e.message);
      } finally {
        paying.value = false;
      }
    }

    function startPolling(orderNo) {
      polling.value = true;
      pollTimer = setInterval(async () => {
        try {
          const status = await api(`/payment/order/${orderNo}`);
          if (status.status === "PAID") {
            stopPolling();
            closePayModal();
            alert("\u2705 订阅成功！");
            await loadCurrentSub();
            await loadOrders();
          }
        } catch (e) { /* ignore */ }
      }, 3000);
    }

    function stopPolling() {
      polling.value = false;
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }

    function closePayModal() {
      stopPolling();
      payModal.show = false;
    }

    async function checkPayResult() {
      if (!payModal.orderNo) return;
      try {
        const status = await api(`/payment/order/${payModal.orderNo}`);
        if (status.status === "PAID") {
          stopPolling();
          closePayModal();
          alert("\u2705 订阅成功！");
          await loadCurrentSub();
          await loadOrders();
        } else {
          alert("支付未完成，请稍后再试");
        }
      } catch (e) {
        alert("查询失败: " + e.message);
      }
    }

    async function mockPay() {
      if (!payModal.orderNo) return;
      try {
        await api(`/payment/mock-pay/${payModal.orderNo}`, { method: "POST" });
        stopPolling();
        closePayModal();
        alert("\u2705 模拟支付成功，订阅已激活！");
        await loadCurrentSub();
        await loadOrders();
      } catch (e) {
        alert("模拟支付失败: " + e.message);
      }
    }

    function formatDate(dt) {
      if (!dt) return "";
      return new Date(dt).toLocaleDateString("zh-CN");
    }

    function orderStatusText(s) {
      const map = { PENDING: "待支付", PAID: "已支付", FAILED: "失败", REFUNDED: "已退款" };
      return map[s] || s;
    }

    onMounted(() => {
      loadPlans();
      loadCurrentSub();
      loadOrders();
    });

    // ========== 通知测试 ==========
    const notifyTab = ref("sms");
    const notifyPhone = ref("");
    const notifySending = ref(false);
    const notifyMsg = ref("");
    const notifyErr = ref(false);
    const testEmail = reactive({ to: "", subject: "KidoAI 测试邮件", body: "这是一封来自 KidoAI 的测试邮件。" });

    async function sendTestOtp() {
      if (!/^1[3-9]\d{9}$/.test(notifyPhone.value)) {
        notifyErr.value = true; notifyMsg.value = "请输入正确的手机号"; return;
      }
      notifySending.value = true; notifyMsg.value = ""; notifyErr.value = false;
      try {
        await api("/notify/send-otp", {
          method: "POST",
          body: JSON.stringify({ phone: notifyPhone.value }),
        });
        notifyErr.value = false;
        notifyMsg.value = "✅ 验证码已发送（开发 Mock 模式接受 123456）";
      } catch (e) {
        notifyErr.value = true;
        notifyMsg.value = "发送失败: " + e.message;
      } finally {
        notifySending.value = false;
      }
    }

    async function sendTestEmail() {
      if (!testEmail.to || !testEmail.subject) {
        notifyErr.value = true; notifyMsg.value = "请填写邮箱和主题"; return;
      }
      notifySending.value = true; notifyMsg.value = ""; notifyErr.value = false;
      try {
        await api("/notify/send-test-email", {
          method: "POST",
          body: JSON.stringify({ email: testEmail.to, subject: testEmail.subject, body: testEmail.body }),
        });
        notifyErr.value = false;
        notifyMsg.value = "✅ 邮件发送成功";
      } catch (e) {
        notifyErr.value = true;
        notifyMsg.value = "发送失败: " + e.message;
      } finally {
        notifySending.value = false;
      }
    }

    function handleLogout() {
      if (confirm("确定要退出登录吗？")) {
        clearAuth();
        switchTab("growth");
      }
    }

    return {
      plans, paidPlans, currentSub, orders,
      selectedPlanCode, selectedPlanPrice,
      payChannel, paying, polling, payModal,
      handleCreateOrder, closePayModal, checkPayResult, mockPay,
      formatDate, orderStatusText, switchTab,
      notifyTab, notifyPhone, notifySending, notifyMsg, notifyErr, testEmail,
      sendTestOtp, sendTestEmail, handleLogout,
    };
  },
});

// ========== 挂载 ==========
app.mount("#app");
