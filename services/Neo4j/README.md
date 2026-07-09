# KidoAI 知识图谱「儿童兴趣 × 多模态知识链条」模块

> 基于 Neo4j + Gradio 的儿童长期语义记忆中枢，将零散的探索事件串联成可解释、可持续的成长关系网。

## 一、需求背景

在传统的儿童启蒙与探索类产品中，儿童的互动通常是单次、零散且无连续性的。例如孩子今天拍了一张"霸王龙"的照片，AI 给出了解释，但明天孩子再问"剑龙"时，系统无法感知这两次探索之间的关联。

- **儿童端痛点**：对话缺乏个性化，AI 记不住我的喜好，每次聊天都像和陌生人说话
- **家长端痛点**：无法系统地了解孩子的兴趣脉络。家长看到的只是一堆零散的聊天记录

本模块通过图数据库 Neo4j 将零散的探索事件串联成可解释、可持续的成长关系网，作为 KidoAI 的**长期语义记忆中枢**。

### 核心业务场景

1. **拍照探索引入知识链条**：孩子拍摄"蜻蜓"图片 → 系统识别出 `Object(蜻蜓)` → 图谱自动关联 `Knowledge(昆虫复眼)` 引导探索 → 产生 `Event(探索事件)`
2. **长期兴趣渐进式沉淀**：孩子连续 3 次提问或拍摄与"恐龙"相关 → 系统在图谱中强化 `Child -[LIKES {weight: 3}]-> Interest(恐龙)`，自动更新兴趣标签
3. **基于图谱记忆的个性化对话 (Graph RAG)**：下次对话开始时，`chat-service` 查询图谱中该儿童喜爱的 `Interest` 和探索过的 `Knowledge`，拼装入 Prompt，AI 主动说："宝贝，上次我们认识了蜻蜓的复眼，今天你想不想了解蝴蝶的翅膀？"

---

## 二、图谱 Schema 设计

### 实体节点 (Nodes)

| Label | 核心属性 | 说明 |
| :--- | :--- | :--- |
| **Child** | `id`, `name`, `age`, `gender`, `created_at` | 儿童档案基本信息 |
| **Interest** | `id`, `name`, `category`, `weight`, `updated_at` | 兴趣主题（恐龙、宇宙、昆虫） |
| **Object** | `id`, `name`, `source_image`, `confidence`, `detected_at` | 识别出的物理实体 |
| **Knowledge** | `id`, `name`, `summary`, `difficulty_level`, `category` | 结构化知识点 |
| **Event** | `id`, `title`, `type`, `happened_at`, `source_id` | 探索事件记录 |

### 关系 (Relationships)

| Type | 起点节点 → 终点节点 | 关系属性 | 业务语义 |
| :--- | :--- | :--- | :--- |
| **LIKES** | `Child` → `Interest` | `weight`, `first_time`, `last_active` | 儿童偏好某种兴趣主题 |
| **DISCOVERED** | `Child` → `Object` | `count`, `first_discovered_at` | 儿童发现/探索了某个物体 |
| **TRIGGERED** | `Event` → `Object` | `method` (camera/voice/sensor) | 探索事件触发了对该物体的识别 |
| **LEADS_TO** | `Object` → `Knowledge` | `relevance` (置信度) | 识别出的物体引申、链接到知识点 |
| **ASKED_ABOUT** | `Child` → `Knowledge` | `count`, `last_asked_at` | 儿童针对某个知识点进行过提问 |

### 初始化数据

`init_db.py` 一键注入 5 类各 10 个节点（共 50 个）和 20 组核心关系：

```
节点分布: Child=10, Interest=10, Object=10, Knowledge=10, Event=10
关系分布: LIKES=5, DISCOVERED=5, TRIGGERED=5, LEADS_TO=5
```

---

## 三、文件结构

```
services/Neo4j/
├── README.md           本文档
├── crud_service.py     KidoGraphService 服务层：CRUD + 复杂查询 + 图算法 + 可视化数据
├── gradio_app.py       Gradio Web UI（7 个 Tab，含图可视化）
├── init_db.py           数据库初始化脚本（50 节点 + 20 关系）
├── test_e2e.py          端到端联调测试（15 个测试用例）
├── requirements.txt     Python 依赖
└── Dockerfile           容器化构建文件
```

---

## 四、KidoGraphService 服务接口

### 1. 实体管理 (Entity CRUD)

| 方法 | 说明 | 关键 Cypher |
| :--- | :--- | :--- |
| `create_entity(label, props)` | 创建实体（MERGE 幂等，按 id 去重） | `MERGE (n:Label {id: $id}) SET n += $props` |
| `get_entity(label, id)` | 按 id 精准查询 | `MATCH (n:Label {id: $eid}) RETURN n` |
| `update_entity(label, id, props)` | 合并更新属性 | `MATCH ... SET n.k = $k ...` |
| `delete_entity(label, id)` | 安全删除（DETACH DELETE）| `MATCH ... DETACH DELETE n` |

### 2. 关系管理 (Relationship CRUD)

