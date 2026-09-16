#!/usr/bin/env python3
"""providers/ — 检索源多 provider 抽象（第六点评 P1：解 SCP 单点依赖）。

设计：
- EvidenceProvider 统一接口：search(query, top_k, domain) -> papers list；available() -> bool
- crossref_provider：免费、无需 Key、覆盖全学科，作为 SCP 不可达时的真实检索兜底
  （替代"降级到 mock"——mock 数据对真实研究没有价值）
- 失败链：SCP → Crossref → mock（mock 永远最后，且 is_mock=true 强制隔离）

新增 provider：继承 EvidenceProvider 实现 search/available，在 PROVIDER_CHAIN 注册。
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Optional

# Crossref REST API：免费、无 Key、全学科 DOI 元数据
CROSSREF_API = "https://api.crossref.org/works"
REQUEST_TIMEOUT = 20
UA = "InterSci-KD/4.9.0 (mailto:intersci-kd@users.noreply.github.com)"


class EvidenceProvider:
    """检索源统一接口。"""

    name = "base"

    def search(self, query: str, top_k: int, domain: Optional[str] = None) -> list[dict]:
        raise NotImplementedError

    def available(self) -> bool:
        return True


def _normalize_paper(item: dict, rank: int) -> dict:
    """Crossref 条目 → 项目标准 paper dict（字段名与 scp_tools 解析器对齐）。"""
    doi = (item.get("DOI") or "").strip()
    title_list = item.get("title") or []
    title = title_list[0] if title_list else ""
    year = None
    for key in ("published-print", "published-online", "issued", "created"):
        parts = (item.get(key) or {}).get("date-parts") or []
        if parts and parts[0]:
            year = parts[0][0]
            break
    source_type = "Journal_article"
    t = (item.get("type") or "").lower()
    if "proceedings" in t or "conference" in t:
        source_type = "Conference_paper"
    elif "journal" in t:
        source_type = "Journal_article"
    abstract = re.sub(r"<[^>]+>", "", item.get("abstract") or "")[:1000]
    # 置信度与 scp_tools 的年份启发一致
    import datetime
    age = datetime.datetime.now().year - year if isinstance(year, int) and year > 0 else None
    confidence = "high" if (age is not None and age <= 2) else ("medium" if age is not None and age <= 6 else "low")
    return {
        "rank": rank,
        "title": title[:300],
        "abstract": abstract,
        "year": year,
        "doi": doi,
        "source_type": source_type,
        "confidence": confidence,
        "journal": ((item.get("container-title") or [""])[0])[:120],
        "provider": "crossref",
    }


class CrossrefProvider(EvidenceProvider):
    """Crossref 检索源：免费无 Key，全学科 DOI 元数据。"""

    name = "crossref"

    def available(self) -> bool:
        return True  # 无需 Key；网络可达性在 search 时自然暴露

    def search(self, query: str, top_k: int, domain: Optional[str] = None) -> list[dict]:
        params = urllib.parse.urlencode({
            "query.bibliographic": query,
            "rows": min(max(top_k, 1), 50),
            "select": "DOI,title,issued,published-print,published-online,type,container-title,abstract",
            "sort": "relevance",
        })
        req = urllib.request.Request(f"{CROSSREF_API}?{params}", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        items = (data.get("message") or {}).get("items") or []
        papers = [_normalize_paper(it, i + 1) for i, it in enumerate(items)]
        # 无 DOI/无标题的条目丢弃（与 has_doi 判定对齐）
        return [p for p in papers if p["doi"] and p["title"]]


PROVIDER_CHAIN: list[EvidenceProvider] = [CrossrefProvider()]


def search_fallback(query: str, top_k: int, domain: Optional[str] = None) -> tuple[Optional[list[dict]], str]:
    """按 provider 链依次尝试真实检索。返回 (papers|None, provider_name)。

    全部失败返回 (None, "")——调用方继续走既有 mock 兜底（is_mock 隔离）。
    """
    for provider in PROVIDER_CHAIN:
        try:
            if not provider.available():
                continue
            papers = provider.search(query, top_k, domain)
            if papers:
                return papers, provider.name
        except Exception:  # noqa: BLE001 — 单个 provider 失败试下一个
            continue
    return None, ""


if __name__ == "__main__":
    papers, name = search_fallback("diabetic retinopathy deep learning", 5)
    print(f"provider={name}, count={len(papers or [])}")
    for p in (papers or [])[:3]:
        print(f"  {p['year']} {p['title'][:60]} | {p['doi']}")
