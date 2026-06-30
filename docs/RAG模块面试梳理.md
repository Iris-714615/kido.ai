# RAG 模块面试梳理（详细版）

> 基于 KidoAI 项目 `app/services/langchain_rag/` 真实实现梳理，用于简历与面试回答。
> 项目是面向 6-12 岁儿童的科普问答 AI，核心是 LangChain + RAG + Function Call 落地。

---

## 一、业务场景

### 1.1 具体业务是什么
**儿童科普智能问答系统**（KidoAI）：孩子用自然语言提问，AI 结合知识库回答，并能查询个人探索记录、成长统计、实时天气。

业务细分场景（不能太宽泛）：
| 场景 | 触发方式 | 数据来源 | 实现路径 |
|---|---|---|---|
| 科普知识问答 | "为什么天是蓝的？" | 知识库（百科/文档/蒸馏） | RAG 检索 → LLM 生成 |
| 个人记录查询 | "我上次拍到了什么？" | MySQL 探索记录表 | Function Call → `query_explore_records` 工具 |
| 成长统计查询 | "我探索多少次了？" | MySQL 统计聚合 | Function Call → `query_growth_stats` 工具 |
| 实时天气查询 | "今天北京天气？" | 外部天气 API | Function Call → `query_weather` 工具 |

### 1.2 谁来用
- **终端用户**：6-12 岁儿童（及其家长），通过 Vue 前端 H5/小程序交互
- **维护人员**：后端运维，通过 `/deep/kb/refresh`、`/deep/kb/stats` 管理知识库
- **评估人员**：通过 `/deep/eval/*` 接口做指标评估与问题诊断

### 1.3 大概流程
```
儿童提问（前端 Vue）
   ↓
FastAPI 异步接收（/api/v1/deep/rag_chat）
   ↓
敏感词预检（Aho-Corasick 自动机）
   ↓
RAG 检索：问题向量化 → Chroma 相似度检索 → 阈值过滤 → 敏感词后检
   ↓
Prompt 拼接（知识库 context + 历史 + 年龄适配）
   ↓
LLM 决策：直接答 / 调工具（Function Call，最多 3 轮）
   ↓
答案敏感词打码 → 持久化历史 → 返回前端
```

---

## 二、技术栈与模型选型

### 2.1 技术栈
| 层 | 选型 | 理由 |
|---|---|---|
| 后端框架 | **FastAPI** | 原生 async，高并发性能优于 Flask/Django；自动 OpenAPI 文档 |
| 前端 | **Vue** | 组件化，生态成熟 |
| 对话演示 | **Gradio** | 快速原型演示（评估调试用） |
| LLM 编排 | **LangChain 1.0** | 标准化 Prompt/Chain/Tool/VectorStore 抽象，工程化好 |
| 向量数据库 | **Chroma** | 轻量嵌入式，持久化到本地磁盘，免运维，适合中小知识库 |
| 向量模型 | 阿里灵积 `text-embedding-v2` | 中文效果好，OpenAI 兼容协议 |
| LLM | 通义千问（DashScope）优先，DeepSeek/OpenAI 降级 | 国产合规、中文强、OpenAI 兼容 |
| 敏感词 | **pyahocorasick**（Aho-Corasick 自动机） | O(n) 多模式匹配，比正则快 10x+ |
| 定时任务 | **APScheduler** | 轻量，BackgroundScheduler 不依赖额外服务 |
| 分词检索 | **jieba + rank_bm25** | 中文 BM25 关键词检索，混合检索用 |
| 爬虫 | requests + BeautifulSoup4 + lxml + re | 三解析器可切换 |

### 2.2 模型选型 - 参数量级 - 硬件配置（重要）
> 这是面试高频追问点，务必答清楚"为什么这么选"。

**LLM 选型（通义千问 qwen-turbo / qwen-plus）**：
- **参数量级**：千亿级（云端 API 调用，不本地部署）
- **选型理由**：
  1. **合规性**：国内儿童产品需用国产备案模型
  2. **中文能力**：千亿参数中文语料充足，儿童科普场景语义理解强
  3. **成本**：qwen-turbo 输入 0.3元/百万token，儿童问答单次 < 0.01 元
  4. **无需 GPU**：调 API，省硬件投入
