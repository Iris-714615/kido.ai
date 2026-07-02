# Deep Agents 可复用技术设计与实现规范 (Reusable Technical Document)

本规范旨在沉淀基于 **LangChain** + **LangGraph** + **Deep Agents (Agent Harness)** 的生产级多智能体系统开发模式。通过对虚拟文件系统、上下文工程、任务规划、多子智能体委派、异步长程任务及长期记忆的标准化抽象，确保复杂智能体应用的高可靠性与自主性。

---

## 一、 技术架构与定位

### 1. 智能体开发的三层架构
在 LangChain 生态体系中，生产级 AI Agent 遵循自底向上的三层构建逻辑：
*   **运行时层 (Agent Runtime) — LangGraph**：提供持久化状态管理 (Durable Execution)、图执行引擎、流式输出 (Streaming) 以及人机协同 (Human-in-the-Loop)。
*   **框架层 (Agent Framework) — LangChain**：提供大模型抽象接口、标准工具调用、中间件 (Middleware) 机制与 Agent 循环抽象。
*   **工具套件层 (Agent Harness) — Deep Agents**：开箱即用的工程套件。预置经过验证的复杂操作工具（虚拟文件系统、Todo 规划器、Sub-Agent 委派），从而省去重复造轮子的工作。

---

## 二、 核心技术模块与最佳实现模式

### 1. 上下文工程与虚拟文件系统 (Virtual File System)
**核心思想**：避免将大文本、多文件、长对话直接塞入 prompt，而是提供给 Agent 一个 VFS，使其能够像人类一样“按需读写、搜索定位”。

#### VFS 核心工具
*   `read_file`: 支持分片读取 (`offset`, `limit`)，原生支持多模态格式（图片、视频、音频、PDF、PPTX 等），直接返回多模态数据块。
*   `write_file` / `edit_file`: 用于精细化的文件写入与字符串精确替换。
*   `grep`: 提供 `files_with_matches` (匹配文件名)、`content` (匹配内容及上下文)、`count` (匹配计数) 三种模式，进行高效全文检索。

#### 复合存储路由 (CompositeBackend)
通过 `CompositeBackend`，Agent 可以在同一套工具调用下，根据**路径前缀**自动路由到不同的存储介质：
*   **临时文件** (`/workspace/`, `/notes.txt`等) -> 路由至 `StateBackend` (跟随单次 Graph 会话生命周期，结束后释放)。
*   **持久化文件/记忆** (`/memories/`) -> 路由至 `StoreBackend` (跨对话持久化)。
*   **沙箱执行** -> 路由至 `SandboxBackend` / `LocalShellBackend`。

```python
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

agent = create_deep_agent(
    model="google_genai:gemini-3.5-flash",
    backend=CompositeBackend(
        default=StateBackend(),
        routes={
            "/memories/": StoreBackend(namespace=user_namespace),
            "/skills/": StoreBackend(namespace=assistant_namespace)
        }
    )
)
```

---

### 2. 任务自主规划 (Task Planning & Decomposition)
**核心思想**：面对复杂长程任务，Agent 必须“先思考、再拆解、逐步执行”。

#### `write_todos` 规范
*   **数据结构**：
    ```json
    {
      "subject": "任务标题",
      "description": "详细描述与交付标准",
      "status": "pending" | "in_progress" | "completed"
    }
    ```
*   **TodoListMiddleware (任务列表中间件)**：
    *   该中间件在大模型生成消息前，自动将当前的 Todo 清单渲染注入到系统提示词中。
    *   即使系统在上下文达到 85% 阈值时触发 `SummarizationMiddleware` 进行聊天历史压缩，**Todo 任务列表依然作为强锚点 (Anchor) 被完整保留**，从而防止 Agent 失忆或迷失方向。

---

### 3. 子智能体委派与上下文隔离 (Sub-agents & Context Quarantine)
**核心思想**：在多步骤、多维度任务中，避免主 Agent 陷入工具调用的长上下文泥潭。通过**隔离上下文**将任务分发给专门的子 Agent，主 Agent 只接收精炼的 JSON/文本结果。

#### 同步子智能体模式 (Sync Sub-agents)
*   **默认 General-purpose 智能体**：继承主 Agent 的 `system_prompt`、`tools`、`model` 和 `skills`。主要用于纯粹的上下文隔离（减少主 Agent 会话中的搜索和冗余日志）。
*   **字典定义子智能体**：
    ```python
    researcher_subagent = {
        "name": "researcher",
        "description": "用于深入特定主题研究，多源搜索并汇总摘要。主 Agent 依此说明进行路由委派。",
        "system_prompt": "你是一位专业调研员，请使用 internet_search 并整理在 500 字以内的精炼摘要。",
        "tools": [internet_search],
        "response_format": ResearcherOutputSchema # 可选，强制返回结构化 JSON
    }
    ```

