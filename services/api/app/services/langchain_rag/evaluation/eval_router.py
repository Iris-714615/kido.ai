"""评估优化路由（评估优化板块 - API 层）。

挂在主 deep_router 下，前缀 /deep：
- 评估：/deep/eval/metrics | /deep/eval/batch | /deep/eval/diagnose | /deep/eval/scenarios | /deep/eval/llm_judge
- 优化：/deep/optimize/rewrite | /deep/optimize/rerank | /deep/optimize/hybrid | /deep/optimize/compress | /deep/optimize/keywords
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.langchain_rag.evaluation.diagnoser import Diagnoser
from app.services.langchain_rag.evaluation.metrics import RAGMetrics
from app.services.langchain_rag.evaluation.optimizer.hybrid_retriever import HybridRetriever
from app.services.langchain_rag.evaluation.optimizer.query_rewriter import QueryRewriter
from app.services.langchain_rag.evaluation.optimizer.reranker import Reranker
from app.services.langchain_rag.evaluation.optimizer.semantic_compressor import SemanticCompressor
from app.services.langchain_rag.evaluation.test_runner import TestRunner

eval_router = APIRouter(tags=["langchain-rag-eval"])


# ========== 请求模型 ==========
class EvalSampleRequest(BaseModel):
    question: str
    retrieved_docs: list[str]
    relevant_docs: list[str]
    answer: str
    ground_truth: str | None = None
    context: str | None = None


class EvalBatchRequest(BaseModel):
    samples: list[EvalSampleRequest]


class DiagnoseRequest(BaseModel):
    metrics: dict[str, float]
    retrieved_count: int = 0
    relevant_count: int = 0
    answer: str = ""
    question: str = ""
    latency_ms: int | None = None
    error: str | None = None


class AutoTestRequest(BaseModel):
    questions: list[str]


class OptimizeQueryRequest(BaseModel):
    question: str
    k_per_query: int = 3


class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    top_n: int = 5
    score_threshold: float = 0.3
    method: str = "auto"


class HybridRequest(BaseModel):
    query: str
    top_k: int = 5
    vector_weight: float = 0.6
    bm25_weight: float = 0.4


class CompressRequest(BaseModel):
    question: str
    documents: list[str]


class KeywordsRequest(BaseModel):
    text: str
    top_n: int = 5


# ========== 评估接口 ==========
@eval_router.post("/eval/metrics")
def eval_metrics(req: EvalSampleRequest):
    """单样本指标评估（召回率/精准率/MRR/准确率/忠实度/F1）。"""
    m = RAGMetrics().evaluate_sample(
        question=req.question,
        retrieved_docs=req.retrieved_docs,
        relevant_docs=req.relevant_docs,
        answer=req.answer,
        ground_truth=req.ground_truth,
        context=req.context,
    )
    return {
        "code": 200,
        "metrics": {
            "context_recall": round(m.context_recall, 4),
            "context_precision": round(m.context_precision, 4),
            "mrr": round(m.mrr, 4),
            "answer_accuracy": round(m.answer_accuracy, 4),
            "faithfulness": round(m.faithfulness, 4),
            "f1": round(m.f1, 4),
        },
        "detail": m.detail,
    }


@eval_router.post("/eval/batch")
def eval_batch(req: EvalBatchRequest):
    """批量评估，返回聚合报告。"""
    samples = [s.model_dump() for s in req.samples]
    report = RAGMetrics().evaluate_batch(samples)
    return {
        "code": 200,
        "sample_count": report.sample_count,
        "avg": {
            "context_recall": round(report.avg_context_recall, 4),
            "context_precision": round(report.avg_context_precision, 4),
            "mrr": round(report.avg_mrr, 4),
            "answer_accuracy": round(report.avg_answer_accuracy, 4),
            "faithfulness": round(report.avg_faithfulness, 4),
            "f1": round(report.avg_f1, 4),
        },
    }


@eval_router.post("/eval/diagnose")
def eval_diagnose(req: DiagnoseRequest):
    """问题诊断（检索/生成/工程问题分类 + 优化建议）。"""
    report = Diagnoser().diagnose(
        metrics=req.metrics,
        retrieved_count=req.retrieved_count,
        relevant_count=req.relevant_count,
        answer=req.answer,
        question=req.question,
        latency_ms=req.latency_ms,
        error=req.error,
    )
    return {
        "code": 200,
        "summary": report.summary,
        "issues": [
            {
                "category": i.category,
                "name": i.name,
                "severity": i.severity,
                "metric_value": i.metric_value,
                "suggestion": i.suggestion,
            }
            for i in report.issues
        ],
    }


@eval_router.post("/eval/scenarios")
def eval_scenarios():
    """场景化专项测试（科普/个人记录/统计/天气四类）。

    会真实调用 RAG，可能较慢。
    """
    runner = TestRunner(use_tools=True)
    results = runner.run_scenarios()
    return {
        "code": 200,
        "count": len(results),
        "results": [
            {
                "scenario": r.scenario,
                "question": r.question,
                "answer": r.answer,
                "tool_used": r.tool_used,
                "tool_match": r.tool_match,
                "metrics": r.metrics,
            }
            for r in results
        ],
    }


@eval_router.post("/eval/auto")
def eval_auto(req: AutoTestRequest):
    """自动化脚本测试（仅问题列表，跑 RAG 验证可用性）。"""
    runner = TestRunner(use_tools=True)
    results, report = runner.run_auto(req.questions)
    return {
        "code": 200,
        "count": len(results),
        "avg": {
            "context_recall": round(report.avg_context_recall, 4),
            "context_precision": round(report.avg_context_precision, 4),
            "mrr": round(report.avg_mrr, 4),
            "faithfulness": round(report.avg_faithfulness, 4),
            "f1": round(report.avg_f1, 4),
        },
        "results": [
            {
                "question": r.question,
                "answer": r.answer,
                "retrieved_count": len(r.retrieved_docs),
                "tool_used": r.tool_used,
            }
            for r in results
        ],
    }


# ========== 优化接口 ==========
@eval_router.post("/optimize/rewrite")
def optimize_rewrite(req: OptimizeQueryRequest):
    """问题改写多路召回（返回子问题 + 合并检索结果）。"""
    rewriter = QueryRewriter()
    sub_questions = rewriter.rewrite(req.question)
    docs = rewriter.retrieve_with_rewrites(req.question, k_per_query=req.k_per_query)
    return {
        "code": 200,
        "sub_questions": sub_questions,
        "merged_count": len(docs),
        "documents": [
            {"content": d.page_content[:200], "source_id": d.metadata.get("source_id")}
            for d in docs
        ],
    }


@eval_router.post("/optimize/rerank")
def optimize_rerank(req: RerankRequest):
    """检索重排 rerank。"""
    from langchain_core.documents import Document
    docs = [Document(page_content=t) for t in req.documents]
    reranker = Reranker(top_n=req.top_n, score_threshold=req.score_threshold, method=req.method)
    reranked = reranker.rerank(req.query, docs)
    return {
        "code": 200,
        "input_count": len(req.documents),
        "output_count": len(reranked),
        "documents": [d.page_content for d in reranked],
    }


@eval_router.post("/optimize/hybrid")
def optimize_hybrid(req: HybridRequest):
    """多路召回 + 混合检索（向量 + BM25）。"""
    retriever = HybridRetriever(
        vector_weight=req.vector_weight,
        bm25_weight=req.bm25_weight,
        top_k=req.top_k,
    )
    docs = retriever.retrieve(req.query)
    return {
        "code": 200,
        "count": len(docs),
        "documents": [
            {"content": d.page_content[:200], "source_id": d.metadata.get("source_id")}
            for d in docs
        ],
    }


@eval_router.post("/optimize/compress")
def optimize_compress(req: CompressRequest):
    """语义压缩。"""
    from langchain_core.documents import Document
    docs = [Document(page_content=t) for t in req.documents]
    compressor = SemanticCompressor()
    compressed = compressor.compress(req.question, docs)
    return {"code": 200, "compressed": compressed}


@eval_router.post("/optimize/keywords")
def optimize_keywords(req: KeywordsRequest):
    """关键词提取。"""
    compressor = SemanticCompressor()
    kws = compressor.extract_keywords(req.text, top_n=req.top_n)
    return {"code": 200, "keywords": kws}
