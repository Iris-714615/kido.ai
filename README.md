# KidoAI

儿童探索类 AI 产品，面向 3-12 岁儿童，提供 AI 对话、探索任务、成长报告、绘本生成等能力，同时为家长提供实时监护、订阅、通知、AI 育儿助手等服务。

## 项目架构

```
KidoAI/
├── services/api/          后端服务（FastAPI + SQLAlchemy + LangChain）
│   ├── app/
│   │   ├── api/v1/        REST API 路由（auth/chat/explore/memory/notify/payment/subscription/parent/coze）
│   │   ├── core/           配置、安全、启动引导
│   │   ├── db/             数据库会话与基类
│   │   ├── models.py       数据模型（User/ChildProfile/ChatSession/Memory/Subscription/NotificationLog...）
│   │   ├── schemas.py      Pydantic 请求/响应 schema
│   │   ├── services/       业务服务层
│   │   │   ├── ai.py / coze_adapter.py / langchain.py   AI 抽象层
│   │   │   ├── chat.py / explore.py / memory.py         对话/探索/记忆
│   │   │   ├── notification.py / otp.py                 通知与短信验证码
│   │   │   ├── payment.py / report.py                    支付与成长报告
│   │   │   └── langchain_rag/                           RAG 知识库子系统
│   │   ├── multi_agent/    多 Agent 协作系统（LangGraph）
│   │   │   ├── agents.py / pipeline.py / router.py      Agent 编排
│   │   │   ├── image_generator.py                        绘本图片生成 Agent
│   │   │   ├── prompts.py / schemas.py / persistence.py
│   │   ├── templates/      邮件/报告模板
│   │   ├── dependencies.py 依赖注入（鉴权、DB Session）
│   │   └── main.py         应用入口（lifespan、定时任务、路由注册）
│   └── requirements.txt
├── services/parent-chat/   家长端 AI 育儿助手（Gradio + LlamaIndex + LangSmith）
│   ├── app.py              Gradio ChatInterface + RAG 引擎
│   └── requirements.txt
├── services/Neo4j/         知识图谱服务（Neo4j + Gradio）
│   ├── crud_service.py     KidoGraphService 服务层：CRUD + 复杂查询 + 图算法
│   ├── gradio_app.py       Gradio Web UI（7 个 Tab，含图可视化）
│   ├── init_db.py           数据库初始化脚本（50 节点 + 20 关系）
│   └── test_e2e.py          端到端联调测试
├── apps/                   前端应用
│   ├── parent-web/         家长端（Vue3 + Vite）
│   │   ├── main.js         单文件应用（登录/成长/定位/视频/订阅/通知测试）
│   │   ├── styles.css      暖橙移动主题样式
│   │   ├── vite.config.js  Vite 配置（含 /api 代理）
│   │   └── index.html
│   └── child-web/          儿童端（Vue3 CDN 单文件）
│       ├── main.js         应用 + ChatAPI/ExploreAPI/MemoryAPI/StoryAPI
│       ├── styles.css      卡通风格主题
│       └── Dockerfile
├── docs/                   产品/技术文档
│   ├── NOTIFICATION_SYSTEM_SPEC.md   通知系统规格
│   ├── story_safety_agent_spec.md    绘本安全 Agent 规格
│   ├── 支付订阅板块.md
│   ├── RAG_INTERVIEW_GUIDE.md        RAG 面试指南
│   ├── archive/            归档的历史 Demo / 旧版本文件
│   └── ...
├── docker-compose.yml
├── .env.example
└── test_notification_system.py     通知系统端到端测试
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| 数据库 | MySQL（生产）/ SQLite（开发默认） |
| ORM | SQLAlchemy 2.0 |
| 鉴权 | JWT（PyJWT） |
| 缓存/限流 | Redis（OTP/短信防刷） |
| AI 对话 | OpenAI / Coze / Fallback 多 Provider |
| RAG 知识库 | LangChain 1.0 + Chroma + BM25 混合检索 |
| 家长端 RAG | LlamaIndex + DashScope（通义千问） |
| 知识图谱 | Neo4j + Cypher + networkx 可视化 |
| 多 Agent | LangGraph（story/image_generator/ router） |
| 可观测性 | LangSmith（家长端 AI 对话全链路追踪） |
| 通知渠道 | 阿里云短信（wanx-v1）/ Resend / SMTP / Fallback Mock |
| 支付 | 支付宝 / 微信 / 模拟支付 |
| 定时任务 | APScheduler（每日 20:00 成长报告） |
| 前端 | Vue 3（CDN 单文件）+ Vite（parent-web） |
| Web UI | Gradio（parent-chat + Neo4j 图谱智能体） |

## 快速启动

### 环境要求

- Python ≥ 3.12
- Node.js ≥ 18（parent-web 开发用）
- Redis（可选，未配置时 OTP 走内存模式）
- MySQL（可选，未配置时默认使用 SQLite）
- Neo4j（可选，未配置时图谱服务走离线模式）

### 1. 后端

```bash
cd services/api
pip install -r requirements.txt

