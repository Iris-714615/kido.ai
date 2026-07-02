# Coze 多智能体协作集成指南

## 架构概览

每个 Coze 工作流由多个智能体节点串联协作，形成完整的 AI 处理流水线。

---

## 工作流 1: 聊天回复 (kidoai-chat-reply)

### 智能体节点流程

```text
开始 → 意图识别 → 记忆检索 → 回复生成 → 安全过滤 → 结束
```

---

### 智能体 1: 意图识别器 (Intent Classifier)

**节点 ID**: `node_001_intent`
**节点类型**: LLM（大语言模型）

**输入参数**:
| 参数名 | 类型 | 必填 | 来源 | 说明 |
|--------|------|------|------|------|
| user_message | string | 是 | 工作流输入 | 用户发送的消息原文 |

**模型配置**:
| 配置项 | 值 | 说明 |
|--------|-----|------|
| 模型 | gpt-4o-mini | 快速轻量模型 |
| Temperature | 0.3 | 低随机性，稳定输出 |
| Max Tokens | 100 | 短输出 |
| Top P | 1.0 | - |

**提示词模板**:
```
你是一个儿童对话意图识别专家。

## 任务
分析用户消息内容，识别其核心意图类型。

## 意图分类标准
- QUESTION：提出疑问句（为什么、怎么、什么、哪里、多少等疑问词结尾）
- STATEMENT：陈述观点或分享（我看到...、我觉得...、今天...等）
- THANKS：表达感谢（谢谢、谢谢你、辛苦啦等）
- CONTINUE：要求继续对话（再说、继续、还有吗、然后呢等）
- GREETING：问候语（你好、早上好、晚安等）
- EXPLORE：探索相关（看、发现、找到、拍照等）
- OTHER：其他无法明确分类

## 输入内容
用户消息：{user_message}

## 输出要求
请以 JSON 格式输出，不要添加任何其他文字：

{
  "intent": "意图类型",
  "confidence": 置信度数值(0.0-1.0),
  "keywords": ["提取的关键词1", "关键词2", "最多3个"]
}

## 示例
输入："为什么天空是蓝色的？"
输出：{"intent": "QUESTION", "confidence": 0.95, "keywords": ["为什么", "天空", "蓝色"]}
```

**输出参数**:
| 参数名 | 类型 | 说明 |
|--------|------|------|
| intent | string | 意图类型（枚举值） |
| confidence | float | 置信度 0.0-1.0 |
| keywords | array[string] | 提取的关键词列表 |

**下游连接**: → 记忆检索器（传递 intent, keywords）

---

### 智能体 2: 记忆检索器 (Memory Retriever)

**节点 ID**: `node_002_memory`
**节点类型**: 代码节点（HTTP 请求）

**输入参数**:
| 参数名 | 类型 | 必填 | 来源 | 说明 |
|--------|------|------|------|------|
| child_id | integer | 是 | 工作流输入 | 儿童用户 ID |
| intent | string | 是 | 意图识别器输出 | 识别出的意图 |
| keywords | array[string] | 是 | 意图识别器输出 | 提取的关键词 |

**外部 API 调用**:

调用 1 - 获取记忆摘要:
```http
GET /api/v1/coze/child/{child_id}/memory-summary?api_key=${COZE_API_KEY}&limit=5
```

调用 2 - 获取最近对话:
```http
GET /api/v1/coze/child/{child_id}/recent-chats?api_key=${COZE_API_KEY}&limit=3
```

**模型配置**:

- 此节点为代码节点，无模型配置

