"""敏感词过滤器（任务三关键要求）。

使用 Aho-Corasick 自动机高效多模式匹配，支持：
- 入库前清洗：过滤/打码文档块
- 出库后过滤：过滤检索结果 + LLM 输出
- 双向检测：预检（用户输入）+ 后检（模型输出）

词表来源：
1. 内置儿童场景敏感词（暴力/色情/政治敏感等示例）
2. 可选外部 sensitive_words.txt（每行一个词）
"""
from __future__ import annotations

import threading
from pathlib import Path

import ahocorasick

# 内置敏感词（儿童场景示例，实际项目应维护更完整词表）
_DEFAULT_SENSITIVE_WORDS = [
    # 暴力相关
    "杀", "杀人", "自杀", "炸弹", "枪杀", "血腥", "暴力", "凶杀",
    # 色情相关
    "色情", "裸体", "性行为", "强奸",
    # 政治敏感（示例占位）
    "反动",
    # 负面引导
    "赌博", "吸毒", "毒品", "传销",
    # 个人信息保护（儿童场景不应出现）
    "身份证号", "银行卡号",
]

# 敏感词外部词表路径（可选）
_WORDS_FILE = Path(__file__).resolve().parents[5] / "data" / "sensitive_words.txt"

_automaton = None
_lock = threading.Lock()


def _load_words() -> list[str]:
    """加载敏感词：内置 + 外部文件。"""
    words = list(_DEFAULT_SENSITIVE_WORDS)
    if _WORDS_FILE.exists():
        try:
            with open(_WORDS_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    w = line.strip()
                    if w and not w.startswith("#"):
                        words.append(w)
        except Exception:
            pass
    # 去重
    return list(dict.fromkeys(words))


def _build_automaton():
    """构建 Aho-Corasick 自动机。"""
    words = _load_words()
    auto = ahocorasick.Automaton()
    for idx, word in enumerate(words):
        if word:
            auto.add_word(word, (idx, word))
    auto.make_automaton()
    return auto


def _get_automaton():
    """获取自动机单例。"""
    global _automaton
    if _automaton is not None:
        return _automaton
    with _lock:
        if _automaton is None:
            _automaton = _build_automaton()
        return _automaton


def reload_words() -> int:
    """重新加载敏感词表（运行期热更新），返回词数。"""
    global _automaton
    with _lock:
        _automaton = _build_automaton()
    return len(_load_words())


class SensitiveFilter:
    """敏感词过滤器。"""

    MASK = "***"

    @staticmethod
    def scan(text: str) -> list[str]:
        """扫描文本，返回命中的敏感词列表。"""
        if not text:
            return []
        auto = _get_automaton()
        hits: list[str] = []
        for _, (_, word) in auto.iter(text):
            hits.append(word)
        return list(dict.fromkeys(hits))

    @staticmethod
    def contains(text: str) -> bool:
        """是否包含敏感词。"""
        if not text:
            return False
        auto = _get_automaton()
        for _ in auto.iter(text):
            return True
        return False

    @staticmethod
    def mask(text: str) -> str:
        """将敏感词打码为 ***。"""
        if not text:
            return text
        auto = _get_automaton()
        result = text
        # 按命中位置从后往前替换，避免偏移
        matches: list[tuple[int, int, str]] = []
        for end_idx, (_, word) in auto.iter(text):
            start_idx = end_idx - len(word) + 1
            matches.append((start_idx, end_idx + 1, word))
        # 去重并按 start 降序
        matches.sort(key=lambda x: x[0], reverse=True)
        seen_spans: set[tuple[int, int]] = set()
        for start, end, _ in matches:
            if (start, end) in seen_spans:
                continue
            seen_spans.add((start, end))
            result = result[:start] + SensitiveFilter.MASK + result[end:]
        return result

    @staticmethod
    def filter_documents(documents, drop: bool = True):
        """过滤文档块。

        Args:
            documents: langchain Document 列表
            drop: True=丢弃含敏感词的块；False=打码保留
        """
        from langchain_core.documents import Document

        out: list[Document] = []
        for doc in documents:
            if SensitiveFilter.contains(doc.page_content):
                if drop:
                    continue
                doc = Document(
                    page_content=SensitiveFilter.mask(doc.page_content),
                    metadata=doc.metadata.copy(),
                )
            out.append(doc)
        return out