- **硬件配置**：API 模式无需 GPU，后端 2C4G 即可承载

**向量模型选型（灵积 text-embedding-v2）**：
- **参数量级**：未公开，约百亿级（云端 API）
- **维度**：1536 维
- **选型理由**：中文检索效果好；OpenAI 兼容协议，LangChain 直接接；输入限制 2048 token，需控制 chunk_size
- **降级方案**：预留 BGE（本地，约 335M 参数，需 1G 显存）和 m3e（本地，约 100M 参数，CPU 可跑）接口

**rerank 模型（灵积 gte-rerank）**：
- cross-encoder 架构，query+doc 拼接编码，精度高于双塔 embedding
- 降级方案：用 embedding 余弦相似度近似 rerank

**为什么不本地部署大模型？**
- 儿童产品 DAU 中等，API 成本远低于自建 GPU 集群（一张 A100 约 10 万 + 电费）
- 合规与内容安全由云厂商兜底
- 团队无需 ML 运维能力

---

## 三、RAG 完整链路

### 3.1 前期数据处理

#### 3.1.1 获取数据（4 种方式）
项目实现 `loaders/` 4 个加载器，对应 4 种数据源：

| 方式 | 加载器 | 数据特点 | 是否需处理 |
|---|---|---|---|
| ① 业务数据库 | `DBLoader` | MySQL/Redis/ES，结构完整 | **不用处理**，直接转 Document |
| ② 爬虫网络获取 | `CrawlerLoader` | 百度百科，非结构 HTML | **需处理**：xpath/bs4/re 三解析器 |
| ③ 读取文档 | `DocumentLoader` | PDF/Word/Excel/txt | **需处理**：表格/图像/敏感词 |
| ④ 模型蒸馏 | `DistillLoader` | LLM 从长文档生成 Q&A | **需处理**：JSON 解析 + 配对 |

**关键代码路径**：
- DB：`loaders/db_loader.py` → 直接 `SELECT` 转 Document
- 爬虫：`loaders/crawler_loader.py` → `crawl_baidu_baike(keyword)`，支持 `parser="bs4"/"xpath"/"re"`
- 文档：`loaders/document_loader.py` → 按 suffix 分发 PyPDFLoader/Docx2txtLoader/OpenpyxlLoader/TextLoader
- 蒸馏：`loaders/distill_loader.py` → LLM 把长文档拆成 `[{"Q":"...","A":"..."}]` 条目

#### 3.1.2 切割（方法）
`processors/splitter.py` 实现 **3 种切割策略**，按场景选用：

| 策略 | 方法 | 适用 | 实现 |
|---|---|---|---|
| **字符切割**（默认） | `RecursiveCharacterTextSplitter`，分隔符 `["\n\n","\n","。","！","？","；"," ",""]` | 通用文本 | chunk_size=500, overlap=50 |
| **段落标题切割** | 正则识别 `一、`/`第X章`/`## `/`1. ` 标题，按段切，超长段再字符二次切 | 结构化文档（百科/教材） | 保留 `section_title` 元数据 |
| **语义相似度切割** | 按句号切句 → 灵积 embedding → 相邻句余弦相似度 < 0.65 断句 | 长文档无标题场景 | 防止语义跳跃被强行拼到一块 |

**为什么 overlap=50？** 保证切割处上下文不丢失，检索时边界片段仍可被命中。

#### 3.1.3 向量模型与向量化
`core/embeddings.py` 工厂模式，支持 3 种向量模型：

| 模型 | 来源 | 调用方式 | 维度 |
|---|---|---|---|
| **灵积 text-embedding-v2**（默认） | 阿里云 API | OpenAI 兼容 | 1536 |
| BGE | 本地（预留接口） | sentence-transformers | 1024 |
| m3e | 本地（预留接口） | sentence-transformers | 768 |

```python
# core/embeddings.py
class EmbeddingFactory:
    @staticmethod
    def get_embeddings(provider="lingji"):
        if provider == "lingji":
            return OpenAIEmbeddings(model="text-embedding-v2", api_key=..., base_url=...)
        # BGE/m3e 延迟导入，缺失时降级
```