**代码逻辑**:
```python
import requests
import json

def main(child_id: int, intent: str, keywords: list) -> dict:
    api_key = "{{COZE_API_KEY}}"
    base_url = "http://your-kidoai-api.com/api/v1/coze"
    
    # 获取记忆摘要
    memory_resp = requests.get(
        f"{base_url}/child/{child_id}/memory-summary",
        params={"api_key": api_key, "limit": 5},
        timeout=10
    )
    memory_data = memory_resp.json()
    
    # 获取最近对话
    chat_resp = requests.get(
        f"{base_url}/child/{child_id}/recent-chats",
        params={"api_key": api_key, "limit": 3},
        timeout=10
    )
    chat_data = chat_resp.json()
    
    # 根据 intent 和 keywords 过滤相关记忆
    relevant_memories = []
    for event in memory_data.get("events", []):
        payload = event.get("payload", {})
        content = str(payload)
        if any(kw in content for kw in keywords) or intent in content:
            relevant_memories.append({
                "type": event.get("event_type"),
                "content": content[:200],  # 截断长度
                "created_at": event.get("created_at")
            })
    
    # 整合上下文摘要
    context_parts = []
    if relevant_memories:
        context_parts.append("相关记忆：" + "; ".join([m["content"] for m in relevant_memories[:3]]))
    if chat_data.get("messages"):
        recent = chat_data["messages"][-2:]  # 最近2条
        context_parts.append("最近对话：" + "; ".join([m["content"] for m in recent]))
    
    context_summary = " | ".join(context_parts) if context_parts else "暂无相关记忆"
    
    return {
        "relevant_memories": relevant_memories[:5],
        "context_summary": context_summary,
        "memory_events": memory_data.get("events", []),
        "recent_chats": chat_data.get("messages", [])
    }
```

**输出参数**:

| 参数名 | 类型 | 说明 |
|--------|------|------|
| relevant_memories | array[dict] | 过滤后的相关记忆 |
| context_summary | string | 整合后的上下文摘要 |
| memory_events | array[dict] | 原始记忆事件 |
| recent_chats | array[dict] | 原始对话记录 |

**下游连接**: → 回复生成器（传递 context_summary, child_nickname, child_age）

---

### 智能体 3: 回复生成器 (Reply Generator)

**节点 ID**: `node_003_reply`
**节点类型**: LLM（大语言模型）

**输入参数**:
| 参数名 | 类型 | 必填 | 来源 | 说明 |
|--------|------|------|------|------|
| user_message | string | 是 | 工作流输入 | 用户消息原文 |
| child_nickname | string | 是 | 工作流输入 | 儿童昵称 |
| child_age | integer | 是 | 工作流输入 | 儿童年龄 |
| intent | string | 是 | 意图识别器输出 | 对话意图 |
| context_summary | string | 是 | 记忆检索器输出 | 上下文摘要 |

**模型配置**:
| 配置项 | 值 | 说明 |
|--------|-----|------|
| 模型 | gpt-4o | 高质量创意回复 |
| Temperature | 0.7 | 适度创意，保持友好 |
| Max Tokens | 500 | 中等长度回复 |
| Top P | 0.9 | - |

**提示词模板**:
```
你是 KidoAI，一个专为儿童设计的 AI 探索伙伴。

## 角色定位
- 名字：KidoAI
- 身份：{child_nickname} 的探索伙伴
- 目标年龄：{child_age} 岁
- 语言风格：简单、温暖、鼓励、有趣
- 禁用词：复杂术语、负面词汇、恐怖内容

## 对话上下文
用户消息：{user_message}
识别意图：{intent}
相关记忆：{context_summary}

## 回复策略

### 不同意图的回复方式：

**QUESTION（提问）**:
- 先肯定问题的价值："这是一个很棒的问题！"
- 用比喻或生活例子解释
- 保持好奇心："你想不想知道更多？"

**STATEMENT（陈述）**:
- 积极回应："哇，真有意思！"
- 引导深入："你还发现了什么？"
- 连接已有知识："记得你之前..."

**THANKS（感谢）**:
- 温馨回应："不客气呀！"
- 强化关系："我最喜欢和你一起探索了"
- 邀请继续："我们继续吧！"

**CONTINUE（继续）**:
- 承接上文："好的，我们继续..."
- 推进探索："接下来..."
- 保持节奏

**GREETING（问候）**:
- 友好回应："你好呀！"
- 询问状态："今天想探索什么呢？"

**EXPLORE（探索）**:
- 鼓励发现："太棒了！"
- 引导观察："你看到了什么颜色/形状？"
- 科学启蒙："这让我想到..."

**OTHER（其他）**:
- 灵活回应："我听到啦！"
- 尝试理解："你是说...吗？"
- 温和引导

## 回复格式（严格 JSON）
{
  "reply_message": "给 {child_nickname} 的回复内容，2-3句话",
  "memory_summary": "本次对话的核心记忆，一句话",
  "suggested_follow_up": "引导下一步的提问，鼓励继续探索"
}

## 示例
输入：
- user_message: "为什么猫的眼睛会发光？"
- child_nickname: "小探险家"
- child_age: 6
- intent: "QUESTION"
- context_summary: "小探险家之前探索过猫和小猫"

输出：
{
  "reply_message": "小探险家，这是一个很棒的问题！猫的眼睛里有一层特殊的反光膜，像镜子一样，所以能在黑暗中发光。就像你晚上戴的反光手环一样！",
  "memory_summary": "小探险家了解了猫眼发光的秘密，对动物眼睛特别感兴趣",
  "suggested_follow_up": "你想不想知道其他动物的眼睛有什么特别的地方呢？"
}
```