| 方法 | 说明 | 关键 Cypher |
| :--- | :--- | :--- |
| `create_relationship(s, e, type, props)` | 建立/合并关系（MERGE 幂等） | `MERGE (a)-[r:TYPE]->(b) SET r.k = $k` |
| `get_relationship(s, e, type)` | 查询两实体间关系 | `MATCH (a)-[r:TYPE]->(b) RETURN r` |
| `update_relationship(s, e, type, props)` | 更新关系属性 | `MATCH ... SET r.k = $k` |
| `delete_relationship(s, e, type)` | 删除关系（保留节点） | `MATCH ... DELETE r` |

### 3. 复杂多条件查询

`advanced_search()` 支持以下查询条件，所有 WHERE 条件之间是 AND 关系，OR_conds 内部是 OR 关系：

| 查询类型 | 参数示例 | Cypher 片段 |
| :--- | :--- | :--- |
| 精准查询 | `precise_conds={"name": "张小明"}` | `n.name = $p_0` |
| 模糊查询 | `fuzzy_conds={"name": "恐龙"}` | `n.name CONTAINS $f_0` |
| 区间查询 | `range_conds={"age": (4, 7)}` | `n.age >= $r_low AND n.age <= $r_high` |
| IN 查询 | `in_conds={"category": ["古生物", "天文学"]}` | `n.category IN $in_0` |
| OR 查询 | `or_conds={"name": "霸王龙", "category": "昆虫学"}` | `(n.name=$or_0 OR n.category=$or_1)` |

所有 Cypher 参数化查询，杜绝注入风险；Label/RelType 做白名单正则校验。

### 4. 图谱统计与关系链路检索

| 方法 | 说明 |
| :--- | :--- |
| `count_nodes(label=None)` | 节点总数统计（可按标签过滤） |
| `get_graph_stats()` | 图谱整体统计：各标签节点数、各关系类型数、总数 |
| `get_neighbors(label, id, direction, rel_type, limit)` | 邻居查询（出/入/双向） |
| `find_paths(s_label, s_id, e_label, e_id, max_depth)` | 最短路径查询（最多 max_depth 跳） |
| `recommend_interests(child_id, top_k)` | 兴趣推荐：基于已喜欢兴趣的同类别推荐 |
| `get_graph_data(limit)` | 获取全量图谱数据（nodes + edges），用于可视化 |
| `verify_connectivity()` | 测试连接是否正常 |

---

## 五、Gradio 智能体界面

`gradio_app.py` 提供一个多 Tab 的 Web 交互界面，访问地址通过 `.env` 中 `NEO4J_GRADIO_PORT` 配置（默认 7861）。

### Tab 设计

| Tab | 功能 | 关键交互 |
| :--- | :--- | :--- |
| 🤖 智能体查询 | 自然语言查询图谱 | 输入"张小明喜欢什么" → 意图识别 → 图谱检索 → 渲染 |
| 🕸️ 图谱可视化 | 知识图谱网络图可视化 | networkx + matplotlib 绘制，按标签着色，显示关系标签 |
| 📊 图谱统计 | 节点/关系统计仪表盘 | 一键刷新，展示各标签分布 |
| 📝 实体 CRUD | 实体创建/更新/删除 | 表单输入 → JSON 渲染结果 |
| 🔗 关系 CRUD | 关系创建/删除 | 起/止节点 + 关系类型 + 属性 JSON |
| 🔎 多条件查询 | 精准/模糊/区间/IN/OR 组合查询 | JSON 形式输入条件 |
| 🛤️ 关系链路 | 邻居/最短路径/兴趣推荐 | 可视化路径展示 |

### 智能体意图识别

系统通过精心编写的系统级 Prompt 约束 + 规则解析器，对用户的输入进行意图分类：

- **可处理意图**：查询实体、查询关系、图谱探索（如"我想看看张小明有什么兴趣"）
- **无法处理意图**：非图谱查询范围（如"帮我写首诗"、"明天天气怎么样"）→ 严格拦截并返回无法处理声明

### 图可视化功能

基于 `networkx` + `matplotlib` 绘制知识图谱网络图：

- **按标签着色**：Child=绿色、Interest=橙色、Object=蓝色、Knowledge=紫色、Event=红色
- **关系标签**：连线中点显示关系类型（如 LIKES、LEADS_TO）
- **有向箭头**：使用 `arrowstyle="-|>"` 表示关系方向
- **中文支持**：配置 SimHei / Microsoft YaHei 字体，解决中文乱码

---

## 六、快速启动

### 1. 启动 Neo4j 数据库

**方式一：Docker Compose（推荐）**

```bash
# 在项目根目录
docker compose up -d neo4j
# 等待健康检查通过（约 30 秒）
docker compose logs -f neo4j
```

**方式二：使用已有的 Neo4j 容器**

```bash
docker run -d --name kidoai-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/123456abc \
  -v neo4j_data:/data \
  neo4j:2026.05-community
```

访问 Neo4j Browser：http://localhost:7474 (用户名 neo4j / 密码 123456abc)

### 2. 安装依赖并初始化数据库

```bash
cd services/Neo4j
pip install -r requirements.txt

# 初始化图谱：注入 50 个节点 + 20 组关系
python init_db.py
# 输出：🎉 KidoAI 知识图谱初始化成功！
```

