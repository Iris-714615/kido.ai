# KidoAI 开发文档（评审草案）

## 1. 项目定位

KidoAI 是一个面向儿童探索场景的 AI 产品。核心目标不是单纯做聊天或识图，而是把“探索行为”变成可持续的成长记录、知识反馈和家长可见的陪伴闭环。

产品面向三类角色：

- 儿童端：拍照、提问、互动探索
- 家长端：查看成长轨迹、使用报告、管理权限
- 管理端：管理内容、提示词、任务和日志

## 2. 设计原则

- 儿童安全优先，输出必须可控、可解释、可追踪
- AI 能力独立封装，避免业务代码与模型调用耦合
- 所有核心 AI 输出尽量结构化，优先 JSON Schema / Pydantic
- 高并发场景优先异步化，重任务走消息队列和任务系统
- Prompt、模型路由、记忆层都要可版本化

## 3. 推荐目录结构

```text
kidoai/
├─ apps/
│  ├─ child-web/
│  ├─ parent-web/
│  └─ admin-web/
├─ services/
│  ├─ api-gateway/
│  ├─ user-service/
│  ├─ explore-service/
│  ├─ chat-service/
│  ├─ growth-service/
│  ├─ task-service/
│  ├─ content-service/
│  └─ ai-service/
├─ packages/
│  ├─ shared-ui/
│  ├─ shared-utils/
│  └─ shared-types/
├─ infra/
│  ├─ mysql/
│  ├─ redis/
│  ├─ nginx/
│  ├─ docker/
│  └─ k8s/
├─ docs/
└─ docker-compose.yml
```

## 4. 前端应用

### 4.1 儿童端 `child-web`

职责：

- 拍照探索
- AI 对话
- 成长徽章和任务引导
- 低门槛、强引导交互

### 4.2 家长端 `parent-web`

职责：

- 成长报告
- 行为轨迹查看
- 统计分析
- 家长设置与绑定

### 4.3 管理端 `admin-web`

职责：

- 用户管理
- 内容管理
- Prompt 管理
- 任务配置
- AI 日志监控

## 5. 后端服务拆分

### 5.1 API Gateway

统一承接鉴权、路由转发、限流和日志记录。

### 5.2 user-service

处理登录、用户资料、家长绑定、基础权限。

### 5.3 explore-service

处理图片/视频/流式探索请求，是儿童端的核心入口。

### 5.4 chat-service

负责 AI 对话、角色人格、上下文管理、长期记忆调度和图谱写入。

### 5.5 growth-service

负责成长评分、习惯打卡、报告生成和趋势分析。

### 5.6 task-service

负责任务配置、任务完成记录和异步调度。

### 5.7 content-service

负责知识卡片、内容池、可复用提示词模板。

### 5.8 ai-service

负责统一模型接入、模型路由、Prompt 组装和成本控制。

## 6. 技术栈

- 前端：Vue3 + TypeScript + Vite
- 后端：FastAPI
- ORM：SQLAlchemy 2.0
- 数据库：MySQL 8
- 缓存：Redis
- 图谱：Neo4j / Memgraph / NebulaGraph
- 队列：RabbitMQ / Celery
- 向量库：Milvus
- 文件存储：OSS
- 模型接入：OpenAI / Gemini / Claude

## 7. 核心数据模型

### 7.1 基础表

- `users`：用户主表
- `child_profiles`：儿童档案
- `explore_records`：探索记录
- `growth_timeline`：成长时间线

### 7.2 扩展表

- `chat_session`：会话
- `chat_message`：消息
- `task`：任务定义
- `task_record`：任务完成记录
- `knowledge_card`：知识卡片
- `prompt_template`：Prompt 模板

### 7.3 关键字段建议

- 用户和儿童档案必须一对多或一对一关系明确
- 探索记录必须保存原始模型结果与结构化结果
- 成长时间线必须可按维度检索
- 所有可变 Prompt 必须带版本号和生效状态

### 7.4 图谱记忆实体建议

图谱不替代 MySQL，而是作为长期语义记忆层，保存“关系”和“可解释路径”。

建议节点：

- `Child`：儿童
- `Interest`：兴趣主题
- `Object`：识别到的物体
- `Knowledge`：知识点
- `Event`：探索事件
- `Task`：任务
- `Report`：成长结论

建议关系：

- `DISCOVERED`：发现了什么
- `LIKES`：偏好关系
- `ASKED_ABOUT`：问过什么
- `LEADS_TO`：由此引出什么知识
- `FULFILLED_BY`：任务由哪些行为完成
- `SUPPORTED_BY`：结论由哪些证据支持