**输出参数**:
| 参数名 | 类型 | 说明 |
|--------|------|------|
| reply_message | string | 给儿童的回复消息 |
| memory_summary | string | 本次对话记忆摘要 |
| suggested_follow_up | string | 后续引导问题 |

**下游连接**: → 安全过滤器（传递 reply_message）

---

### 智能体 4: 安全过滤器 (Safety Guard)

**节点 ID**: `node_004_safety`
**节点类型**: LLM（大语言模型）

**输入参数**:
| 参数名 | 类型 | 必填 | 来源 | 说明 |
|--------|------|------|------|------|
| reply_message | string | 是 | 回复生成器输出 | 待检查的回复 |

**模型配置**:
| 配置项 | 值 | 说明 |
|--------|-----|------|
| 模型 | gpt-4o-mini | 快速检查模型 |
| Temperature | 0.1 | 极低随机性 |
| Max Tokens | 50 | 短输出 |

**提示词模板**:
```
你是一个儿童内容安全审查员。

## 审查标准
检查以下内容是否适合 {child_age} 岁儿童：

### 禁止内容
- 暴力、血腥描述
- 恐怖、惊悚内容
- 不当接触、隐私泄露
- 错误科学知识（如"喝汽油能飞"）
- 危险行为鼓励（如"从高处跳下试试"）
- 成人内容或暗示

### 审查维度
1. 词汇安全性：无敏感词
2. 内容适宜性：符合年龄认知
3. 引导正确性：无危险建议
4. 科学准确性：无错误信息

## 待审查内容
{reply_message}

## 输出格式（严格 JSON）
{
  "is_safe": true/false,
  "violations": ["违规点列表，无违规则为空数组"],
  "suggested_fix": "如有违规，提供修改建议"
}
```

**输出参数**:
| 参数名 | 类型 | 说明 |
|--------|------|------|
| is_safe | boolean | 是否安全 |
| violations | array[string] | 违规点列表 |
| suggested_fix | string | 修改建议 |

**下游连接**: → 结束节点

---

## 工作流 2: 探索分析 (kidoai-explore-analysis)

### 智能体节点流程

```text
开始 → 图像预处理器 → 物体识别器 → 知识生成器 → 分数评估器 → 结束
```

---

### 智能体 1: 图像预处理器 (Image Preprocessor)

**节点 ID**: `node_101_preprocess`
**节点类型**: 代码节点

**输入参数**:
| 参数名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| file_url | string | 工作流输入 | 图片访问 URL |
| content_type | string | 工作流输入 | MIME 类型 |
| child_age | integer | 工作流输入 | 儿童年龄 |

**模型配置**: 无（代码节点）

**处理逻辑**:
```python
import requests
from PIL import Image
import io
import base64

def main(file_url: str, content_type: str, child_age: int) -> dict:
    # 下载图片
    resp = requests.get(file_url, timeout=30)
    img = Image.open(io.BytesIO(resp.content))
    
    # 基础处理
    width, height = img.size
    format_type = img.format or content_type.split("/")[-1].upper()
    
    # 生成图片描述（用于后续模型理解）
    # 这里返回图片基本信息，实际 VLM 在下一节点
    return {
        "width": width,
        "height": height,
        "format": format_type,
        "size_kb": len(resp.content) // 1024,
        "preprocessed": True
    }
```