# 默认 SQLite + Fallback AI + Fallback 通知，零配置即可启动
python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

### 2. 家长端（Vite 开发服务器）

```bash
cd apps/parent-web
npm install
npx vite --host 127.0.0.1 --port 5174
```

Vite 会通过 `vite.config.js` 的 proxy 将 `/api` 请求代理到 `http://127.0.0.1:8001`，前端访问 `http://127.0.0.1:5174/`。

### 3. 儿童端（静态服务器）

```bash
cd apps/child-web
python -m http.server 5173
```

访问 `http://127.0.0.1:5173/`。

### 4. 家长端 AI 育儿助手（Gradio）

```bash
cd services/parent-chat
pip install -r requirements.txt
python app.py
```

访问 `http://127.0.0.1:7860/`，基于 LlamaIndex RAG + 通义千问的育儿问答服务。

### 5. 知识图谱智能体（Neo4j + Gradio）

```bash
# 先启动 Neo4j（Docker）
docker compose up -d neo4j

# 初始化图谱数据
cd services/Neo4j
pip install -r requirements.txt
python init_db.py

# 启动 Gradio 界面
python gradio_app.py
```

访问 `http://127.0.0.1:7861/`（端口可通过 `.env` 中 `NEO4J_GRADIO_PORT` 修改）。

### 6. 容器化（全部服务）

```bash
docker compose up --build
```

## 默认访问地址

| 服务 | 地址 | 说明 |
|------|------|------|
| 后端 API | http://127.0.0.1:8001 | FastAPI |
| API 文档（Swagger） | http://127.0.0.1:8001/docs | 自动生成 |
| 家长端 | http://127.0.0.1:5174 | Vue3 + Vite |
| 儿童端 | http://127.0.0.1:5173 | Vue3 CDN |
| 家长端 AI 助手 | http://127.0.0.1:7860 | Gradio + LlamaIndex |
| 知识图谱智能体 | http://127.0.0.1:7861 | Gradio + Neo4j |
| Neo4j Browser | http://localhost:7474 | 图数据库管理界面 |

## 演示账号

| 端 | 账号 | 密码 | 角色 |
|----|------|------|------|
| 儿童端 | `demo_child` | `demo123` | CHILD |
| 家长端 | `parent_demo` | `demo123456` | PARENT |

家长端启动时会自动注册/登录 demo 家长账号（`autoLoginIfNeed`）；如需查看登录页，可在"订阅"页底部点击"退出登录"。

## 核心功能模块

### 后端 API

| 路由前缀 | 功能 |
|---------|------|
| `/api/v1/auth` | 注册、登录、JWT 签发 |
| `/api/v1/chat` | 儿童对话（流式 SSE） |
| `/api/v1/explore` | 探索任务 |
| `/api/v1/memory` | 记忆事件与摘要 |
| `/api/v1/parent` | 家长查看孩子报告、AI 分析、记忆摘要 |
| `/api/v1/subscription` | 套餐列表、当前订阅状态 |
| `/api/v1/payment` | 创建订单、支付回调、订单查询、模拟支付 |
| `/api/v1/notify` | 发送/校验 OTP、测试邮件 |
| `/api/v1/stories` | 多 Agent 生成绘本 + 图片生成 + 打包 |

### 通知系统

- **OTP 验证码**：5 分钟 TTL，Mock 模式接受 `123456`
- **短信防刷**：每分钟 1 条、每小时 5 条（Redis pipeline 计数器）
- **支付通知**：`asyncio.create_task` 异步发送，不阻塞回调响应
- **成长报告**：APScheduler 每日 20:00 自动生成并推送
- **审计日志**：所有通知记录到 `notification_logs` 表
- **Fallback 模式**：未配置 SMS/Email 凭证时自动走 Mock，零配置即可联调

