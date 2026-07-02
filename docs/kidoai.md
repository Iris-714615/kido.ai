langchain+RAG模块

![langchain技术](E:\AICM\P5\KidoAI\langchain技术.png)

```
┌─────────────────────────────────────────────────────────┐
│  家长请求 GET /parent/children/{id}/report              │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│  Step 1: 数据采集层                                      │
│  - 探索记录统计（已有）                                   │
│  - 聊天记录统计（已有）                                   │
│  - Memory 事件 + 实体（已有，需深化）                     │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│  Step 2: Memory 画像构建层（新增）                        │
│  - 兴趣聚类：从 memory_entities 聚类分析                  │
│  - 行为画像：从 memory_events 提取行为模式                │
│  - 记忆摘要：生成结构化孩子画像 JSON                      │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│  Step 3: Prompt 模板层（新增）                            │
│  - 系统提示词：角色设定（儿童教育分析师）                  │
│  - 数据注入模板：统计 + 画像 + 维度分布                   │
│  - 输出要求：分析 + 建议 + 鼓励语                         │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│  Step 4: LLM 调用层（新增）                               │
│  - 调用 AI Provider 生成报告                             │
│  - 异步执行，结果缓存到 DB                               │
└──────────────────────┬──────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────┐
│  Step 5: 响应组装层                                       │
│  - 统计数据 + 画像 + LLM 分析文本 + 维度图表              │
└─────────────────────────────────────────────────────────┘
我先梳理项目结构，理解现有代码上下文，然后给出完整的业务梳理和重构方案。
        
            
toolName: view_folder
            
status: success
          
e:\AICM\P5\KidoAI\services\api
          

        
            
toolName: view_folder
            
status: success
          
e:\AICM\P5\KidoAI\services\api\app
          

        
            
toolName: view_files
            
status: success
          
            
filePath: e:\AICM\P5\KidoAI\services\api\app\core\settings.py
          

        
            
toolName: view_files
            
status: success
          
            
filePath: e:\AICM\P5\KidoAI\services\api\app\models.py
          

        
            
toolName: view_files
            
status: success
          
            
filePath: e:\AICM\P5\KidoAI\services\api\app\dependencies.py
          

        
            
toolName: view_files
            
status: success
          
            
filePath: e:\AICM\P5\KidoAI\services\api\requirements.txt
          

        
            
toolName: view_files
            
status: success
          
            
filePath: e:\AICM\P5\KidoAI\services\api\app\main.py
          

        
            
toolName: view_files
            
status: success
          
            
filePath: e:\AICM\P5\KidoAI\services\api\app\services\report.py
          

        
            
toolName: view_files
            
status: success
          
            
filePath: e:\AICM\P5\KidoAI\services\api\app\services\__init__.py
          

        
            
toolName: view_files
            
status: success
          
            
filePath: e:\AICM\P5\KidoAI\services\api\app\services\ai.py
          

        
            
toolName: view_files
            
status: success
          
            
filePath: e:\AICM\P5\KidoAI\services\api\app\db\session.py
          
我已通读项目代码（`langchain.py`、`settings.py`、`models.py`、`ai.py`、`report.py` 等）和 `kidoai.md` 案例。下面先做完整的业务梳理，再给出详细开发文档与步骤。

## 一、现状分析

**现有 `langchain.py` 的局限：**
- 单文件堆叠，RAG + 路由 + 历史全耦合，无法复用
- 只用 `InMemoryVectorStore`（进程重启即丢失），非 `Chroma`
- 仅 1 个知识源（`十万个为什么.txt`），无多源采集
- 无 Function Call，LLM 只能"背知识库"，不能查孩子动态数据
- 无敏感词过滤、无定时维护、无切割策略可选
- `temperature` 判断用 `"dashscope" in base_url` 字符串包含，脆弱

**案例 `kidoai.md` 可借鉴点：** `Chroma` 持久化 + 元数据去重 + `RecursiveCharacterTextSplitter` + 结构化抽取。

## 二、业务场景梳理（真实细分，不宽泛）

针对 KidoAI「儿童科普探索」业务，设计 4 个真实落地场景：

| 场景 | 触发示例 | 涉及技术 | 数据源 |
|---|---|---|---|
| ① 科普知识问答 | "为什么天是蓝的？" | RAG 检索 + LLM | 文档库(十万个为什么) + 蒸馏知识 |
| ② 个人探索回溯 | "我上次拍了什么？" | Function Call 查 DB | MySQL(explore_records) |
| ③ 成长数据咨询 | "我已经探索多少次了？" | Function Call 查统计 | MySQL(统计聚合) |
| ④ 知识库自动扩充 | 定时抓取科普百科 | 爬虫 + 异步入库 | 网络爬虫(xpath/bs4) |

**核心闭环（任务四）：** 用户输入 → 敏感词预检 → 问题向量化 → Chroma 检索 → 结果过滤(敏感词/相似度阈值) → 拼接 Prompt → LLM(可触发 Function Call) → 敏感词后检 → 持久化历史。

## 三、目录架构（任务一：框架搭建，独立文件夹封装）

```
app/services/langchain_rag/
├── __init__.py                  # 对外统一导出 deep_router
├── core/                        # 核心能力层
│   ├── __init__.py
│   ├── llm.py                   # LLM 工厂(千问/DeepSeek，带 bind_tools)
│   ├── embeddings.py            # 向量化(灵积text-embedding-v2 / BGE / m3e 可切换)
│   ├── vector_store.py          # Chroma 持久化封装(去重/按collection隔离)
│   └── prompts.py               # 儿童科普 Prompt 模板
├── loaders/                     # 任务三：4种数据源
│   ├── __init__.py
│   ├── db_loader.py             # ① 项目数据 MySQL/Redis/ES(结构完整免处理)
│   ├── crawler_loader.py        # ② 爬虫 xpath+bs4+re
│   ├── document_loader.py       # ③ 文档 PDF/Word/Excel/txt(表格/图像)
│   └── distill_loader.py        # ④ 模型蒸馏(大模型→小知识条目)
├── processors/                  # 任务三：数据处理
│   ├── __init__.py
│   ├── splitter.py              # 切割(字符/语义相似度/段落标题 三策略)
│   ├── sensitive_filter.py      # 敏感词过滤(关键, 前后双检)
│   └── cleaner.py               # 表格扁平化/图像OCR占位/清洗
├── tools/                       # 任务二：Function Call 工具(≥2)
│   ├── __init__.py
│   ├── explore_tool.py          # 工具1: 查询孩子探索记录
│   ├── growth_tool.py           # 工具2: 查询成长统计
│   └── weather_tool.py          # 工具3: 天气查询(扩展)
├── rag/                         # RAG 核心
│   ├── __init__.py
│   ├── retriever.py             # 检索器: 向量化→检索→相似度过滤
│   └── chain.py                 # RAG+Tool 链编排
├── maintenance/                 # 任务四：知识库维护
│   ├── __init__.py
│   ├── scheduler.py             # 定时任务(定时增量入库)
│   └── ingest.py                # 异步入库管线
└── router.py                    # FastAPI 路由(保留原接口签名, 向下兼容)
```

## 四、详细开发文档与步骤

### 任务一：框架搭建

**Step 1.1 核心层 `core/llm.py`**
- 抽出 `_resolve_provider()` → `LLMFactory.get_llm(bind_tools=False)`
- 用 `settings.dashscope_api_key` 优先级判定，避免字符串包含判断
- 支持 `bind_tools=[...]` 传参，为 Function Call 铺路

**Step 1.2 向量化 `core/embeddings.py`**
- `EmbeddingFactory.get(provider="lingji|bge|m3e")`
- 默认灵积 `text-embedding-v2`；BGE/m3e 预留接口（本地模型用 `HuggingFaceEmbeddings`）

**Step 1.3 向量库 `core/vector_store.py`**
- `ChromaVectorStore(collection_name, persist_dir)`
- 封装 `add_documents` / `similarity_search_with_score` / 按元数据去重（借鉴案例 `candidate_map` 思路，用 `source_id` 去重）
- 多 collection 隔离：`science_kb` / `explore_distilled` 等

**Step 1.4 Prompt `core/prompts.py`**
- `SCIENCE_RAG_SYSTEM` 儿童科普系统词
- `ChatPromptTemplate` 注入 `{context}`/`{history}`/`{age}`

### 任务二：Function Call 工具

**Step 2.1 工具1 `tools/explore_tool.py`** — 查询孩子探索记录
```python
@tool
def query_explore_records(child_id: int, keyword: str = "") -> str:
    """查询孩子的探索记录(上次拍到了什么)。"""
    # 查 MySQL explore_records，返回结构化文本