#### 3.1.4 向量数据库（Chroma）
`core/vector_store.py` 封装 Chroma：
- **持久化**：`PersistentClient` 落盘到 `data/chroma_db/`，重启不丢
- **多 collection 隔离**：`science_kb`（科普）/ `explore_distilled`（探索蒸馏）
- **去重**：按 `source_id` 元数据去重，避免重复入库
- **检索**：`similarity_search_with_score`，返回 L2 距离（越小越相似，阈值 2.0）

#### 3.1.5 敏感词过滤（关键）
`processors/sensitive_filter.py` 用 **Aho-Corasick 自动机**（pyahocorasick），O(n) 一次扫描匹配所有敏感词：
- **入库前过滤**：丢弃含敏感词的文档块（`drop=True`）
- **检索前预检**：问题命中敏感词直接拒绝
- **检索后过滤**：剔除含敏感词的召回片段
- **生成后打码**：答案中敏感词替换为 `***`

---

### 3.2 检索

`rag/retriever.py` 实现检索闭环（任务四核心）：

```
获取用户输入
  → 敏感词预检（命中 → blocked=True，直接拒绝）
  → 问题向量化（Chroma 内部用 embedding 函数完成）
  → similarity_search_with_score 检索 top-k（默认 k=5）
  → 结果过滤：
      ① 相似度阈值过滤（L2 距离 < 2.0）
      ② source_id 去重
      ③ 敏感词后检（剔除含敏感词的片段）
  → 返回 context + sources
```

**top-k 取多少？** 默认 k=5，权衡召回率与上下文长度（千问单次输入限制）。
**为什么二次过滤？** 入库时已过滤，但爬虫/蒸馏动态数据可能引入新敏感词，检索后必须再检一次。

---

### 3.3 评估优化（核心模块）

项目 `evaluation/` 子包实现完整评估优化体系，分三层：

#### 3.3.1 评估指标（`evaluation/metrics.py`）

| 指标 | 公式 | 含义 |
|---|---|---|
| **上下文召回率** | 有效召回条数 / 总有效条数 | 该召回的相关文档，召回了多少 |
| **上下文精准率** | top-k 有效片段 / 应返回总数 | 召回的里有多少是相关的 |
| **MRR** | 1 / 第一个命中相关项的排名 | 相关项排得靠不靠前 |
| **答案准确率** | 与标注答案的字符相似度（difflib） | 答得对不对 |
| **答案忠实度** | 可被上下文佐证语句数 / 答案总语句数 | **防幻觉**核心指标 |
| **F1** | 2·P·R / (P+R) | 召回与精准的调和平均 |

**实现细节**：
- 相似度阈值默认 0.5（difflib SequenceMatcher）
- 忠实度：答案按句切分，每句与上下文句子比对，超阈值视为"可佐证"
- 批量评估 `evaluate_batch` 输出聚合报告（6 指标平均值）

#### 3.3.2 测试方式（`evaluation/test_runner.py`）

| 测试方式 | 说明 | 适用 |
|---|---|---|
| **人工标注测试** | 从 JSON 数据集加载 `{question, relevant_docs, ground_truth}`，跑 RAG 对比 | 有标注数据 |
| **自动化脚本测试** | 仅问题列表，跑 RAG 验证工程可用性 | 无标注，CI/CD |
| **LLM 评测** | LLM 对答案打分（相关性/准确性/简洁性/儿童友好度，各 0-5） | 无标注答案时 |
| **场景化专项** | 4 类场景（科普/记录/统计/天气）预设用例，校验是否触发期望工具 | 功能回归 |

#### 3.3.3 问题诊断（`evaluation/diagnoser.py`）
根据指标自动分类问题并给优化建议：

**检索问题**：
| 问题 | 判定条件 | 优化建议 |
|---|---|---|
| 漏召回 | recall < 0.6 | 问题改写多路召回；混合检索；降阈值 |
| 无关召回 | precision < 0.5 | rerank 重排；提阈值；语义压缩去噪 |
| 排序靠后 | MRR < 0.5 | rerank 模型；语义相似度替代 L2 |
| 上下文不足 | retrieved_count == 0 | 扩充数据源；检查 embedding 模型 |