**输出**: 图片基础信息

---

### 智能体 2: 物体识别器 (Object Recognizer)

**节点 ID**: `node_102_recognize`
**节点类型**: LLM + 视觉输入

**输入参数**:
| 参数名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| file_url | string | 工作流输入 | 图片 URL |
| child_age | integer | 工作流输入 | 儿童年龄 |

**模型配置**:
| 配置项 | 值 |
|--------|-----|
| 模型 | gpt-4o 或 Claude 3.5 Sonnet |
| 视觉输入 | 启用（可接收图片 URL） |
| Temperature | 0.3 |
| Max Tokens | 200 |

**提示词模板**:
```
你是一个儿童探索图像识别专家，专门帮助小朋友认识他们发现的事物。

## 任务
分析儿童上传的图片，识别主要物体，并用适合儿童的语言描述。

## 识别要求
1. 识别图片中的主要物体（动物、植物、物品、场景等）
2. 判断物体的状态（静态/动态、完整/局部等）
3. 识别适合儿童的成长维度

## 成长维度分类
- SCIENCE：自然科学（动物、植物、天气、物理现象等）
- LANGUAGE：语言文字（书本、文字、符号等）
- HISTORY：历史文化（古建筑、传统物品等）
- HABIT：学习习惯（书桌、文具、学习场景等）

## 输入
- 图片：{file_url}
- 儿童年龄：{child_age} 岁

## 输出格式（严格 JSON）
{
  "object_name": "物体名称（2-5字，儿童易懂）",
  "object_description": "物体外观描述（适合儿童理解）",
  "growth_dimension": "SCIENCE|LANGUAGE|HISTORY|HABIT",
  "confidence": 0.0-1.0,
  "detected_objects": ["检测到的物体1", "物体2"]
}
```

**输出参数**:
| 参数名 | 类型 | 说明 |
|--------|------|------|
| object_name | string | 主物体名称 |
| object_description | string | 外观描述 |
| growth_dimension | string | 成长维度 |
| confidence | float | 识别置信度 |
| detected_objects | array[string] | 所有检测到的物体 |

---

### 智能体 3: 知识生成器 (Knowledge Generator)

**节点 ID**: `node_103_knowledge`
**节点类型**: LLM

**输入参数**:
| 参数名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| object_name | string | 物体识别器输出 | 物体名称 |
| object_description | string | 物体识别器输出 | 物体描述 |
| growth_dimension | string | 物体识别器输出 | 成长维度 |
| child_nickname | string | 工作流输入 | 儿童昵称 |
| child_age | integer | 工作流输入 | 儿童年龄 |

**模型配置**:
| 配置项 | 值 |
|--------|-----|
| 模型 | gpt-4o |
| Temperature | 0.8 |
| Max Tokens | 300 |

**提示词模板**:
```
你是一位儿童科学启蒙老师，擅长用有趣的方式讲解知识。

## 任务
为儿童发现的事物生成一个有趣的知识点。

## 输入信息
- 物体名称：{object_name}
- 物体描述：{object_description}
- 成长维度：{growth_dimension}
- 儿童昵称：{child_nickname}
- 儿童年龄：{child_age} 岁

## 生成要求

### SCIENCE 维度示例风格：
"小探险家，你发现的{object_name}有自己的秘密哦！
[具体知识点]
就像[生活化比喻]，是不是很有趣？"

### LANGUAGE 维度示例风格：
"小探险家，你找到的{object_name}和文字有关呢！
[文字相关知识]
下次看到它，试着读一读/写一写吧！"

### HISTORY 维度示例风格：
"小探险家，这个{object_name}有很久远的故事呢！
[历史背景简化版]
古人就是这样[相关活动]的！"

### HABIT 维度示例风格：
"小探险家，你发现{object_name}说明你有很好的观察习惯！
[习惯价值说明]
继续这样认真观察，你会学到更多！"

## 输出格式（严格 JSON）
{
  "scientific_fact": "知识点描述，2-3句话，亲切有趣",
  "fun_fact": "额外趣味小知识（可选）",
  "learning_tip": "给家长的建议（可选）"
}
```