```

**Step 2.2 工具2 `tools/growth_tool.py`** — 查询成长统计
```python
@tool
def query_growth_stats(child_id: int) -> str:
    """查询孩子成长数据(探索次数/积分/维度分布)。"""
```

**Step 2.3 工具3 `tools/weather_tool.py`**（扩展）— 天气查询，演示外部 API 工具

**Step 2.4 Agent 编排 `rag/chain.py`** — 用 `llm.bind_tools([...])` + `tool_executor` 循环，让 LLM 自主决定"查库还是查记录"。

### 任务三：RAG 多源 + 数据处理

**Step 3.1 数据源加载 `loaders/`**

| 加载器 | 实现 | 处理 |
|---|---|---|
| `db_loader.py` | SQLAlchemy 查 `explore_records`/`memory_entities`；Redis 缓存读；ES 可选 | 结构完整，免处理，直接转 Document |
| `crawler_loader.py` | `requests`+`lxml.xpath`/`BeautifulSoup`/`re` 抓科普百科 | 三种解析器可切换 |
| `document_loader.py` | `pypdf.PdfReader`/`python-docx`/`openpyxl`/`TextLoader` | 表格扁平化、图像做 OCR 占位标记 |
| `distill_loader.py` | 调 LLM 把长文档蒸馏成「问题→答案」条目 | 增强问答召回 |

**Step 3.2 切割策略 `processors/splitter.py`**（三策略可选）
- `char_split`：`RecursiveCharacterTextSplitter`（字符串）
- `semantic_split`：按相邻块语义相似度断句（灵积 embedding 余弦）
- `title_split`：按段落标题（`一、`/`## `）切分

