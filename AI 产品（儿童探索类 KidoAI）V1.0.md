#  AI 产品（儿童探索类 KidoAI）V1.0

------

# 一、Monorepo 总体结构

```text
kidoai/
├── apps/
│   ├── child-web/          # 儿童端（Vue3）
│   ├── parent-web/         # 家长端（Vue3）
│   ├── admin-web/          # 管理后台（Vue3）
│
├── services/
│   ├── api-gateway/        # FastAPI网关
│   ├── user-service/       # 用户服务
│   ├── explore-service/    # 探索（识图）服务
│   ├── chat-service/       # AI对话服务
│   ├── growth-service/     # 成长系统
│   ├── task-service/       # 任务系统
│   ├── content-service/    # 内容/知识库
│   ├── ai-service/         # LLM统一接入层
│
├── packages/
│   ├── shared-ui/          # 前端组件库
│   ├── shared-utils/       # 工具函数
│   ├── shared-types/       # TS类型定义
│
├── infra/
│   ├── mysql/
│   ├── redis/
│   ├── nginx/
│   ├── docker/
│   ├── k8s/
│
├── docs/
│   ├── prd/
│   ├── api/
│   ├── architecture/
│   ├── prompt-engineering/
│
├── scripts/
├── tests/
├── docker-compose.yml
└── README.md
```

------

# 二、前端三端结构（Vue3）

------

## 1️⃣ 儿童端（child-web）

```text
child-web/
├── src/
│   ├── assets/
│   ├── components/
│   │   ├── AIChatBox.vue
│   │   ├── ExploreCamera.vue
│   │   ├── GrowthBadge.vue
│   │
│   ├── pages/
│   │   ├── Home.vue
│   │   ├── Explore.vue
│   │   ├── Chat.vue
│   │   ├── Growth.vue
│   │   ├── Task.vue
│   │
│   ├── router/
│   ├── store/
│   ├── api/
│   ├── hooks/
│   ├── utils/
│   ├── styles/
│
├── public/
├── vite.config.ts
└── main.ts
```

👉 特点：

- 强交互
- AI为核心
- 少设置，多引导

------

## 2️⃣ 家长端（小程序）

```text
parent-web/
├── src/
│   ├── pages/
│   │   ├── Dashboard.vue
│   │   ├── Report.vue
│   │   ├── GrowthAnalysis.vue
│   │   ├── BehaviorTrack.vue
│   │   ├── Settings.vue
│   │
│   ├── components/
│   │   ├── GrowthChart.vue
│   │   ├── AIAdviceCard.vue
│   │
│   ├── api/
│   ├── store/
│   ├── router/
│
└── main.ts
```

👉 特点：

- 数据展示为主
- 强分析
- 强报表

------

## 3️⃣ 管理后台（admin-web）

```text
admin-web/
├── src/
│   ├── pages/
│   │   ├── UserManage.vue
│   │   ├── ContentManage.vue
│   │   ├── PromptCenter.vue
│   │   ├── TaskConfig.vue
│   │   ├── AILogMonitor.vue
│   │
│   ├── components/
│   │   ├── PromptEditor.vue
│   │   ├── LogTable.vue
│   │
│   ├── api/
│   ├── store/
│
└── main.ts
```

👉 核心能力：

- 控AI行为
- 控内容
- 看日志
- 改Prompt（非常关键）

------

# 三、后端 FastAPI（核心）

------

## 1️⃣ API Gateway（统一入口）

```text
api-gateway/
├── main.py
├── routes/
│   ├── auth.py
│   ├── explore.py
│   ├── chat.py
│   ├── growth.py
│
├── middleware/
│   ├── auth_middleware.py
│   ├── rate_limit.py
│
└── config.py
```

👉 作用：

- 鉴权
- 路由转发
- 限流
- 日志

------

## 2️⃣ user-service

```text
user-service/
├── api/
├── models/
├── schemas/
├── service/
├── repository/
└── main.py
```

功能：

- 登录
- 用户信息
- 家长绑定

------

## 3️⃣ explore-service（核心）

```text
explore-service/
├── api/
│   ├── upload.py
│   ├── vision.py
│
├── service/
│   ├── image_recognition.py
│   ├── ai_explainer.py
│
├── models/
├── schemas/
└── main.py
```

流程：

```text
上传图片
→ OSS
→ Vision模型
→ Prompt增强
→ 儿童化输出
→ 存储记录
```

------

## 4️⃣ chat-service（Agent核心）

```text
chat-service/
├── api/
│   ├── chat.py
│
├── agent/
│   ├── prompt_builder.py
│   ├── memory_manager.py
│   ├── persona_engine.py
│
├── service/
│   ├── llm_service.py
│
└── main.py
```

------

## 5️⃣ growth-service

```text
growth-service/
├── api/
├── service/
│   ├── level_engine.py
│   ├── report_generator.py
│
├── models/
└── main.py
```

------

## 6️⃣ ai-service（统一大模型层）

```text
ai-service/
├── llm/
│   ├── openai.py
│   ├── gemini.py
│   ├── claude.py
│
├── prompt/
│   ├── explore_prompt.py
│   ├── chat_prompt.py
│
├── router/
│   ├── model_router.py
│
└── main.py
```

👉 核心能力：

- 多模型切换
- Prompt统一管理
- 成本控制

------

# 四、数据层设计（MySQL + Redis）

------

## MySQL

```text
user
explore_record
chat_session
chat_message
growth_profile
task
task_record
knowledge_card
prompt_template
```

------

## Redis

用途：

```text
聊天上下文缓存
用户session
图片识别缓存
限流计数
```

------

# 五、AI架构（核心）

------

## 1️⃣ 总体AI链路

```text
用户输入
→ 意图识别
→ Agent调度
→ Memory读取
→ Prompt构建
→ LLM调用
→ 后处理
→ 返回结果
```

------

## 2️⃣ Memory结构

```text
短期记忆（Redis）
长期记忆（MySQL）
语义记忆（可扩展 Milvus）
```

------

## 3️⃣ Prompt体系

```text
基础Prompt
角色Prompt
任务Prompt
成长报告Prompt
安全过滤Prompt
```

------

# 六、部署结构

```text
Frontend (Nginx)
        ↓
API Gateway
        ↓
Microservices (FastAPI)
        ↓
MySQL + Redis
        ↓
AI APIs (GPT/Gemini)
        ↓
OSS
```

------

# 七、项目关键亮点（工程级）

## 1️⃣ 微服务拆分合理

不是随便拆，而是：

- 用户域
- AI域
- 成长域
- 内容域

------

## 2️⃣ AI服务独立化

避免：

> AI代码污染业务代码

------

## 3️⃣ Prompt工程化

支持：

- 动态修改
- 版本控制
- 灰度发布

------

## 4️⃣ Memory系统

实现：

- 短期上下文
- 长期兴趣画像
- 行为学习

------

## 5️⃣ 三端解耦

```text
儿童端（体验）
家长端（价值）
后台（控制）
```

------

