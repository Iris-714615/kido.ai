# Coze 集成指南

## 概述

本文档详细介绍如何将 KidoAI 后端与 Coze Workflow 集成。通过本指南，你将能够：

1. 在 Coze 平台创建三个核心工作流
2. 配置完整的提示词模板和参数
3. 实现前端 -> FastAPI -> Coze Workflow -> MySQL 的完整链路

---

## 架构设计

```
前端请求
    ↓
FastAPI (KidoAI)
    ↓
AI Provider 路由
    ├─ coze: CozeAdapter → Coze Workflow API
    └─ fallback: FallbackProvider (本地逻辑)
    ↓
MySQL 持久化
```

---

## 环境变量配置

在 `.env` 文件中添加以下配置：

```env
# AI Provider: coze 或 fallback
AI_PROVIDER=coze

# Coze API 配置
COZE_API_KEY=your-coze-api-key-here
COZE_BASE_URL=https://api.coze.cn/v1
COZE_TIMEOUT=30

# Coze Workflow ID (创建后填写)
COZE_CHAT_WORKFLOW_ID=kidoai-chat-reply
COZE_EXPLORE_WORKFLOW_ID=kidoai-explore-analysis
COZE_SUMMARY_WORKFLOW_ID=kidoai-memory-summary
```

---

## 工作流配置

### 工作流 1: 聊天回复 (kidoai-chat-reply)

**工作流 ID**: `kidoai-chat-reply`

#### 输入参数

| 参数名 | 类型 | 说明 |
|--------|------|------|
| user_message | string | 用户输入的消息内容 |
| memory_summary | string | 儿童的记忆摘要文本 |
| child_nickname | string | 儿童昵称 |
| child_age | integer | 儿童年龄 (3-12岁) |

#### 输出参数

| 参数名 | 类型 | 说明 |
|--------|------|------|
| reply_message | string | AI 回复消息，适合儿童理解的自然语言 |
| memory_summary | string | 更新后的记忆摘要 |
| suggested_follow_up | string | 建议的后续问题或引导语 |

#### 提示词模板

```
你是一个专为儿童设计的友好探索伙伴。

## 角色设定
- 身份：KidoAI 小助手
- 语气：亲切、耐心、鼓励性
- 语言：简单易懂，适合 {child_age} 岁儿童理解
- 避免：复杂术语、负面词汇、过长句子

## 输入信息
用户消息：{user_message}
记忆摘要：{memory_summary}
儿童昵称：{child_nickname}
儿童年龄：{child_age} 岁

## 任务要求
1. 理解用户消息意图（问题、陈述、请求等）
2. 结合记忆摘要中的信息进行回复
3. 保持积极鼓励的态度
4. 生成一个适合继续探索的引导问题

## 输出格式 (JSON)
{
  "reply_message": "给儿童的回复消息",
  "memory_summary": "更新后的记忆摘要",
  "suggested_follow_up": "后续引导问题"
}

## 示例
输入：
user_message: "为什么天空是蓝色的？"
memory_summary: "小探险家最近探索了天空、太阳和云朵"
child_nickname: "小探险家"
child_age: 6

输出：
{
  "reply_message": "小探险家，这是一个很棒的问题！天空看起来是蓝色的，是因为阳光穿过空气时，蓝色的光更容易被散射开来。就像我们玩的泡泡，也会呈现出漂亮的颜色呢！",
  "memory_summary": "小探险家探索了天空的颜色，问为什么天空是蓝色的",
  "suggested_follow_up": "你想不想知道傍晚的天空为什么会变成红色或橙色呢？"
}
```

---

### 工作流 2: 探索分析 (kidoai-explore-analysis)

**工作流 ID**: `kidoai-explore-analysis`

#### 输入参数

| 参数名 | 类型 | 说明 |
|--------|------|------|
| file_name | string | 上传的文件名 |
| content_type | string | 文件 MIME 类型 |
| file_size | integer | 文件大小（字节） |
| file_url | string | 文件访问 URL（供 Coze 下载分析） |
| child_nickname | string | 儿童昵称 |
| child_age | integer | 儿童年龄 (3-12岁) |

#### 输出参数

| 参数名 | 类型 | 说明 |
|--------|------|------|
| object_name | string | 识别出的物体名称 |
| scientific_fact | string | 适合儿童的科学知识描述 |
| growth_dimension | string | 成长维度 (SCIENCE/LANGUAGE/HISTORY/HABIT) |
| score_delta | integer | 分数增量 (10-50) |

#### 提示词模板

```
你是一个儿童探索分析专家，帮助小朋友发现和理解他们看到的世界。

## 角色设定
- 身份：KidoAI 探索分析师
- 语气：好奇、鼓励、充满发现感
- 语言：简单有趣，适合 {child_age} 岁儿童
- 目标：激发好奇心，传递科学知识

## 输入信息
文件名：{file_name}
文件类型：{content_type}
文件大小：{file_size} 字节
文件URL：{file_url}
儿童昵称：{child_nickname}
儿童年龄：{child_age} 岁

## 成长维度定义
- SCIENCE：自然科学、数学、物理现象
- LANGUAGE：语言文字、阅读表达
- HISTORY：历史文化、传统故事
- HABIT：学习习惯、探索方法

## 任务要求
1. 分析图片内容，识别主要物体
2. 用儿童能理解的语言描述科学事实
3. 确定适合的成长维度
4. 根据内容质量给出分数（10-50分）

## 输出格式 (JSON)
{
  "object_name": "识别的物体名称",
  "scientific_fact": "适合儿童的科学知识描述",
  "growth_dimension": "SCIENCE|LAN
GUAGE|HISTORY|HABIT",
  "score_delta": 分数
}

## 示例
输入：
file_name: cat.jpg
content_type: image/jpeg
file_size: 120000
file_url: https://example.com/media/cat.jpg
child_nickname: 小探险家
child_age: 5

输出：
{
  "object_name": "小猫",
  "scientific_fact": "小探险家，你发现了一只可爱的小猫！猫的眼睛在黑暗中能发光，这是因为它们眼睛里有一层特殊的反光膜，可以帮助它们在夜里看东西哦！",
  "growth_dimension": "SCIENCE",
  "score_delta": 35
}
```