**Step 3.3 敏感词过滤 `processors/sensitive_filter.py`**（关键）
- 双向检测：**入库前**清洗文档；**出库后**过滤检索结果 + LLM 输出
- 词表文件 `sensitive_words.txt` + Aho-Corasick (`pyahocorasick`) 高效匹配
- 命中则打码 `***` 或丢弃该 chunk

**Step 3.4 向量入库** — 切割→敏感词过滤→embeddings→Chroma `add_documents`

### 任务四：知识库维护 + 检索闭环

**Step 4.1 异步入库 `maintenance/ingest.py`**
- `async def ingest_source(source_type, **kwargs)` 统一入口
- 用 `asyncio.to_thread` 包同步 IO，不阻塞 FastAPI 事件循环

**Step 4.2 定时任务 `maintenance/scheduler.py`**
- 用 `APScheduler`（或 FastAPI `lifespan` 内 `asyncio.create_task`）
- 每日凌晨增量爬取科普百科 → 蒸馏 → 入库
- 提供手动触发接口 `POST /deep/kb/refresh`

**Step 4.3 检索闭环 `rag/retriever.py`**
```
用户输入
  → 敏感词预检(命中直接拒绝/打码)
  → 问题向量化(embeddings)
  → Chroma.similarity_search_with_score(k=5)
  → 结果过滤(score 阈值 + 敏感词后检)
  → 返回 Top-K context
```

**Step 4.4 路由 `router.py`** — 保留原接口签名向下兼容：
- `GET /deep/explore_RAG_chat`（调试）
- `POST /deep/rag_chat`（多轮历史）
- `POST /deep/rag_chat/stream`（流式）
- `GET /deep/rag_history` / `DELETE /deep/rag_history/{id}`
- 新增 `POST /deep/kb/refresh`（手动维护）、`GET /deep/kb/stats`

## 五、依赖新增（requirements.txt）

```
langchain-community>=0.2,<1.0
langchain-chroma>=0.1,<1.0
chromadb>=0.5,<1.0
pypdf>=4.0,<5.0
python-docx>=1.1,<2.0
openpyxl>=3.1,<4.0
beautifulsoup4>=4.12,<5.0
lxml>=5.2,<6.0
pyahocorasick>=2.1,<3.0
apscheduler>=3.10,<4.0
```

## 六、向下兼容策略

- 原 `langchain.py` 改为薄壳：`from app.services.langchain_rag import deep_router`，保证 `main.py` 的 `from app.services.langchain import deep_router` 不变
- 原有 5 个接口签名/响应结构保持不变，前端零改动
- `_vector_store` 全局缓存逻辑迁移到 `ChromaVectorStore` 单例
        
        
from app.services.langchain_rag.processors.sensitive_filter import SensitiveFilter
from app.services.langchain_rag.processors.cleaner import DataCleaner
from app.services.langchain_rag.processors.splitter import TextSplitter
from langchain_core.documents import Document

# 1. 敏感词过滤（关键）
assert SensitiveFilter.contains('这里有暴力和赌博')
assert not SensitiveFilter.contains('今天天气真好')
masked = SensitiveFilter.mask('这里有暴力内容')
assert '***' in masked
print('[1] 敏感词过滤: scan=', SensitiveFilter.scan('杀人和赌博'), 'mask=', masked)

# 2. 清洗
cleaned = DataCleaner.clean_text('你好\u200b世界\t\t连续  空格\n\n\n\n换行')
assert '\u200b' not in cleaned
print('[2] 清洗:', repr(cleaned))

