"""Prompt 模板集中管理。

成长报告场景的提示词工程：
- 系统提示词：设定 LLM 角色（儿童成长分析师）和输出规范
- 用户提示词模板：注入统计数据 + Memory 画像 + 近期记录
"""

from __future__ import annotations


# 成长报告 - 系统提示词（角色设定 + 输出规范）
REPORT_SYSTEM_PROMPT = """你是一位专业的儿童成长分析师，擅长根据儿童的探索记录和对话数据，分析孩子的兴趣偏好、认知发展水平和成长建议。

你的分析应该：
1. 用温暖、专业的语气，面向家长
2. 基于数据给出具体观察，避免空泛
3. 给出 2-3 条可执行的引导建议
4. 长度控制在 200-300 字
5. 用中文输出，使用 markdown 格式，包含三个二级标题：## 兴趣分析、## 认知发展、## 引导建议"""


# 成长报告 - 用户提示词模板（含占位符，运行时注入数据）
REPORT_USER_PROMPT_TEMPLATE = """请根据以下数据为 {nickname}（{age}岁）生成本周成长分析报告：

## 基础统计
- 探索次数：{total_explore}
- 对话会话：{total_chat_sessions}
- 对话消息：{total_chat_messages}
- 累计积分：{total_tokens_earned}

## 兴趣分布
{interests_text}

## 知识领域
{knowledge_text}

## 近期探索记录
{recent_explore_text}

## 近期对话话题
{recent_topics_text}

## 行为特征
- 提问占比：{question_ratio}（孩子主动提问的比例，反映好奇心）

请输出：
1. **兴趣分析**：孩子当前的主要兴趣方向
2. **认知发展**：从探索维度看认知发展情况
3. **引导建议**：2-3 条具体的家庭引导建议"""


def build_report_prompt(
    nickname: str,
    age: int,
    statistics: dict,
    profile: dict,
    recent_explore: list,
) -> str:
    """组装完整的用户提示词，把统计数据和画像注入模板。"""
    interests_text = "\n".join(
        f"- {i['name']}（{i['type']}）：{i['count']} 次"
        for i in profile.get("interests", [])[:5]
    ) or "暂无明显兴趣"

    knowledge_text = "\n".join(
        f"- {d['domain']}：{d['count']} 次"
        for d in profile.get("knowledge_domains", [])
    ) or "暂无数据"

    recent_explore_text = "\n".join(
        f"- {r.get('object_name', '未知')}（{r.get('growth_dimension', '')}）"
        for r in recent_explore[:5]
    ) or "暂无记录"

    recent_topics_text = "\n".join(
        f"- {t['topic']}：{t['count']} 次"
        for t in profile.get("chat_topics", [])[:5]
    ) or "暂无话题"

    behavior = profile.get("behavior", {})
    question_ratio = behavior.get("question_ratio", 0)

    return REPORT_USER_PROMPT_TEMPLATE.format(
        nickname=nickname,
        age=age,
        total_explore=statistics.get("total_explore", 0),
        total_chat_sessions=statistics.get("total_chat_sessions", 0),
        total_chat_messages=statistics.get("total_chat_messages", 0),
        total_tokens_earned=statistics.get("total_tokens_earned", 0),
        interests_text=interests_text,
        knowledge_text=knowledge_text,
        recent_explore_text=recent_explore_text,
        recent_topics_text=recent_topics_text,
        question_ratio=question_ratio,
    )
