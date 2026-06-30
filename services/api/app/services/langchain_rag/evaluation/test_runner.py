"""测试运行器（评估优化板块 - 测试层）。

支持 4 种测试方式：
1. 人工标注测试：从标注数据集（JSON/CSV）加载样本，跑 RAG 后对比
2. 自动化脚本测试：批量调用 retriever/chain，用 metrics 自动计算指标
3. LLM 评测：用大模型对"答案质量"打分（无标注答案时也可用）
4. 场景化专项：针对科普/个人记录/统计/天气等场景的专项用例

标注数据集格式（JSON 数组）：
    [
      {
        "question": "为什么天是蓝的？",
        "relevant_docs": ["瑞利散射使蓝光散射更强..."],
        "ground_truth": "因为大气分子对蓝光散射更强..."
      }
    ]
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.langchain_rag.evaluation.metrics import AggregateReport, RAGMetrics
from app.services.langchain_rag.rag.chain import RAGAgentChain
from app.services.langchain_rag.rag.retriever import RAGRetriever

logger = logging.getLogger(__name__)

# 默认场景化专项用例（科普/个人记录/统计/天气）
DEFAULT_SCENARIO_CASES: list[dict] = [
    {
        "scenario": "科普知识",
        "question": "为什么彩虹是弧形的？",
        "relevant_docs": ["彩虹是阳光在水滴中折射反射形成的弧形光谱"],
        "ground_truth": "彩虹是阳光经过雨滴折射和反射形成的弧形彩色光带",
    },
    {
        "scenario": "个人记录",
        "question": "我上次拍到了什么？",
        "relevant_docs": [],
        "ground_truth": "需调用 query_explore_records 工具查询",
        "expect_tool": "query_explore_records",
    },
    {
        "scenario": "成长统计",
        "question": "我已经探索多少次了？",
        "relevant_docs": [],
        "ground_truth": "需调用 query_growth_stats 工具查询",
        "expect_tool": "query_growth_stats",
    },
    {
        "scenario": "天气查询",
        "question": "今天北京天气怎么样？",
        "relevant_docs": [],
        "ground_truth": "需调用 query_weather 工具查询",
        "expect_tool": "query_weather",
    },
]


@dataclass
class TestSample:
    """测试样本。"""
    question: str
    relevant_docs: list[str] = field(default_factory=list)
    ground_truth: str | None = None
    scenario: str | None = None
    expect_tool: str | None = None  # 场景化：期望触发的工具


@dataclass
class TestCaseResult:
    """单条测试结果。"""
    question: str
    answer: str
    retrieved_docs: list[str]
    tool_used: list[str]
    metrics: dict[str, float]
    scenario: str | None = None
    tool_match: bool | None = None  # 场景化：是否触发期望工具


class TestRunner:
    """RAG 测试运行器。"""

    def __init__(self, metrics: RAGMetrics | None = None, use_tools: bool = True) -> None:
        self.metrics = metrics or RAGMetrics()
        self.use_tools = use_tools

    # ---------- 数据集加载 ----------
    @staticmethod
    def load_dataset(path: str | Path) -> list[TestSample]:
        """从 JSON 文件加载人工标注数据集。"""
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        samples: list[TestSample] = []
        for item in data:
            samples.append(TestSample(
                question=item["question"],
                relevant_docs=item.get("relevant_docs", []),
                ground_truth=item.get("ground_truth"),
                scenario=item.get("scenario"),
                expect_tool=item.get("expect_tool"),
            ))
        return samples

    @staticmethod
    def save_dataset(samples: list[TestSample], path: str | Path) -> None:
        """保存数据集到 JSON（便于人工标注累积）。"""
        path = Path(path)
        data = [
            {
                "question": s.question,
                "relevant_docs": s.relevant_docs,
                "ground_truth": s.ground_truth,
                "scenario": s.scenario,
                "expect_tool": s.expect_tool,
            }
            for s in samples
        ]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- ① 人工标注测试 ----------
    def run_annotated(self, samples: list[TestSample]) -> tuple[list[TestCaseResult], AggregateReport]:
        """人工标注测试：用标注数据集跑 RAG，自动计算指标。"""
        return self._run_samples(samples)

    # ---------- ② 自动化脚本测试 ----------
    def run_auto(self, questions: list[str]) -> tuple[list[TestCaseResult], AggregateReport]:
        """自动化脚本测试：仅有问题无标注，跑 RAG 看检索+生成是否正常。

        无 relevant_docs / ground_truth 时指标会偏低，主要用于工程可用性验证。
        """
        samples = [TestSample(question=q) for q in questions]
        return self._run_samples(samples)

    # ---------- ③ LLM 评测 ----------
    def run_llm_judge(self, samples: list[TestSample]) -> list[dict]:
        """LLM 评测：用大模型对生成的答案打分（无标注答案时尤为有用）。

        评分维度：相关性 / 准确性 / 简洁性 / 儿童友好度，各 0~5 分。
        """
        chain = RAGAgentChain(use_tools=self.use_tools)
        results: list[dict] = []
        judge_prompt = self._build_judge_prompt()

        for s in samples:
            try:
                rag_result = chain.invoke(s.question)
                answer = rag_result["answer"]
                score = self._llm_judge(judge_prompt, s.question, answer)
                results.append({
                    "question": s.question,
                    "answer": answer,
                    "llm_score": score,
                })
            except Exception as e:
                logger.warning("LLM 评测失败 %s: %s", s.question, e)
                results.append({"question": s.question, "error": str(e)})
        return results

    # ---------- ④ 场景化专项 ----------
    def run_scenarios(self, cases: list[dict] | None = None) -> list[TestCaseResult]:
        """场景化专项：科普/个人记录/统计/天气四类场景。"""
        cases = cases or DEFAULT_SCENARIO_CASES
        samples = [TestSample(
            question=c["question"],
            relevant_docs=c.get("relevant_docs", []),
            ground_truth=c.get("ground_truth"),
            scenario=c.get("scenario"),
            expect_tool=c.get("expect_tool"),
        ) for c in cases]
        results, _ = self._run_samples(samples)
        # 场景化：校验是否触发了期望工具
        for r, c in zip(results, cases):
            if r.expect_tool:
                r.tool_match = r.expect_tool in r.tool_used
        return results

    # ---------- 内部执行 ----------
    def _run_samples(self, samples: list[TestSample]) -> tuple[list[TestCaseResult], AggregateReport]:
        chain = RAGAgentChain(use_tools=self.use_tools)
        retriever = RAGRetriever()
        results: list[TestCaseResult] = []
        batch: list[dict] = []

        for s in samples:
            try:
                # 检索（用于指标）
                retrieval = retriever.retrieve(s.question)
                retrieved_docs = [d.page_content for d in retrieval.documents]
                # 生成
                rag_result = chain.invoke(s.question)
                answer = rag_result["answer"]
                tool_used = rag_result.get("tool_used", [])

                m = self.metrics.evaluate_sample(
                    question=s.question,
                    retrieved_docs=retrieved_docs,
                    relevant_docs=s.relevant_docs,
                    answer=answer,
                    ground_truth=s.ground_truth,
                    context=retrieval.context,
                )
                results.append(TestCaseResult(
                    question=s.question,
                    answer=answer,
                    retrieved_docs=retrieved_docs,
                    tool_used=tool_used,
                    metrics={
                        "context_recall": m.context_recall,
                        "context_precision": m.context_precision,
                        "mrr": m.mrr,
                        "answer_accuracy": m.answer_accuracy,
                        "faithfulness": m.faithfulness,
                        "f1": m.f1,
                    },
                    scenario=s.scenario,
                ))
                batch.append({
                    "question": s.question,
                    "retrieved_docs": retrieved_docs,
                    "relevant_docs": s.relevant_docs,
                    "answer": answer,
                    "ground_truth": s.ground_truth,
                    "context": retrieval.context,
                })
            except Exception as e:
                logger.warning("测试样本失败 %s: %s", s.question, e)
                results.append(TestCaseResult(
                    question=s.question,
                    answer=f"<error: {e}>",
                    retrieved_docs=[],
                    tool_used=[],
                    metrics={},
                    scenario=s.scenario,
                ))

        report = self.metrics.evaluate_batch(batch)
        return results, report

    # ---------- LLM 评测辅助 ----------
    def _build_judge_prompt(self) -> str:
        return (
            "你是儿童科普问答的评测专家。请对下面的回答打分，维度：\n"
            "1. 相关性（0-5）：是否切题\n"
            "2. 准确性（0-5）：知识是否正确\n"
            "3. 简洁性（0-5）：是否简洁不冗余\n"
            "4. 儿童友好度（0-5）：是否适合6-12岁理解\n"
            "严格输出 JSON：{\"relevance\": x, \"accuracy\": x, \"conciseness\": x, \"friendliness\": x, \"comment\": \"...\"}\n"
            "不要输出 JSON 以外内容。"
        )

    def _llm_judge(self, system_prompt: str, question: str, answer: str) -> dict:
        """调用 LLM 评分。"""
        from app.services.langchain_rag.core.llm import LLMFactory
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "问题：{question}\n回答：{answer}"),
        ])
        chain = prompt | LLMFactory.get_llm(temperature=0.0)
        res = chain.invoke({"question": question, "answer": answer})
        import re
        text = res.content.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw": res.content}
