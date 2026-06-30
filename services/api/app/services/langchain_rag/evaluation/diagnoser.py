"""问题诊断（评估优化板块 - 诊断层）。

根据评估指标和运行特征，把问题分类为三大类并给出优化建议：
1. 检索问题：漏召回、无关召回、排序靠后、上下文不足
2. 生成问题：幻觉编造、总结冗余、答非所问、逻辑混乱、要点遗漏
3. 工程问题：响应延迟、并发报错、上下文截断异常
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DiagnosisIssue:
    """单个诊断出的问题。"""
    category: str  # retrieval / generation / engineering
    name: str  # 问题名（如 漏召回）
    severity: str  # high / medium / low
    metric_value: float | None = None
    suggestion: str = ""  # 优化建议


@dataclass
class DiagnosisReport:
    """诊断报告。"""
    issues: list[DiagnosisIssue] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)  # 各类别问题计数

    def add(self, issue: DiagnosisIssue) -> None:
        self.issues.append(issue)
        self.summary[issue.category] = self.summary.get(issue.category, 0) + 1


class Diagnoser:
    """RAG 问题诊断器。

    阈值均可配置，默认值基于经验。
    """

    def __init__(
        self,
        recall_threshold: float = 0.6,
        precision_threshold: float = 0.5,
        mrr_threshold: float = 0.5,
        faithfulness_threshold: float = 0.7,
        latency_ms_threshold: int = 3000,
    ) -> None:
        self.recall_threshold = recall_threshold
        self.precision_threshold = precision_threshold
        self.mrr_threshold = mrr_threshold
        self.faithfulness_threshold = faithfulness_threshold
        self.latency_ms_threshold = latency_ms_threshold

    def diagnose(
        self,
        metrics: dict[str, float],
        retrieved_count: int = 0,
        relevant_count: int = 0,
        answer: str = "",
        question: str = "",
        latency_ms: int | None = None,
        error: str | None = None,
    ) -> DiagnosisReport:
        """根据单条样本的指标与运行特征诊断问题。

        Args:
            metrics: evaluate_sample 返回的指标 dict
            retrieved_count: 实际召回条数
            relevant_count: 标注相关条数
            answer: 生成答案
            question: 用户问题
            latency_ms: 响应耗时（毫秒）
            error: 异常信息
        """
        report = DiagnosisReport()

        # ===== 工程问题（优先判，若有异常直接归类）=====
        if error:
            report.add(DiagnosisIssue(
                category="engineering",
                name="并发/运行报错",
                severity="high",
                suggestion="检查异常栈，常见为 API 限流/连接超时/线程安全。建议加重试 + 限流 + 异步隔离。",
            ))
            if "length" in error.lower() or "token" in error.lower() or "truncat" in error.lower():
                report.add(DiagnosisIssue(
                    category="engineering",
                    name="上下文截断异常",
                    severity="high",
                    suggestion="缩短检索结果数或单段长度，开启 chunk_size 控制，注入前做 token 计数截断。",
                ))
            return report

        if latency_ms is not None and latency_ms > self.latency_ms_threshold:
            report.add(DiagnosisIssue(
                category="engineering",
                name="响应延迟",
                severity="medium",
                metric_value=float(latency_ms),
                suggestion="异步多线程 + 流式输出；检索结果缓存；冷启动时预热向量库。",
            ))

        # ===== 检索问题 =====
        recall = metrics.get("context_recall", 0.0)
        precision = metrics.get("context_precision", 0.0)
        mrr = metrics.get("mrr", 0.0)

        if relevant_count > 0 and recall < self.recall_threshold:
            report.add(DiagnosisIssue(
                category="retrieval",
                name="漏召回",
                severity="high",
                metric_value=recall,
                suggestion="启用问题改写多路召回（改写成3个子问题）；混合检索（向量+BM25）；降低相似度阈值。",
            ))

        if retrieved_count > 0 and precision < self.precision_threshold:
            report.add(DiagnosisIssue(
                category="retrieval",
                name="无关召回",
                severity="medium",
                metric_value=precision,
                suggestion="启用 rerank 重排过滤低相关片段；提高相似度阈值；语义压缩去噪。",
            ))

        if relevant_count > 0 and mrr < self.mrr_threshold:
            report.add(DiagnosisIssue(
                category="retrieval",
                name="排序靠后",
                severity="medium",
                metric_value=mrr,
                suggestion="引入 rerank 模型重排；调整检索 k 值；用语义相似度而非 L2 距离。",
            ))

        if retrieved_count == 0:
            report.add(DiagnosisIssue(
                category="retrieval",
                name="上下文不足",
                severity="high",
                suggestion="知识库覆盖不足，扩充数据源（爬虫/蒸馏/文档）；问题向量化失配，检查 embedding 模型。",
            ))

        # ===== 生成问题 =====
        faithfulness = metrics.get("faithfulness", 0.0)
        if faithfulness < self.faithfulness_threshold:
            report.add(DiagnosisIssue(
                category="generation",
                name="幻觉编造",
                severity="high",
                metric_value=faithfulness,
                suggestion="Prompt 强约束『仅基于知识库回答』；降低 temperature；后检拒绝无佐证语句。",
            ))

        if answer:
            ans_len = len(answer)
            if ans_len > 400:
                report.add(DiagnosisIssue(
                    category="generation",
                    name="总结冗余",
                    severity="low",
                    metric_value=float(ans_len),
                    suggestion="Prompt 限制字数（如200字内）；语义压缩检索结果再生成。",
                ))
            if question and len(answer) > 0:
                # 简易答非所问判定：答案与问题关键词无交集
                if not self._has_overlap(question, answer):
                    report.add(DiagnosisIssue(
                        category="generation",
                        name="答非所问",
                        severity="high",
                        suggestion="强化 Prompt 中『回答孩子最新的问题』约束；检查历史注入是否污染上下文。",
                    ))
            # 逻辑混乱/要点遗漏需 LLM 评测判定，此处给占位
            if faithfulness > self.faithfulness_threshold and recall > self.recall_threshold and precision > self.precision_threshold:
                # 检索OK但答案质量仍差，疑似生成侧问题
                if ans_len < 30:
                    report.add(DiagnosisIssue(
                        category="generation",
                        name="要点遗漏",
                        severity="medium",
                        suggestion="Prompt 要求覆盖知识库要点；增加 few-shot 示例。",
                    ))

        return report

    @staticmethod
    def _has_overlap(question: str, answer: str) -> bool:
        """问题与答案是否有词级交集（简易判定答非所问）。"""
        import re
        q_words = set(re.findall(r"[\u4e00-\u9fa5]{2,}", question))
        a_words = set(re.findall(r"[\u4e00-\u9fa5]{2,}", answer))
        return bool(q_words & a_words)

    def diagnose_batch(self, samples: list[dict]) -> list[DiagnosisReport]:
        """批量诊断。"""
        return [self.diagnose(**s) for s in samples]
