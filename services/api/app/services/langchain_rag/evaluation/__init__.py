"""评估优化板块。

包含三部分能力：
1. 评估指标（metrics）：上下文召回率/精准率/MRR/F1/答案忠实度
2. 测试运行器（test_runner）：人工标注/自动化脚本/LLM评测/场景化专项
3. 问题诊断（diagnoser）：检索问题/生成问题/工程问题分类

以及优化策略子包（optimizer）：
- kb_preprocessor: 知识库预处理优化
- query_rewriter: 问题改写多路召回
- reranker: 检索重排 rerank
- hybrid_retriever: 多路召回+混合检索（向量+分词）
- semantic_compressor: 语义压缩、关键词提取
"""
from app.services.langchain_rag.evaluation.diagnoser import Diagnoser
from app.services.langchain_rag.evaluation.eval_router import eval_router
from app.services.langchain_rag.evaluation.metrics import RAGMetrics
from app.services.langchain_rag.evaluation.test_runner import TestRunner

__all__ = ["RAGMetrics", "TestRunner", "Diagnoser", "eval_router"]