# 3. 表格扁平化
table = DataCleaner.flatten_table([['姓名','年龄'],['小明','6']])
assert '|' in table
print('[3] 表格扁平化:', table)

# 4. 字符切割
splitter = TextSplitter(strategy='char', chunk_size=50, chunk_overlap=10)
docs = [Document(page_content='一、标题\n' + '科普内容。'*20)]
chunks = splitter.split(docs)
assert len(chunks) >= 2
print('[4] 字符切割: 输入1文档 -> 输出', len(chunks), '块, 首块标题meta=', chunks[0].metadata.get('section_title'))

# 5. 标题切割
splitter_t = TextSplitter(strategy='title', chunk_size=200, chunk_overlap=20)
docs = [Document(page_content='一、第一章\n内容A'*5 + '\n二、第二章\n内容B'*5)]
chunks_t = splitter_t.split(docs)
titles = [c.metadata.get('section_title') for c in chunks_t if c.metadata.get('section_title')]
print('[5] 标题切割: 输出', len(chunks_t), '块, 标题=', titles)

# 6. 文档加载(txt)
import tempfile, os
with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as f:
    f.write('这是一个测试文档。\n第二行内容。')
    tmp = f.name
from app.services.langchain_rag.loaders.document_loader import DocumentLoader
loader = DocumentLoader()
loaded = loader.load(tmp)
assert len(loaded) == 1 and '测试文档' in loaded[0].page_content
print('[6] 文档加载txt:', loaded[0].metadata)
os.unlink(tmp)
print('全部组件测试通过')
" undefined
          


## 重构成果总览

### 新建文件夹 `app/services/langchain_rag/`（任务一，18 个文件）

```
langchain_rag/
├── __init__.py              # 对外导出 deep_router
├── core/                    # 任务一：核心能力层
│   ├── llm.py               # LLMFactory（千问/DeepSeek，支持 bind_tools）
│   ├── embeddings.py        # EmbeddingFactory（灵积默认，BGE/m3e 预留）
│   ├── vector_store.py      # ChromaVectorStore（持久化+去重+多collection隔离）
│   └── prompts.py           # 儿童科普 Prompt（RAG / Agent / 简易）
├── loaders/                 # 任务三：4种数据源
│   ├── db_loader.py         # ① MySQL/Redis/ES（结构完整免处理）
│   ├── crawler_loader.py    # ② 爬虫（xpath/bs4/re 三解析器）
│   ├── document_loader.py   # ③ PDF/Word/Excel/txt（表格扁平化+图像占位）
│   └── distill_loader.py    # ④ 模型蒸馏（长文档→Q→A条目）
├── processors/              # 任务三：数据处理
│   ├── splitter.py          # 切割（字符/语义相似度/段落标题）
│   ├── sensitive_filter.py  # 敏感词过滤（Aho-Corasick，前后双检，关键）
│   └── cleaner.py           # 清洗（表格/图像/不可见字符）
├── tools/                   # 任务二：Function Call（3个工具）
│   ├── explore_tool.py      # 查探索记录
│   ├── growth_tool.py       # 查成长统计
│   └── weather_tool.py      # 查天气（外部API）
├── rag/                     # 任务四：RAG核心
│   ├── retriever.py         # 检索闭环：敏感词预检→向量化→检索→结果过滤
│   └── chain.py             # RAG+Tool链编排（工具调用循环）
├── maintenance/             # 任务四：知识库维护
│   ├── ingest.py            # 异步入库管线（asyncio.to_thread）
│   └── scheduler.py         # APScheduler定时任务（每日爬取+每周DB刷新）
└── router.py                # 路由层（兼容原5接口+新增3接口）
```

### 关键设计点

- **检索闭环**（任务四）：用户输入 → 敏感词预检 → Chroma 检索 → 相似度阈值过滤 + 敏感词后检 → 拼接 Prompt → LLM(可触发 Function Call) → 敏感词后检打码 → 持久化
- **Function Call**：LLM 自主决策"查知识库 / 查探索记录 / 查成长数据 / 查天气"，工具调用循环最多 3 轮
- **向量库**：Chroma 持久化（`data/chroma_db/`），按 `source_id` 去重，多 collection 隔离（`science_kb`/`explore_distilled`）
- **向下兼容**：原 `langchain.py` 改为薄壳转发，`main.py` 的 `from app.services.langchain import deep_router` 不变，原 5 个接口签名/响应结构不变

### 接口清单（8 个路由）
兼容：`GET /deep/explore_RAG_chat`、`POST /deep/rag_chat`、`POST /deep/rag_chat/stream`、`GET /deep/rag_history`、`DELETE /deep/rag_history/{id}`
新增：`POST /deep/kb/refresh`（手动刷新知识库）、`GET /deep/kb/stats`（库统计）、`POST /deep/agent_chat`（显式 Agent 问答）