### 3. 启动 Gradio 界面

```bash
python gradio_app.py
# 输出：Running on local URL:  http://127.0.0.1:7861
```

浏览器访问 `http://127.0.0.1:7861`（或 `.env` 中 `NEO4J_GRADIO_PORT` 指定的端口）。

### 4. 运行端到端测试

```bash
python test_e2e.py
# 输出 15 项测试结果，覆盖统计/精准/模糊/区间/IN/OR/邻居/路径/推荐/CRUD/意图识别
```

---

## 七、环境变量配置

在项目根目录 `.env` 中配置（参考 `.env.example`）：

```bash
# Neo4j 连接
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=123456abc

# Gradio 服务监听
NEO4J_GRADIO_HOST=127.0.0.1
NEO4J_GRADIO_PORT=7861
```

> **Windows 注意**：`NEO4J_GRADIO_HOST` 必须设为 `127.0.0.1`（不能用 `0.0.0.0`）。
> Gradio 启动时会通过 HEAD 请求验证本地可访问性，若系统设置了 HTTP_PROXY/HTTPS_PROXY 会导致代理走外网失败。
> `gradio_app.py` 已自动清除代理环境变量并设置 `NO_PROXY=127.0.0.1,localhost` 兜底。

---

## 八、Docker 部署

### 单独构建 Gradio 服务

```bash
cd services/Neo4j
docker build -t kidoai/neo4j-gradio .
docker run -d -p 7861:7861 \
  -e NEO4J_URI=bolt://host.docker.internal:7687 \
  -e NEO4J_USER=neo4j \
  -e NEO4J_PASSWORD=123456abc \
  kidoai/neo4j-gradio
```

### 与项目其他服务一起启动

```bash
# 项目根目录
docker compose up -d neo4j neo4j-gradio
```

`docker-compose.yml` 中已配置：

- `neo4j` 服务：暴露 7474/7687 端口，挂载 `neo4j_data` 持久化卷，健康检查 + APOC 插件
- `neo4j-gradio` 服务：暴露 7861 端口，依赖 neo4j 健康检查通过后启动

---

## 九、技术要点

### 1. 安全性

- 所有 Cypher 查询使用**参数化** (`$param`)，杜绝注入风险
- Label 和关系类型做**白名单正则校验** (`[A-Za-z_][A-Za-z0-9_]*`)，覆盖所有入口（`advanced_search`、`get_neighbors` 等）
- 删除实体使用 `DETACH DELETE` 连带删除关系，避免悬挂边
- 创建使用 `MERGE` 幂等，按 id 去重，重复执行不会产生脏数据

### 2. 容错降级

- Neo4j 连接失败时，Gradio 自动切换到**离线演示模式**，使用模拟数据反馈
- 不影响其他服务运行，方便本地无 Neo4j 环境时调试 UI

### 3. 性能

- 所有查询带 `LIMIT` 上限（默认 50，最大 500），防止超大结果集
- `find_paths` 限制 max_depth ≤ 6 跳，防止图遍历爆炸
- Driver 单例复用，连接池由 neo4j-python-driver 自动管理

### 4. 可视化

- 使用 `networkx` 构建有向图 + `matplotlib` 绘制
- 按节点标签着色（5 种颜色对应 5 类实体）
- 关系标签显示在连线中点，支持中文显示
- 支持自定义返回条数上限

---

## 十、与项目其他模块的集成点

本模块作为 KidoAI 的**长期语义记忆中枢**，未来可与以下模块联动：

| 模块 | 集成方式 |
| :--- | :--- |
| `services/api/app/services/chat.py` | 对话开始前查询图谱，注入儿童兴趣到 Prompt（Graph RAG） |
| `services/api/app/services/explore.py` | 探索事件完成后，写入图谱（Event → Object → Knowledge） |
| `services/api/app/multi_agent/` | 多 Agent 协作时，从图谱检索知识点用于绘本创作 |
| `apps/parent-web/` | 家长端展示孩子的兴趣图谱可视化、知识网络成长轨迹 |
| `services/api/app/services/memory.py` | 记忆摘要时结合图谱兴趣标签，生成更精准的成长报告 |

---

## 十一、面试可讲的亮点

1. **图谱 Schema 设计**：5 类实体 5 类关系，覆盖儿童探索 → 物体识别 → 知识引申 → 兴趣沉淀的完整链路
2. **Cypher 多条件查询**：精准/模糊/区间/IN/OR 五种组合，参数化防注入，Label 白名单校验
3. **图算法应用**：最短路径（`shortestPath`）、邻居遍历、基于类别的兴趣推荐
4. **意图识别智能体**：规则解析 + Prompt 约束，严格拦截非图谱查询
5. **工业级工程实践**：MERGE 幂等、DETACH DELETE 防悬挂边、白名单校验、Driver 单例、离线降级
6. **可视化运营**：Gradio 7 Tab 界面（含图可视化），让产品/运营也能直接操作图谱，无需写 Cypher
7. **中文可视化**：matplotlib 配置 SimHei 字体，networkx 绘制有向图，按标签着色 + 关系标签