建议属性：

- `source_id`：来源记录 ID
- `confidence`：置信度
- `version`：版本号
- `created_at`：写入时间
- `ttl_hint`：是否适合过期

### 7.5 图谱记忆职责边界

- Redis 负责短期会话和临时状态
- MySQL 负责稳定业务事实和持久记录
- 图谱负责关系、路径和可解释记忆
- Milvus 负责语义相似召回
- Chat 服务负责把四层记忆编排起来

## 8. 关键流程

### 8.1 图片探索流程

```text
儿童上传图片
→ OSS 存储
→ API 接入
→ Redis 锁防重
→ VLM / 多模态识别
→ Pydantic 结构化输出
→ 写入 MySQL
→ 触发异步任务
→ 家长端可见成长变化
```

### 8.2 对话流程

```text
用户输入
→ 意图识别
→ 记忆读取
→ Prompt 构建
→ 模型调用
→ 安全过滤
→ 返回结果
```

### 8.3 成长分析流程

```text
探索记录 / 打卡记录
→ 维度归类
→ 分数计算
→ 时间线聚合
→ 报告生成
→ 家长端展示
```

## 9. 关键实现约束

- AI 返回必须尽量只输出结构化数据
- 业务侧不得直接信任模型自由文本
- 并发探索请求要有防重机制
- 解锁逻辑必须与请求身份绑定，避免误删锁
- 重任务必须异步处理，避免阻塞接口

## 10. Redis 约定

建议用途：

- 登录态与会话
- 图片识别缓存
- 并发锁
- 临时上下文
- 限流计数

## 11. 图谱记忆层

图谱记忆层建议作为 KidoAI 的长期语义记忆中枢，核心作用不是“存所有内容”，而是把零散事件串成可解释的关系网。

### 11.1 适合存什么

- 儿童长期兴趣
- 反复出现的物体和主题
- 某次探索引发的知识链路
- 任务完成与行为表现
- 家长关注点与反馈结论

### 11.2 不适合直接存什么

- 高频短对话全文
- 每一轮临时 prompt 拼接内容
- 纯缓存数据
- 一次性无价值噪声事件

### 11.3 推荐技术栈

- 图数据库：Neo4j、Memgraph 或 NebulaGraph
- 查询语言：Cypher 或等价图查询语言
- 写入方式：服务层封装，不直接让业务层拼图查询
- 更新触发：探索结果落库后异步写图
- 召回方式：图遍历 + 向量召回混合

### 11.4 推荐链路

```text
探索记录 / 对话事件
→ 结构化抽取
→ MySQL 持久化
→ 图谱增量写入
→ 语义向量同步
→ 下次对话 / 报告召回
```

### 11.5 落地建议

- 第一版先只做“儿童-物体-知识点-事件”四类核心节点
- 先保证可解释路径，再追求复杂推理
- 关系上尽量写清来源、时间和置信度
- 图谱不要成为第二套主数据库

## 12. Prompt 体系

建议拆分为：

- 基础 Prompt
- 角色 Prompt
- 任务 Prompt
- 成长报告 Prompt
- 安全过滤 Prompt

所有 Prompt 建议支持：

- 版本管理
- 灰度发布
- 回滚
- 审计记录

## 13. 当前版本建议的开发重点

1. 先把 `explore-service` 和 `chat-service` 跑通
2. 先统一 `ai-service` 的模型接入层
3. 先落 `users / child_profiles / explore_records / growth_timeline` 四张核心表
4. 先完成 Redis 锁、异步任务和结构化输出
5. 先把图谱记忆做成最小闭环
6. 再补家长端报表和管理端配置能力

## 14. 待确认事项

- 当前是要按“单体 FastAPI”落地，还是直接按“微服务”拆分
- 儿童端首发是否只做图片探索，还是要同步上聊天
- 模型供应商是否固定 OpenAI，还是保留多模型路由
- 向量库 Milvus 是否第一期必上
- 图谱第一期选 Neo4j、Memgraph 还是 NebulaGraph
- 是否需要把 DDL 直接固化成初始化脚本

## 15. 结论

这份文档适合作为 KidoAI 的开发骨架。它把产品目标、服务拆分、核心数据、AI 流程和落地约束统一到一套结构里，后续可以继续细化成：

- README
- API 文档
- 数据库 DDL
- 服务间时序图
- Prompt 规范