**生成问题**：
| 问题 | 判定条件 | 优化建议 |
|---|---|---|
| 幻觉编造 | faithfulness < 0.7 | Prompt 强约束『仅基于知识库回答』；降温度 |
| 总结冗余 | 答案 > 400 字 | Prompt 限字数；语义压缩 |
| 答非所问 | 问题与答案无词交集 | 强化『回答最新问题』约束；查历史污染 |
| 要点遗漏 | 检索OK但答案过短 | few-shot 示例；覆盖要点 |

**工程问题**：
| 问题 | 判定条件 | 优化建议 |
|---|---|---|
| 响应延迟 | latency > 3000ms | 异步多线程；流式输出；缓存；预热 |
| 并发/运行报错 | error 非空 | 重试 + 限流 + 线程隔离 |
| 上下文截断异常 | error 含 length/token | 缩短检索结果；token 计数截断 |

#### 3.3.4 优化策略（`evaluation/optimizer/` 5 个模块）

**① 知识库预处理优化**（`kb_preprocessor.py`）
- 无效版本清除：去空文档、去过短片段（< 10 字）、去重
- 特殊符号/敏感词过滤
- 非格式数据转换：HTML 剥离、表格扁平化、图像占位
- opencv 去噪（可选依赖，缺失降级）

**② 问题改写多路召回**（`query_rewriter.py`）
用户问题不精准 → LLM 改写成 3 个子问题：
1. 同义改写：换说法保留原意
2. 细化改写：补充背景细节
3. 反向改写：从对立面追问

3 个子问题 + 原问题分别检索 → 合并去重 → 供 rerank。

**③ 检索重排 rerank**（`reranker.py`）
- 主路径：灵积 `gte-rerank`（cross-encoder，query+doc 拼接编码）
- 降级：embedding 余弦相似度近似 rerank
- 输出：按分数过滤（阈值 0.3）+ 取 top_n

**④ 语义压缩 + 关键词提取**（`semantic_compressor.py`）
- 语义压缩：LLM 把多文档压成与问题相关的精炼片段（< 200 字）
- 关键词提取：LLM 提 3-8 个关键词，降级用 jieba + TF

**⑤ 多路召回 + 混合检索**（`hybrid_retriever.py`）
- 向量检索（余弦相似度，捕获同义）+ BM25 分词检索（捕获专有名词/数字）
- 两路分数 **min-max 归一化** 到 [0,1]
- 加权融合（默认 向量 0.6 + BM25 0.4）
- 解决纯向量检索对专有名词（如"北极星"）召回弱的问题

---

## 四、知识库维护（任务四）

### 4.1 异步入库管线（`maintenance/ingest.py`）
统一编排：**加载 → 清洗 → 切割 → 敏感词过滤 → 入库**
- 用 `asyncio.to_thread` 包装同步 IO（Chroma/文件/DB），不阻塞 FastAPI 事件循环
- 4 个数据源便捷入口：`ingest_document_files` / `ingest_crawler_keywords` / `ingest_db_data` / `ingest_distill`

### 4.2 定时任务（`maintenance/scheduler.py`）
APScheduler `BackgroundScheduler`：
- **每日 02:00**：增量爬取 10 个科普关键词 → 蒸馏 → 入库
- **每周一 03:00**：全量刷新项目数据库数据入知识库

通过 FastAPI `lifespan` 启停，与应用生命周期绑定。

---

## 五、面试高频问答

### Q1：为什么选 Chroma 不选 Milvus/Pinecone？
- Chroma 嵌入式部署，零运维，适合中小知识库（百万级以下）
- Milvus 适合亿级向量，需独立集群，运维重
- Pinecone 是 SaaS，国内合规问题
- 我们知识库 < 10 万块，Chroma 持久化到磁盘足够

### Q2：敏感词为什么用 Aho-Corasick 不用正则？
- 正则每个敏感词编译一个 pattern，1000 个敏感词 = 1000 次匹配，O(n·m)
- AC 自动机一次扫描匹配所有词，O(n)，1000 词与 1 词速度几乎一样
- 儿童产品敏感词表大，性能差异显著