**输出参数**:
| 参数名 | 类型 | 说明 |
|--------|------|------|
| scientific_fact | string | 主知识点 |
| fun_fact | string | 趣味补充 |
| learning_tip | string | 家长建议 |

---

### 智能体 4: 分数评估器 (Score Evaluator)

**节点 ID**: `node_104_score`
**节点类型**: 代码节点

**输入参数**:
| 参数名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| file_size | integer | 工作流输入 | 文件大小（字节） |
| child_age | integer | 工作流输入 | 儿童年龄 |
| growth_dimension | string | 物体识别器输出 | 成长维度 |
| confidence | float | 物体识别器输出 | 识别置信度 |

**模型配置**: 无（代码节点）

**评估逻辑**:
```python
def main(file_size: int, child_age: int, growth_dimension: str, confidence: float) -> dict:
    # 基础分数（根据文件大小）
    base_score = max(10, min(50, 12 + file_size // 60000))
    
    # 年龄调整
    if child_age <= 5:
        base_score = max(10, base_score - 2)
    
    # 置信度调整
    if confidence < 0.5:
        base_score = max(10, base_score - 5)
    
    # 维度加成
    dimension_bonus = {
        "SCIENCE": 0,
        "LANGUAGE": 2,
        "HISTORY": 3,
        "HABIT": 4
    }
    bonus = dimension_bonus.get(growth_dimension, 0)
    
    final_score = min(50, base_score + bonus)
    
    return {
        "score_delta": final_score,
        "score_breakdown": {
            "base": base_score,
            "dimension_bonus": bonus,
            "age_adjusted": child_age <= 5
        }
    }
```

**输出参数**:
| 参数名 | 类型 | 说明 |
|--------|------|------|
| score_delta | integer | 最终分数（10-50） |
| score_breakdown | dict | 分数明细 |

---

## 工作流 3: 记忆总结 (kidoai-memory-summary)

### 智能体节点流程

```text
开始 → 记忆提取器 → 模式分析器 → 报告生成器 → 结束
```

---

### 智能体 1: 记忆提取器 (Memory Extractor)

**节点 ID**: `node_201_extract`
**节点类型**: 代码节点（HTTP 请求）

**输入参数**:
| 参数名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| child_id | integer | 工作流输入 | 儿童 ID |
| days | integer | 工作流输入 | 查询天数 |

**外部 API 调用**:
```http
GET /api/v1/coze/child/{child_id}/memory-summary?api_key=xxx&limit=20
GET /api/v1/coze/child/{child_id}/explore-records?api_key=xxx&days={days}&limit=20
```

**输出**: 结构化的记忆数据

---

### 智能体 2: 模式分析器 (Pattern Analyzer)

**节点 ID**: `node_202_pattern`
**节点类型**: LLM

**输入参数**:
| 参数名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| memory_events | array[dict] | 记忆提取器 | 记忆事件列表 |
| explore_records | array[dict] | 记忆提取器 | 探索记录列表 |
| child_nickname | string | 工作流输入 | 儿童昵称 |
| child_age | integer | 工作流输入 | 儿童年龄 |

**提示词模板**:
```
你是一个儿童成长模式分析专家。

## 任务
分析儿童的探索记录和记忆事件，识别兴趣模式和成长轨迹。

## 分析维度
1. 高频兴趣主题
2. 探索习惯（时间、频率）
3. 学习风格（视觉/听觉/动手）
4. 成长亮点
5. 待发展领域

## 输出格式（严格 JSON）
{
  "top_interests": ["兴趣1", "兴趣2", "兴趣3"],
  "explore_pattern": {
    "total_explores": 数字,
    "preferred_dimensions": ["维度1", "维度2"],
    "avg_score": 平均分
  },
  "strengths": ["优势1", "优势2"],
  "growth_areas": ["待发展1", "待发展2"],
  "milestones": ["里程碑事件1", "事件2"]
}
```

**输出**: 结构化分析报告

---

### 智能体 3: 报告生成器 (Report Generator)

**节点 ID**: `node_203_report`
**节点类型**: LLM

**输入参数**:
| 参数名 | 类型 | 来源 | 说明 |
|--------|------|------|------|
| pattern_analysis | dict | 模式分析器输出 | 模式分析结果 |
| child_nickname | string | 工作流输入 | 儿童昵称 |
| child_age | integer | 工作流输入 | 儿童年龄 |