---

### 4. 异步多智能体协同 (Async Sub-agents)
**核心思想**：对于运行数分钟以上的长程任务（如：长文撰写、代码重构），避免主 Agent 阻塞。主 Agent 立即获得任务 ID 并能继续与用户互动，子 Agent 在后台并发运行。

#### 异步控制的“5 把遥控器”
由 `AsyncSubAgentMiddleware` 自动注入到主 Agent 中的 5 大控制工具：
1.  `start_async_task(subagent_name, task_desc)`: 启动后台任务，立即返回 `task_id`。
2.  `check_async_task(task_id)`: 查询运行状态、日志进度或最终结果。
3.  `update_async_task(task_id, new_instruction)`: 运行时动态注入新指令、中途修正方向。
4.  `cancel_async_task(task_id)`: 强行取消执行。
5.  `list_async_tasks()`: 列出当前所有后台任务的全局状态。

---

### 5. 技能包复用机制 (Skills & Progressive Disclosure)
**核心思想**：将领域知识、工作流 SOP、可执行脚本与模板组合打包，遵循开放的 **Agent Skills 规范**，实现跨平台、跨工具的复用。

#### 技能目录结构
```text
skills/my-skill/
├── SKILL.md         # 必填。YAML frontmatter（元数据 + 触发描述） + Markdown 剧本指令
├── scripts/         # 可选。辅助可执行脚本 (Python/Bash)
├── references/      # 可选。详细的专业文档/参考资料
└── assets/          # 可选。报告/配置模板
```

#### 渐进式披露机制 (Progressive Disclosure)
为防止在启动时加载过多 Skill 导致 Prompt 溢出，采用三级加载：
1.  **Level 1 (Metadata)**: 启动时仅读取所有 `SKILL.md` 的 `name` 与 `description`。
2.  **Level 2 (Instructions)**: 仅当用户 query 与某 Skill 的 `description` 匹配并激活时，才完整加载该 `SKILL.md` 的正文指令。
3.  **Level 3 (Resources)**: 当指令明确要求读取、或 Agent 发现需要时，才按需调取 `scripts/`、`references/` 文件夹中的大文件。

---

### 6. 长期记忆工程 (Long-Term Memory Engine)
**核心思想**：利用 `StoreBackend` 实现跨 Thread（跨会话）的持久化数据沉淀。

#### 记忆作用域 (Memory Scopes)
1.  **用户级记忆 (User-scoped)**: Namespace 为 `(user_id,)`，存储用户的个性化偏好、项目背景配置等。启动时通过 `memory=["/memories/preferences.md"]` 自动载入。
2.  **智能体级记忆 (Agent-scoped)**: Namespace 为 `(assistant_id,)`，存储 Agent 自我改进日志 (Self-Improvement)。随着对话增多，Agent 将运行中的反馈更新至 `/memories/AGENTS.md`，实现自我进化。
3.  **组织级记忆 (Organization-scoped)**: Namespace 为 `(org_id,)`，存储企业级合规政策、标准 SOP（通常为**只读**权限）。

#### 后台异步整合 (Background Consolidation)
为避免在对话主路线上进行大篇幅的记忆抽取和合并（增加用户等待延迟），采用后台整合模式：
*   用户与主 Agent 进行实时流畅对话。
*   配置一个 Cron Job（如每 6 小时触发），由独立的 **Consolidation Agent** 扫描该时段内的所有会话历史，提炼事实，静默合并写入 `StoreBackend`。

---

## 三、 LangChain & LangGraph 深度融合规范

1.  **中间件拦截模式**：熟练运用 `@before_model` 和 `@after_model` 装饰器，在不破坏大模型通用推理链的前提下，插入中间件逻辑（如输入消息裁剪 `trim_messages`，输出流式解析，令牌计数，或安全防护拦截）。
2.  **ToolRuntime 自定义状态管理**：
    *   工具函数中隐式声明 `runtime: ToolRuntime` 变量。
    *   读状态：`runtime.state`。
    *   写状态：返回 `Command(update={...})` 动态写回 `AgentState`，不通过大模型中间生成，保障确定性状态修改。
3.  **Durable Session (持久化会话断点恢复)**：
    *   生产环境中统一配置 `PostgresSaver` 作为 Checkpointer，确保进程中断后，多 Agent 的任务可以从精准的 Node 断点恢复执行。