### Q3：忠实度怎么防幻觉？
- 答案按句切分，每句与上下文做相似度比对
- 超 0.5 视为"可佐证"，否则标记为潜在幻觉
- 忠实度 = 可佐证句数 / 总句数，< 0.7 触发告警
- 优化：Prompt 加"仅基于知识库回答，不知道就说不知道"

### Q4：混合检索为什么需要归一化？
- 向量余弦相似度范围 [0,1]，BM25 分数范围 [0, ∞)
- 不归一化直接相加，BM25 大分数会淹没向量分数
- min-max 归一化到 [0,1] 后再加权融合，两路贡献可控

### Q5：Function Call 工具怎么触发？
- LangChain 1.0 `ChatOpenAI.bind_tools(tools)` 绑定工具 schema
- LLM 根据问题自主决策是否调工具、调哪个
- 工具调用循环最多 3 轮，防死循环
- 例："我上次拍到什么" → LLM 识别需查记录 → 调 `query_explore_records`

### Q6：评估指标里 MRR 为什么用 1/rank？
- MRR 关注"第一个相关结果"的位置
- 排第 1 得 1.0，排第 2 得 0.5，排第 5 得 0.2
- 反映排序质量，相关项越靠前分数越高
- 多样本求平均即 Mean Reciprocal Rank

### Q7：模型蒸馏是什么？为什么用？
- 用大模型（千问）从长文档生成 Q&A 对，作为知识库条目
- 好处：把"长文档检索"转成"问答对检索"，召回更精准
- 例：1 篇 2000 字百科 → 蒸馏成 10 个 Q&A → 每条 100 字，检索命中率提升

### Q8：并发报错怎么处理？
- FastAPI async + `asyncio.to_thread` 隔离同步 IO
- Chroma 写入加锁（`_seed_lock` 双重检查）
- LLM API 调用加重试 + 限流
- 上下文截断：入库前 chunk_size=500 控制，注入前 token 计数兜底

---

## 六、项目结构（一句话总览）

```
langchain_rag/
├── core/           # LLM/向量/Chroma/Prompt（任务一：框架封装）
├── loaders/        # 4 种数据源加载器（任务三：数据获取）
├── processors/     # 切割/敏感词/清洗（任务三：数据处理）
├── tools/          # 3 个 Function Call 工具（任务二：工具）
├── rag/            # 检索器 + 链编排（任务四：检索 + 生成）
├── maintenance/    # 异步入库 + 定时任务（任务四：维护）
├── evaluation/     # 评估指标 + 测试 + 诊断 + 优化策略（任务三：评估优化）
│   └── optimizer/  # 5 个优化策略模块
└── router.py       # FastAPI 路由（8 兼容 + 10 评估优化 = 18 接口）
```

---

## 七、简历 bullet point 模板

- 设计并实现儿童科普 RAG 问答系统，基于 **FastAPI + LangChain 1.0 + Chroma**，支持 4 类业务场景（科普/记录/统计/天气），18 个 API 接口
- 实现 **4 种数据源**异步入库（MySQL/爬虫/文档/模型蒸馏），3 种切割策略（字符/标题/语义相似度），Aho-Corasick 敏感词三重过滤
- 封装 **3 个 Function Call 工具**，LLM 自主决策调用，工具循环最多 3 轮
- 搭建完整 **RAG 评估体系**：6 类指标（召回率/精准率/MRR/准确率/忠实度/F1）+ 4 种测试方式 + 3 类问题诊断
- 落地 **5 种检索优化策略**：知识库预处理、问题改写多路召回、rerank 重排、语义压缩、向量+BM25 混合检索（归一化融合）
- 用 **APScheduler** 实现知识库定时维护（每日爬取 + 每周 DB 刷新），`asyncio.to_thread` 异步不阻塞
- 模型选型：通义千问（千亿参数，API 模式，合规 + 中文强 + 成本低），灵积 text-embedding-v2（1536 维），gte-rerank cross-encoder