**提示词模板**:
```
你是一位专业的儿童成长报告撰写专家，为家长撰写温暖、专业、可读性强的成长报告。

## 报告对象
- 儿童昵称：{child_nickname}
- 儿童年龄：{child_age} 岁

## 分析数据
{pattern_analysis}

## 报告结构

### 1. 成长概览（2-3句话）
- 总体评价
- 核心亮点

### 2. 兴趣探索（3-5个主题）
- 每个兴趣的探索次数
- 表现评价

### 3. 成长维度分析
- 优势维度
- 待加强维度

### 4. 里程碑事件
- 重要成长时刻

### 5. 家长建议
- 3条具体可操作的建议

## 输出格式
用温暖亲切的语言撰写，避免使用专业术语，让家长容易理解。
```

**输出**: 完整的成长报告文本

---

## Coze 工作流 JSON 配置

你可以通过 Coze API 直接创建工作流：

```json
{
  "name": "kidoai-chat-reply",
  "nodes": [
    {
      "id": "node_001_intent",
      "type": "llm",
      "position": {"x": 100, "y": 100},
      "config": {
        "model": "gpt-4o-mini",
        "temperature": 0.3,
        "max_tokens": 100,
        "system_prompt": "你是意图识别专家..."
      }
    },
    {
      "id": "node_002_memory", 
      "type": "code",
      "position": {"x": 300, "y": 100},
      "config": {
        "code": "def main(...): ..."
      }
    },
    {
      "id": "node_003_reply",
      "type": "llm",
      "position": {"x": 500, "y": 100},
      "config": {
        "model": "gpt-4o",
        "temperature": 0.7,
        "max_tokens": 500
      }
    },
    {
      "id": "node_004_safety",
      "type": "llm", 
      "position": {"x": 700, "y": 100},
      "config": {
        "model": "gpt-4o-mini",
        "temperature": 0.1
      }
    }
  ],
  "edges": [
    {"from": "start", "to": "node_001_intent"},
    {"from": "node_001_intent", "to": "node_002_memory"},
    {"from": "node_002_memory", "to": "node_003_reply"},
    {"from": "node_003_reply", "to": "node_004_safety"},
    {"from": "node_004_safety", "to": "end"}
  ]
}
```

---

## 环境变量配置

```env
# .env
AI_PROVIDER=coze

# Coze API
COZE_API_KEY=pat_xxxxxxxxxxxx
COZE_BASE_URL=https://api.coze.cn/v1

# 工作流 ID（在 Coze 平台创建后填入）
COZE_CHAT_WORKFLOW_ID=738xxxxxxxxxx
COZE_EXPLORE_WORKFLOW_ID=739xxxxxxxxxx
COZE_SUMMARY_WORKFLOW_ID=740xxxxxxxxxx
```

---

## 测试调用示例

### 聊天工作流调用
```bash
curl -X POST https://api.coze.cn/v1/workflows/738xxxxxx/execute \
  -H "Authorization: Bearer pat_xxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "user_message": "为什么天空是蓝色的？",
      "child_nickname": "小探险家", 
      "child_age": 6,
      "child_id": 1
    }
  }'
```

### 探索工作流调用
```bash
curl -X POST https://api.coze.cn/v1/workflows/739xxxxxx/execute \
  -H "Authorization: Bearer pat_xxxxx" \
  -H "Content-Type: application/json" \
  -d '{
    "inputs": {
      "file_url": "https://xxx.com/media/cat.jpg",
      "content_type": "image/jpeg",
      "file_size": 120000,
      "child_nickname": "小探险家",
      "child_age": 6
    }
  }'
```

---

## 注意事项

1. **节点顺序很重要**：先识别意图，再检索记忆，再生成回复，最后安全过滤
2. **上下文传递**：每个节点的输出通过变量传递给下游节点
3. **错误处理**：代码节点需要处理 API 超时、网络异常等情况
4. **Token 控制**：合理设置 Max Tokens，控制成本
5. **Temperature 设置**：意图识别/安全过滤用低值，创意回复用高值
