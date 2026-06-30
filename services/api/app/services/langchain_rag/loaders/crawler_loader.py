"""数据源②：网络爬虫（xpath / bs4 / re）。

支持三种解析器可切换，默认抓取百度百科科普词条作为儿童科普知识扩充。
"""
from __future__ import annotations

import re
from typing import Literal

import requests
from bs4 import BeautifulSoup
from lxml import etree
from langchain_core.documents import Document

ParserType = Literal["xpath", "bs4", "re"]

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
}


class CrawlerLoader:
    """网络爬虫加载器。"""

    def __init__(self, parser: ParserType = "bs4", timeout: int = 10) -> None:
        self.parser = parser
        self.timeout = timeout

    def fetch_html(self, url: str) -> str:
        """请求页面 HTML。"""
        resp = requests.get(url, headers=_DEFAULT_HEADERS, timeout=self.timeout)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text

    def crawl_baidu_baike(self, keyword: str) -> Document | None:
        """抓取百度百科词条（默认科普知识来源）。"""
        url = f"https://baike.baidu.com/item/{requests.utils.quote(keyword)}"
        try:
            html = self.fetch_html(url)
        except Exception:
            return None

        content = self._parse(html, url, keyword)
        if not content:
            return None
        return Document(
            page_content=content,
            metadata={
                "source": "crawler.baike",
                "source_id": url,
                "keyword": keyword,
                "parser": self.parser,
            },
        )

    def crawl_urls(self, urls: list[str], title: str | None = None) -> list[Document]:
        """批量抓取指定 URL 列表。"""
        docs: list[Document] = []
        for url in urls:
            try:
                html = self.fetch_html(url)
                content = self._parse(html, url, title or url)
                if content:
                    docs.append(Document(
                        page_content=content,
                        metadata={
                            "source": "crawler.url",
                            "source_id": url,
                            "parser": self.parser,
                        },
                    ))
            except Exception:
                continue
        return docs

    def _parse(self, html: str, url: str, title: str | None = None) -> str:
        """根据 parser 类型解析 HTML，返回纯文本。"""
        if self.parser == "xpath":
            return self._parse_xpath(html, title)
        if self.parser == "re":
            return self._parse_re(html, title)
        return self._parse_bs4(html, title)

    def _parse_bs4(self, html: str, title: str | None = None) -> str:
        """BeautifulSoup 解析。"""
        soup = BeautifulSoup(html, "lxml")
        # 标题
        title_text = title or (soup.find("h1").get_text(strip=True) if soup.find("h1") else "")
        # 百度百科正文在 class="lemma-summary" 或 main-content
        summary = soup.find("div", class_="lemma-summary")
        body = ""
        if summary:
            body = summary.get_text("\n", strip=True)
        else:
            main = soup.find("div", class_="main-content") or soup.find("body")
            if main:
                body = main.get_text("\n", strip=True)
        parts = [p for p in [title_text, body] if p]
        return "\n".join(parts)

    def _parse_xpath(self, html: str, title: str | None = None) -> str:
        """lxml xpath 解析。"""
        tree = etree.HTML(html)
        title_text = title or ""
        if not title_text:
            h1 = tree.xpath("//h1//text()")
            title_text = "".join(h1).strip()
        # 百度百科摘要
        summary = tree.xpath('//div[contains(@class,"lemma-summary")]//text()')
        body = "".join(summary).strip() if summary else ""
        if not body:
            body = "".join(tree.xpath("//body//text()")).strip()
        parts = [p for p in [title_text, body] if p]
        return "\n".join(parts)

    def _parse_re(self, html: str, title: str | None = None) -> str:
        """正则解析（去标签后提取文本）。"""
        title_text = title or ""
        if not title_text:
            m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
            if m:
                title_text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        # 去 script/style
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
        # 去标签
        text = re.sub(r"<[^>]+>", " ", text)
        # 压缩空白
        text = re.sub(r"\s+", " ", text).strip()
        parts = [p for p in [title_text, text] if p]
        return "\n".join(parts)