### 验证结果
- 全部模块导入通过；3 个工具已注册
- 组件测试：敏感词过滤(scan/mask)、清洗、表格扁平化、字符/标题切割、txt 文档加载 全部通过
- uvicorn 启动成功（lifespan 含 DB 初始化 + KBScheduler 启动），`/healthz` 返回 healthy，鉴权路由正确返回 401

### 依赖
新增安装 `pyahocorasick`、`langchain-chroma`（其余 langchain/chromadb/pypdf/python-docx/openpyxl/bs4/lxml/apscheduler 本地已装），已更新 [requirements.txt](file:///e:/AICM/P5/KidoAI/services/api/requirements.txt)。

### 改动文件
- 新建：`app/services/langchain_rag/` 整个子包（18 文件）
- 修改：[app/services/langchain.py](file:///e:/AICM/P5/KidoAI/services/api/app/services/langchain.py)（薄壳）、[app/main.py](file:///e:/AICM/P5/KidoAI/services/api/app/main.py)（lifespan 启停定时任务）、[requirements.txt](file:///e:/AICM/P5/KidoAI/services/api/requirements.txt)


```

langchain+rag+function call 综合案例

```
tools/chromadb.py 
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import FakeEmbeddings
from settings import settings
from typing import List, Tuple

class ChromaStore:
    def __init__(self):
        self.embedding = FakeEmbeddings(size=1024)
        self.persist_path = settings.CHROMA_PERSIST_PATH
        self.db = None
       

    # (4) 添加简历数据到向量库
    def add_resume_data(self, content: str,collection_name:str):
        """
        texts: 简历文本片段
        metadatas: 结构化信息 {name, phone, education}
        ids: 唯一标识
        """
        # self.db = Chroma(persist_directory=self.persist_path, embedding_function=self.embedding,collection_name=collection_name)
        self.db = Chroma(collection_name=collection_name,
        embedding_function=self.embedding,
        persist_directory=self.persist_path)
        self.db.add_documents(content)
        self.db.persist()
    

    # 根据岗位描述检索匹配简历
    def search_resume_by_job(self, job_query: str, top_k: int = None,collection_name:str = None):
        self.db = Chroma(persist_directory=self.persist_path, embedding_function=self.embedding,collection_name=collection_name)
        docs = self.db.similarity_search(query=job_query, k=top_k or settings.TOP_K_MATCH)
        docs = [(i.page_content) for i in docs]
        return docs


# 全局单例向量库    
chroma_client = ChromaStore()
\ No newline at end of file
 +89 tools/file_parser.py  0 -> 100644
import os
import re
from PyPDF2 import PdfReader
from docx import Document
from pydantic import BaseModel

# 结构化简历返回模型
class ResumeStruct(BaseModel):
    name: str
    phone: str
    education: str
    raw_text: str  # 完整简历文本用于向量化

# 正则匹配手机号、姓名、学历简易规则
PHONE_PATTERN = re.compile(r"1[3-9]\d{9}")
EDUCATION_LIST = ["博士", "硕士", "本科", "大专", "中专", "高中"]

def extract_base_info(text: str) -> dict:
    """从文本提取手机号、学历（简易规则，可替换NLP抽取）"""
    phone_res = PHONE_PATTERN.findall(text)
    phone = phone_res[0] if phone_res else ""

    education = ""
    for edu in EDUCATION_LIST:
        if edu in text:
            education = edu
            break

    # 简易姓名提取：取文本前100字第一行中文（生产环境替换NER模型）
    name = ""
    lines = text.split("\n")
    for line in lines:
        clean_line = line.strip()
        if len(clean_line) > 1 and not any(d in clean_line for d in "0123456789"):
            name = clean_line[:4]
            break
    return {"name": name, "phone": phone, "education": education}

# (1) PDF解析接口
def parse_pdf(file_path: str) -> ResumeStruct:
    reader = PdfReader(file_path)
    full_text = ""
    for page in reader.pages:
        page_text = page.extract_text() or ""
        full_text += page_text + "\n"
    info = extract_base_info(full_text)
    return ResumeStruct(
        name=info["name"],
        phone=info["phone"],
        education=info["education"],
        raw_text=full_text
    )

# (2) Word解析接口
def parse_word(file_path: str) -> ResumeStruct:
    doc = Document(file_path)
    full_text = ""
    for para in doc.paragraphs:
        full_text += para.text + "\n"
    info = extract_base_info(full_text)
    return ResumeStruct(
        name=info["name"],
        phone=info["phone"],
        education=info["education"],
        raw_text=full_text
    )

# (3) 遍历文件夹批量解析所有简历
def scan_resume_folder(folder_path: str) -> list[ResumeStruct]:
    resume_list = []
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        return resume_list
    for filename in os.listdir(folder_path):
        file_full_path = os.path.join(folder_path, filename)
        if os.path.isdir(file_full_path):
            continue
        suffix = filename.lower()
        try:
            if suffix.endswith(".pdf"):
                res = parse_pdf(file_full_path)
                resume_list.append(res)
            elif suffix.endswith(".docx") or suffix.endswith(".doc"):
                res = parse_word(file_full_path)
                resume_list.append(res)
        except Exception as e:
            print(f"解析文件失败 {filename}: {str(e)}")
            continue
    return resume_list


from fastapi import APIRouter
from settings import settings
from tools.file_parser import scan_resume_folder
import json
from langchain_core.documents import Document
from tools.chromadb import chroma_client
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool


hr_router = APIRouter()
@hr_router.get("/chat")
def get_data():
    path  = settings.RESUME_FOLDER
    resume_list = scan_resume_folder(path)
    datalist = []
    for i in resume_list:
      dict = {"name":i.name,"phone":i.phone,"education":i.education,'raw_text':i.raw_text}
      datalist.append(Document(page_content=json.dumps(dict,ensure_ascii=False)))
    chroma_client.add_resume_data(datalist,collection_name="resume")
    
    return {"message": "ok"}

#查询学历工具
@tool
def query_education(education: str):
    """
    查询学历
    Args:
        education (str): 学历编号
    Returns:
        str: 学历信息
    """
   
    return education+"是本科 HR 职位学历要求"

#查询地图的工具
@tool
def query_map(map: str):
    """
    查询地图
    Args:
        map (str): 起始地址
    Returns:    
        str: 地图信息
    """
    return map+"是地铁五号线"

messages = [{"role": "system", "content": "你是HR，请回答问题"}]
@hr_router.get("/hrchat")
def ask_chat(ask: str):
    global messages
    messages.append({"role": "user", "content": ask})
    #     获取用户输入信息，第一次调用模型。

# 判断是否使用工具，如果使用工具，调用工具，把工具加入到messages中 role=tool

# 如果不走工具，查询向量数据库，获取信息,prompt提示词调用模型回答

# 加多轮对话 messeges存入redis
    llm = ChatOpenAI(model_name="deepseek-chat", temperature=0.7,api_key=settings.DEEPSEEK_API_KEY,base_url=settings.DEEPSEEK_BASE_URL)
    llm_tool = llm.bind_tools([query_education,query_map])
    prompt = ChatPromptTemplate.from_messages([
        ("system","你是一个专业的HR，工作有三个,一个是负责查学历,如果用户查学历调用query_education工具,一个是负责查地图,如果用户查地图,调用query_map工具,一个是负责筛选和面试HR岗位的候选人，如果是筛选候选人，后面会走知识库查询，你直接返回结果，不要让用户再提供学历呀等其他信息"),
        ("human","{input}")
    ])
    chain = prompt | llm_tool
    result = chain.invoke({"input":ask})
    
    #判断是否使用工具，如果使用工具，调用工具，把工具加入到messages中 role=tool
    print(result)
    if result.tool_calls:
        messages.append(result)
        for tool in result.tool_calls:
            name = tool["name"]
            args = tool["args"]
            if name == "query_education":
                content = query_education.invoke(args)
            elif name == "query_map":
                content = query_map.invoke(args)
            messages.append({"role": "tool", "content": content,"name":name,"tool_call_id":tool["id"]})
            mesresult =llm_tool.invoke(messages)
            return {"code":200,"msg":mesresult.content}
    print("##############")

    data  = chroma_client.search_resume_by_job(job_query=ask,top_k=3,collection_name="resume")
    prompt = ChatPromptTemplate.from_messages([
        ("system","你是一个专业的HR，负责筛选和面试HR岗位的候选人,筛选的信息从这个内容中获取{context},返回格式为json,包含姓名，手机号，邮件，学历，技术栈，符合原因.直接根据用户的要求从内容中筛选，不要再询问学历，年龄等其他问题，直接回答"),    
        ("human","{input}")
    ])
    chain = prompt | llm
    result = chain.invoke({"input":ask,"context":data})
    messages.append(result)
    return {"code":200,"msg":result.content}

```



```
import re
import glob
import os
from typing import Dict, Optional, List
from collections import defaultdict
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import FakeEmbeddings

# PDF解析
from pypdf import PdfReader
# Word解析
from docx import Document as DocxDocument

# ====================== 配置常量 ======================
VECTOR_SIZE = 384
CHROMA_PERSIST_DIR = "./resume_chroma_db"
COLLECTION_NAME = "hrtest1_resume_collection"
TEXT_SPLIT_CHUNK_SIZE = 500
TEXT_SPLIT_CHUNK_OVERLAP = 100

# 初始化Fake Embedding
embeddings = FakeEmbeddings(size=VECTOR_SIZE)

# ====================== 工具类1：PDF简历读取工具 ======================
class PdfResumeLoader:
    """读取PDF简历文件，提取纯文本"""
    @staticmethod
    def load(file_path: str) -> str:
        full_text = ""
        reader = PdfReader(file_path)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                full_text += page_text + "\n"
        return full_text.strip()

# ====================== 工具类2：Word简历读取工具 ======================
class WordResumeLoader:
    """读取docx Word简历文件，提取纯文本"""
    @staticmethod
    def load(file_path: str) -> str:
        full_text = ""
        doc = DocxDocument(file_path)
        # 读取段落
        for para in doc.paragraphs:
            if para.text.strip():
                full_text += para.text + "\n"
        # 读取表格内容
        for table in doc.tables:
            for row in table.rows:
                row_text = ""
                for cell in row.cells:
                    row_text += cell.text.strip() + " "
                full_text += row_text + "\n"
        return full_text.strip()

# ====================== 简历信息抽取核心函数（大幅优化姓名识别） ======================
def extract_resume_info(resume_text: str) -> Dict[str, Optional[str]]:
    info = {
        "name": None,
        "phone": None,
        "email": None,
        "education": None,
        "major": None,
        "tech_stack": None
    }

    # 1. 手机号正则匹配
    phone_pattern = re.compile(r"1[3-9]\d{9}")
    phone_match = phone_pattern.search(resume_text)
    if phone_match:
        info["phone"] = phone_match.group()

    # 2. 邮箱正则匹配
    email_pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    email_match = email_pattern.search(resume_text)
    if email_match:
        info["email"] = email_match.group()

    # 3. 学历匹配规则
    education_keywords = ["博士", "硕士", "本科", "大专", "专科", "高中", "中专"]
    edu_result = []
    for edu in education_keywords:
        if edu in resume_text:
            edu_result.append(edu)
    if edu_result:
        info["education"] = "/".join(sorted(list(set(edu_result))))

    # 4. 姓名多层级提取（重点优化，杜绝开发工误识别）
    # 优先级1：匹配 姓名：XXX / 姓名:XXX
    name_prefix_pattern = re.compile(r"姓名[:：]\s*([\u4e00-\u9fa5]{2,4})")
    name_prefix_match = name_prefix_pattern.search(resume_text)
    if name_prefix_match:
        info["name"] = name_prefix_match.group(1)
    else:
        # 优先级2：匹配个人简历上方常见人名区域，前200字
        name_text = resume_text[:200]
        chinese_name_pattern = re.compile(r"[\u4e00-\u9fa5]{2,4}")
        name_candidates = chinese_name_pattern.findall(name_text)
        # 黑名单：极易误匹配的词汇
        filter_words = [
            "简历", "个人", "电话", "邮箱", "学历", "专业", "求职", "意向",
            "开发工", "工程师", "管理员", "技术员", "架构师", "程序员",
            "实习生", "负责人", "项目经理", "产品经理", "测试工程师"
        ]
        valid_names = [n for n in name_candidates if n not in filter_words]
        if valid_names:
            info["name"] = valid_names[0]

    # 5. 专业提取
    major_keywords = [
        "计算机科学与技术", "软件工程", "人工智能", "大数据", "网络工程",
        "电子信息", "自动化", "机械设计", "会计学", "市场营销"
    ]
    major_res = []
    for m in major_keywords:
        if m in resume_text:
            major_res.append(m)
    if major_res:
        info["major"] = "/".join(list(set(major_res)))

    # 6. 技术栈提取
    tech_keywords = [
        "Python", "Java", "Go", "C++", "JavaScript", "Vue", "React",
        "Django", "FastAPI", "SpringBoot", "MySQL", "Redis", "MongoDB",
        "Docker", "K8s", "LangChain", "Chroma", "大模型", "LLM"
    ]
    tech_list = []
    for tech in tech_keywords:
        if tech in resume_text:
            tech_list.append(tech)
    if tech_list:
        info["tech_stack"] = ",".join(list(set(tech_list)))

    return info

# ====================== Chroma向量库操作封装（修复同候选人分裂问题） ======================
class ResumeChromaStore:
    def __init__(self):
        self.vector_store = Chroma(
            persist_directory=CHROMA_PERSIST_DIR,
            embedding_function=embeddings,
            collection_name=COLLECTION_NAME
        )
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=TEXT_SPLIT_CHUNK_SIZE,
            chunk_overlap=TEXT_SPLIT_CHUNK_OVERLAP
        )

    def save_resume_to_chroma(self, resume_raw_text: str, resume_struct_info: Dict, file_unique_id: str):
        chunks = self.text_splitter.split_text(resume_raw_text)
        docs = []
        for chunk in chunks:
            doc = Document(
                page_content=chunk,
                metadata={
                    "file_id": file_unique_id,
                    "name": resume_struct_info["name"],
                    "phone": resume_struct_info["phone"],
                    "email": resume_struct_info["email"],
                    "education": resume_struct_info["education"],
                    "major": resume_struct_info["major"],
                    "tech_stack": resume_struct_info["tech_stack"]
                }
            )
            docs.append(doc)
        self.vector_store.add_documents(docs)
        self.vector_store.persist()
        print(f"✅ 简历 {resume_struct_info['name']} 已存入Chroma，分块数量：{len(docs)}")

    def match_job_position(self, job_desc: str, top_k: int = 10) -> List[Dict]:
        raw_result = self.vector_store.similarity_search_with_score(job_desc, k=top_k)
        # 以手机号为唯一key，同一个手机号=同一个候选人
        candidate_map = defaultdict(lambda: {
            "min_score": float("inf"),
            "best_meta": None,
            "best_text": "",
            "correct_name": None
        })

        for doc, score in raw_result:
            phone = doc.metadata.get("phone", "unknown")
            item = candidate_map[phone]
            # 更新最小距离（最优匹配片段）
            if score < item["min_score"]:
                item["min_score"] = score
                item["best_meta"] = doc.metadata
                item["best_text"] = doc.page_content
            # 优先保存非“开发工”的正确姓名
            current_name = doc.metadata.get("name")
            if current_name and current_name != "开发工" and item["correct_name"] is None:
                item["correct_name"] = current_name

        # 整理输出列表，替换错误姓名为正确人名
        output_list = []
        for phone, data in candidate_map.items():
            meta = data["best_meta"]
            # 覆盖元数据里错误的name
            if data["correct_name"]:
                meta["name"] = data["correct_name"]
            output_list.append({
                "score": data["min_score"],
                "meta": meta,
                "text": data["best_text"]
            })
        # 按距离升序（越小越匹配）
        output_list.sort(key=lambda x: x["score"])
        return output_list

# ====================== 统一简历入口处理函数 ======================
def process_resume_file(file_path: str) -> tuple[Dict, str]:
    if file_path.lower().endswith(".pdf"):
        resume_text = PdfResumeLoader.load(file_path)
    elif file_path.lower().endswith(".docx"):
        resume_text = WordResumeLoader.load(file_path)
    else:
        raise ValueError("仅支持 .pdf 和 .docx 格式简历文件")

    struct_info = extract_resume_info(resume_text)
    return struct_info, resume_text


def test_job_match():
    chroma_store = ResumeChromaStore()
    doc_folder = "D:/p4/boss_project/doc/"

    pdf_files = glob.glob(f"{doc_folder}*.pdf")
    docx_files = glob.glob(f"{doc_folder}*.docx")
    all_resume_files = pdf_files + docx_files

    print(f"=== 找到 {len(all_resume_files)} 份简历文件 ===")

    for resume_path in all_resume_files:
        print(f"\n=== 处理简历: {resume_path} ===")
        try:
            resume_info, full_text = process_resume_file(resume_path)
            print("=== 抽取简历结构化信息 ===")
            for k, v in resume_info.items():
                print(f"{k}: {v}")
            chroma_store.save_resume_to_chroma(full_text, resume_info, file_unique_id=resume_path)
        except Exception as e:
            print(f"❌ 处理简历失败: {resume_path}, 错误: {str(e)}")

    print(f"\n=== 所有简历处理完成，共处理 {len(all_resume_files)} 份简历 ===")

    job_jd = """
    Python后端开发工程师
    要求：本科及以上学历，计算机相关专业
    熟练使用Python、FastAPI、Redis、MySQL，了解LangChain、向量数据库
    """
    print("\n=== 岗位匹配简历结果（按手机号去重，统一正确姓名） ===")
    match_results = chroma_store.match_job_position(job_jd, top_k=10)
    show_top = 3
    for idx, item in enumerate(match_results[:show_top], 1):
        score = item["score"]
        meta = item["meta"]
        text = item["text"]
        print(f"\n【匹配第{idx}条｜相似度距离：{score:.4f}（数值越小匹配度越高）】")
        print(f"候选人完整信息：{meta}")
        print(f"简历片段：{text[:200]}...")


if __name__ == "__main__":
    test_job_match()
```