---

### 工作流 3: 记忆总结 (kidoai-memory-summary)

**工作流 ID**: `kidoai-memory-summary`

#### 输入参数

| 参数名 | 类型 | 说明 |
|--------|------|------|
| child_id | integer | 儿童 ID |
| memory_events | array | 记忆事件列表 |
| recent_chats | array | 最近对话列表 |
| explore_records | array | 探索记录列表 |

#### 输出参数

| 参数名 | 类型 | 说明 |
|--------|------|------|
| summary | string | 结构化的记忆总结文本 |

#### 提示词模板

```
你是一位儿童成长记录专家，负责整理和总结儿童的探索历程。

## 角色设定
- 身份：KidoAI 记忆整理师
- 语气：温暖、欣赏、积极
- 语言：适合家长阅读，同时保留儿童视角的纯真

## 输入信息
儿童ID：{child_id}
记忆事件：{memory_events}
最近对话：{recent_chats}
探索记录：{explore_records}

## 任务要求
1. 分析最近的探索和对话数据
2. 提炼出儿童的兴趣点和成长亮点
3. 用温暖亲切的语言总结
4. 突出积极的成长变化

## 输出格式 (JSON)
{
  "summary": "记忆总结文本"
}

## 示例
输入：
child_id: 1
memory_events: [{"event_type": "explore.recorded", "payload": {"object_name": "小猫", "growth_dimension": "SCIENCE"}}]
recent_chats: [{"role": "user", "content": "为什么小猫的眼睛会发光？"}]
explore_records: [{"object_name": "小猫", "scientific_fact": "猫的眼睛有反光膜"}]

输出：
{
  "summary": "小探险家最近对小动物表现出浓厚的兴趣，特别是对小猫进行了深入探索。不仅观察了小猫的外观特征，还提出了关于猫眼发光的有趣问题。这种好奇心和探索精神非常值得鼓励！"
}
```

---

## Coze 工作流调用 KidoAI API

Coze 工作流可以调用以下 KidoAI 接口获取上下文数据：

### 1. 获取记忆摘要

```
GET /api/v1/coze/child/{child_id}/memory-summary?api_key={your-api-key}&limit=10
```

**响应示例**:
```json
{
  "child_id": 1,
  "events": [
    {
      "id": 123,
      "event_type": "explore.recorded",
      "source_type": "explore",
      "source_id": 45,
      "payload": {"object_name": "小猫", "growth_dimension": "SCIENCE"},
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "entities": [
    {
      "id": 67,
      "entity_type": "object",
      "entity_name": "小猫",
      "attributes": {"dimension": "SCIENCE"},
      "created_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

### 2. 获取最近对话

```
GET /api/v1/coze/child/{child_id}/recent-chats?api_key={your-api-key}&limit=20
```

**响应示例**:
```json
{
  "child_id": 1,
  "messages": [
    {"role": "user", "content": "为什么天空是蓝色的？", "created_at": "2024-01-15T10:25:00Z"},
    {"role": "assistant", "content": "这是因为阳光散射的原因...", "created_at": "2024-01-15T10:26:00Z"}
  ]
}
```

### 3. 获取探索记录

```
GET /api/v1/coze/child/{child_id}/explore-records?api_key={your-api-key}&days=7&limit=20
```

**响应示例**:
```json
{
  "child_id": 1,
  "records": [
    {
      "id": 45,
      "object_name": "小猫",
      "scientific_fact": "猫的眼睛有反光膜",
      "growth_dimension": "SCIENCE",
      "score_delta": 35,
      "created_at": "2024-01-15T10:30:00Z"
    }
  ]
}
```

### 4. 获取儿童档案

```
GET /api/v1/coze/child/{child_id}/profile?api_key={your-api-key}
```

**响应示例**:
```json
{
  "id": 1,
  "nickname": "小探险家",
  "age": 6,
  "current_level": 2,
  "token_balance": 150
}
```

---

## 测试验证

### 启动服务

```bash
cd services/api
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 切换到 Coze 模式

```bash
# 设置环境变量
$env:AI_PROVIDER="coze"
$env:COZE_API_KEY="your-coze-key"

# 重启服务
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 测试 API

```bash
# 测试聊天接口
curl -X POST http://localhost:8000/api/v1/chat/sessions \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"content": "你好"}'

# 测试探索接口
curl -X POST http://localhost:8000/api/v1/explore/upload \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@test.jpg"
```

---

## 故障排除

### 常见问题

1. **ModuleNotFoundError: No module named 'pydantic_settings'**
   - 解决方案：`pip install pydantic-settings>=2.3`

2. **Coze API 调用失败**
   - 检查 API Key 是否正确
   - 确认网络连通性
   - 检查工作流 ID 是否匹配

3. **切换 Provider 不生效**
   - 确保环境变量 `AI_PROVIDER` 设置正确
   - 需要重启服务才能生效

---

## 后续扩展

### 建议的下一步

1. **图片预处理服务**：为 Coze 提供图片 URL 时，可以先做一层视觉预处理
2. **多模型路由**：支持根据场景选择不同的模型
3. **Prompt 版本管理**：实现 Prompt 模板的版本化管理
4. **异步任务队列**：将重任务（如图像分析）异步化
5. **家长报告生成**：利用 Coze 生成结构化的家长报告