### 多 Agent 绘本系统

基于 LangGraph 的多 Agent 协作：
- **story Router**：分发创作任务
- **story Agents**：生成中文绘本文本（3-6 岁适宜）
- **image_generator**：调用阿里云通义万相 `wanx-v1` 模型串行生成 1280×720 图片
- **SSE 流式输出**：start → image_done ×N → complete
- 产物保存到 `data/uploads/stories/{story_id}/images/act_{N}.png` + `manifest.json`

### 家长端 AI 育儿助手

基于 **Gradio + LlamaIndex + LangSmith** 的育儿问答服务：
- **RAG 检索增强**：内置育儿知识库，LlamaIndex VectorStoreIndex 向量检索
- **多轮对话**：CondensePlusContextChatEngine 支持上下文浓缩与连续对话
- **流式输出**：实时打字效果
- **可观测性**：LangSmith 全链路追踪（检索/LLM 调用/Token 用量/延迟可视化）
- 详见 [services/parent-chat/README.md](services/parent-chat/README.md)

### 知识图谱模块（Neo4j）

基于 **Neo4j + Gradio** 的儿童长期语义记忆中枢：
- **5 类实体**：Child、Interest、Object、Knowledge、Event
- **5 类关系**：LIKES、DISCOVERED、TRIGGERED、LEADS_TO、ASKED_ABOUT
- **完整 CRUD**：实体管理 + 关系管理，MERGE 幂等 + DETACH DELETE 防悬挂边
- **复杂查询**：精准/模糊/区间/IN/OR 五种组合，参数化防注入
- **图算法**：最短路径、邻居遍历、兴趣推荐
- **图可视化**：networkx + matplotlib 绘制，按标签着色，支持中文
- **Gradio 7 Tab**：智能体查询、图谱可视化、图谱统计、实体 CRUD、关系 CRUD、多条件查询、关系链路
- 详见 [services/Neo4j/README.md](services/Neo4j/README.md)

## 环境变量

参考 `.env.example`，关键配置：

```bash
# 数据库（未配置时默认 SQLite data/kidoai.db）
DATABASE_URL=mysql+pymysql://user:pass@host:3306/kidoai
REDIS_URL=redis://host:6379/0

# AI Provider：fallback / openai / coze
AI_PROVIDER=fallback
OPENAI_API_KEY=...
COZE_API_KEY=...

# 通义千问（家长端 AI 助手 + 绘本图片生成）
DASHSCOPE_API_KEY=...

# 通知 Provider：未配置时走 Fallback Mock
SMS_PROVIDER=fallback      # fallback / aliyun
EMAIL_PROVIDER=fallback    # fallback / resend / smtp

# 支付（可选）
ALIPAY_APP_ID=...
WECHAT_MCH_ID=...

# Neo4j 知识图谱
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=123456abc
NEO4J_GRADIO_PORT=7861

# LangSmith 可观测性（家长端 AI 助手）
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=...
LANGCHAIN_PROJECT=kidoai-parent-chat
```

## 测试

### 通知系统端到端测试

```bash
python test_notification_system.py
```

覆盖：登录 → OTP 发送/校验（Mock）→ 错误码拒绝 → 手机号格式校验 → 测试邮件 → 未认证拦截。

### 知识图谱端到端测试

```bash
cd services/Neo4j
python test_e2e.py
```

覆盖：统计/精准/模糊/区间/IN/OR/邻居/路径/推荐/CRUD/意图识别（15 项测试）。

## 项目文档

- [通知系统规格](docs/NOTIFICATION_SYSTEM_SPEC.md)
- [绘本安全 Agent 规格](docs/story_safety_agent_spec.md)
- [Coze 集成指南](docs/COZE_INTEGRATION_GUIDE.md)
- [支付订阅板块](docs/支付订阅板块.md)
- [前端 Coze 集成](docs/FRONTEND_COZE_INTEGRATION.md)
- [RAG 面试指南](docs/RAG_INTERVIEW_GUIDE.md)
- [家长端 AI 助手文档](services/parent-chat/README.md)
- [知识图谱模块文档](services/Neo4j/README.md)
