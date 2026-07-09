# KidoAI 家长端 AI 育儿助手

基于 **Gradio + LlamaIndex + LangSmith** 构建的家长端 AI 育儿问答服务。

## 技术栈

| 层 | 技术 | 用途 |
|---|---|---|
| Web UI | Gradio ChatInterface | 自带聊天界面 + 流式打字效果 |
| RAG 框架 | LlamaIndex VectorStoreIndex | 向量索引与检索 |
| LLM | 通义千问 qwen-plus（DashScope） | 对话生成 |
| Embedding | text-embedding-v2（DashScope） | 中文向量编码 |
| 对话引擎 | CondensePlusContextChatEngine | 多轮对话（浓缩历史+上下文检索） |
| 可观测性 | LangSmith | 全链路追踪（检索/LLM调用/Token用量/延迟可视化） |

## 功能

- 家长可提问 3-6 岁儿童的育儿问题（心理、教育、健康、行为）
- 基于内置育儿知识库进行 RAG 检索增强
- 流式输出，实时打字效果
- 多轮对话上下文理解
- 内置示例问题快速体验

## 快速启动

### 1. 环境变量

确保 `.env` 中已配置 DashScope API Key：

```bash
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxx
```

### 2. 本地运行

```bash
cd services/parent-chat
pip install -r requirements.txt
python app.py
```

访问：http://127.0.0.1:7860

### 3. Docker 运行

```bash
docker compose up parent-chat
```

## 知识库

育儿知识库位于 `data/parenting_kb/`，当前包含：

- `儿童心理发展.txt` — 3-6岁儿童心理发展阶段特点与常见问题应对
- `早期教育与亲子互动.txt` — 分年龄段教育重点、亲子互动方法、阅读习惯培养
- `儿童健康与营养.txt` — 营养需求、睡眠管理、常见疾病预防、安全防护

### 扩充知识库

将 `.txt`、`.pdf`、`.docx` 等文档放入 `data/parenting_kb/` 目录，删除 `data/storage/` 后重启服务，系统会自动重建向量索引。

## 架构说明

```
用户提问
  ↓
CondensePlusContextChatEngine
  ├─ Step 1: 浓缩历史 + 新问题 → 独立问题
  ├─ Step 2: 向量检索（top_k=5） → 育儿知识片段
  ├─ Step 3: 系统提示词 + 上下文 + 问题 → qwen-plus LLM
  └─ Step 4: 流式输出 → Gradio 前端（打字机效果）

LangSmith 追踪链路（可选）：
  每一次 embedding 调用 / 向量检索 / LLM 生成
    ↓ 自动上报
  LangSmith 控制台（https://smith.langchain.com）
    ↓ 可视化查看
  完整调用链路 + Token 用量 + 延迟 + 检索质量
```

## LangSmith 追踪配置（可选）

LangSmith 提供全链路可观测性，可以在控制台可视化查看每一次 RAG 调用的：
- 检索的 query 和召回的知识片段
- LLM 的完整 prompt 和 response
- Token 用量和延迟
- 多轮对话的完整链路

### 启用步骤

在项目根目录 `.env` 中配置：

```bash
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_sk_xxxxxxxx
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_PROJECT=kidoai-parent-chat
```

获取 API Key：https://smith.langchain.com/settings

启用后启动服务，日志会显示：
```
LangSmith 追踪已启用：project=kidoai-parent-chat, endpoint=https://api.smith.langchain.com
```

### 不启用时

`LANGCHAIN_TRACING_V2=false`（默认），服务正常运行，不追踪。

## 与主项目的关系

本服务是 KidoAI 项目的独立子服务：
- 不依赖主后端 FastAPI（独立运行在 7860 端口）
- 不修改现有儿童端 RAG（langchain_rag 模块保持不变）
- 复用 .env 中的 DASHSCOPE_API_KEY 和 LangSmith 配置
- 通过 parent-web 导航栏入口跳转访问
