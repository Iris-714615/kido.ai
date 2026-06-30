"""评估指标计算（评估优化板块 - 指标层）。

实现 6 类核心指标：
1. 上下文召回率（Context Recall）：有效召回条数 / 总有效条数
2. 上下文精准率（Context Precision）：top-k 有效片段 / 应返回总数
3. MRR（平均倒数排名）：用专门公式 1/rank 求平均
4. 答案准确率（Answer Accuracy）：与标注答案的字符/语义匹配
5. 答案忠实度（Faithfulness）：防幻觉，可被上下文佐证的语句数 / 答案总语句数
6. F1 值：召回率与精准率的调和平均

依赖说明：
- 字符级匹配用 difflib（标准库）
- 语义级匹配用 embeddings 余弦相似度（延迟导入）
- 无外部专属指标库时，本模块自行实现 MRR/F1 公式
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any


def _split_sentences(text: str) -> list[str]:
    """切分句子（中文标点 + 换行）。"""
    if not text:
        return []
    parts = re.split(r"[。！？\n！？.!?]+", text)
    return [p.strip() for p in parts if p.strip()]


def _char_similarity(a: str, b: str) -> float:
    """字符级相似度（difflib SequenceMatcher，0~1）。"""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class MetricResult:
    """单条样本的指标结果。"""
    context_recall: float = 0.0
    context_precision: float = 0.0
    mrr: float = 0.0
    answer_accuracy: float = 0.0
    faithfulness: float = 0.0
    f1: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class AggregateReport:
    """整体评估报告（多条样本聚合）。"""
    sample_count: int = 0
    avg_context_recall: float = 0.0
    avg_context_precision: float = 0.0
    avg_mrr: float = 0.0
    avg_answer_accuracy: float = 0.0
    avg_faithfulness: float = 0.0
    avg_f1: float = 0.0
    per_sample: list[MetricResult] = field(default_factory=list)


class RAGMetrics:
    """RAG 评估指标计算器。"""

    def __init__(self, similarity_threshold: float = 0.5) -> None:
        # 字符相似度阈值，用于判定"有效召回/精准"
        self.threshold = similarity_threshold

    # ---------- 单样本指标 ----------
    def evaluate_sample(
        self,
        question: str,
        retrieved_docs: list[str],
        relevant_docs: list[str],
        answer: str,
        ground_truth: str | None = None,
        context: str | None = None,
    ) -> MetricResult:
        """评估单条样本的全部指标。

        Args:
            question: 用户问题
            retrieved_docs: 检索返回的文档片段列表（按返回顺序）
            relevant_docs: 人工标注的相关文档片段列表（应被召回）
            answer: LLM 生成的答案
            ground_truth: 人工标注的标准答案（可选，用于准确率）
            context: 注入 Prompt 的上下文文本（可选，用于忠实度）
        """
        result = MetricResult()

        # 1. 上下文召回率：有效召回条数 / 总有效条数
        result.context_recall = self._context_recall(retrieved_docs, relevant_docs)

        # 2. 上下文精准率：top-k 有效片段 / 应返回总数
        result.context_precision = self._context_precision(retrieved_docs, relevant_docs)

        # 3. MRR：第一个命中相关项的倒数排名
        result.mrr = self._mrr(retrieved_docs, relevant_docs)

        # 4. 答案准确率：与标注答案的字符相似度
        if ground_truth:
            result.answer_accuracy = _char_similarity(answer, ground_truth)

        # 5. 答案忠实度：可被上下文佐证的语句数 / 答案总语句数（防幻觉）
        ctx = context or "\n".join(retrieved_docs)
        result.faithfulness = self._faithfulness(answer, ctx)

        # 6. F1：召回率与精准率的调和平均
        result.f1 = self._f1(result.context_recall, result.context_precision)

        result.detail = {
            "retrieved_count": len(retrieved_docs),
            "relevant_count": len(relevant_docs),
            "answer_sentences": len(_split_sentences(answer)),
        }
        return result

    # ---------- 聚合报告 ----------
    def evaluate_batch(
        self,
        samples: list[dict],
    ) -> AggregateReport:
        """批量评估，返回聚合报告。

        每个 sample dict 需含：question, retrieved_docs, relevant_docs, answer
        可选：ground_truth, context
        """
        report = AggregateReport()
        for s in samples:
            r = self.evaluate_sample(**s)
            report.per_sample.append(r)
            report.sample_count += 1
            report.avg_context_recall += r.context_recall
            report.avg_context_precision += r.context_precision
            report.avg_mrr += r.mrr
            report.avg_answer_accuracy += r.answer_accuracy
            report.avg_faithfulness += r.faithfulness
            report.avg_f1 += r.f1

        n = max(1, report.sample_count)
        report.avg_context_recall /= n
        report.avg_context_precision /= n
        report.avg_mrr /= n
        report.avg_answer_accuracy /= n
        report.avg_faithfulness /= n
        report.avg_f1 /= n
        return report

    # ---------- 指标实现 ----------
    def _context_recall(self, retrieved: list[str], relevant: list[str]) -> float:
        """上下文召回率 = 有效召回条数 / 总有效条数。"""
        if not relevant:
            return 0.0
        hit = 0
        for rel in relevant:
            for ret in retrieved:
                if _char_similarity(rel, ret) >= self.threshold:
                    hit += 1
                    break
        return hit / len(relevant)

    def _context_precision(self, retrieved: list[str], relevant: list[str]) -> float:
        """上下文精准率 = top-k 有效片段 / 应返回总数。

        分母取 max(应返回总数, 实际返回数)，避免虚高。
        """
        if not retrieved:
            return 0.0
        valid_in_topk = 0
        for ret in retrieved:
            for rel in relevant:
                if _char_similarity(rel, ret) >= self.threshold:
                    valid_in_topk += 1
                    break
        denom = max(len(relevant), len(retrieved))
        return valid_in_topk / denom

    def _mrr(self, retrieved: list[str], relevant: list[str]) -> float:
        """MRR 平均倒数排名 = 1 / 第一个命中相关项的排名位置。

        多样本聚合时再求平均（见 evaluate_batch）。
        """
        for rank, ret in enumerate(retrieved, start=1):
            for rel in relevant:
                if _char_similarity(rel, ret) >= self.threshold:
                    return 1.0 / rank
        return 0.0

    def _faithfulness(self, answer: str, context: str) -> float:
        """答案忠实度（防幻觉）= 可被上下文佐证的语句数 / 答案总语句数。

        每句答案与上下文做字符相似度，超过阈值视为"可佐证"。
        """
        sentences = _split_sentences(answer)
        if not sentences:
            return 0.0
        supported = 0
        for sent in sentences:
            # 句子与上下文的最高相似度
            max_sim = 0.0
            for ctx_sent in _split_sentences(context):
                sim = _char_similarity(sent, ctx_sent)
                if sim > max_sim:
                    max_sim = sim
            # 整段上下文兜底比对
            if max_sim < self.threshold:
                max_sim = max(max_sim, _char_similarity(sent, context))
            if max_sim >= self.threshold:
                supported += 1
        return supported / len(sentences)

    @staticmethod
    def _f1(recall: float, precision: float) -> float:
        """F1 = 2*P*R / (P+R)。"""
        if recall + precision == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)
