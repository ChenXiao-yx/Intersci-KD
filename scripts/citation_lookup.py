#!/usr/bin/env python3
"""citation_lookup.py — Semantic Scholar 被引数据查询（第三轮评估②）。

激活 validity_states.json 中【低影响力】枚举的支撑数据源：
- 单条查询：GET /graph/v1/paper/DOI:{doi}?fields=citationCount,influentialCitationCount
- 批量查询：POST /graph/v1/paper/batch（一次最多 500 个 DOI，限速友好）

字段说明：
- citationCount: 总被引数 —— 用于【低影响力】判定（显著低于同方向中位数）
- influentialCitationCount: S2 计算的"有影响力被引数"（更抗灌水）
- 两者一并返回，供第零章"知识密度"与第十章"有效性状态"使用

使用纪律：
- 无 API Key 时使用公共限速端点（100 req/5min 单机），批量用 batch 端点一次拿全
- 查询失败（网络/429/未收录）→ 返回 None，由调用方走既有兜底规则
  （output-template.md：citation_count 缺失 → 状态标「无法验证」，不得臆断「低影响力」）

纯标准库实现（urllib），与 score_evidence.py 同级零依赖。
用法：
    python scripts/citation_lookup.py --dois 10.1001/jama.2016.17216 10.1038/nm.4345
    python scripts/citation_lookup.py --input examples/dr_papers.json --output citations.json
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

S2_BASE = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "citationCount,influentialCitationCount,title,year"
BATCH_SIZE = 500
REQUEST_TIMEOUT = 20
# 429/网络错误重试参数（尊重 Retry-After）
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5


def _request_json(url: str, data=None, headers=None) -> dict:
    """带 429/网络错误重试的 JSON GET/POST。

    data: Optional[bytes]（POST 请求体）；headers: Optional[dict]。类型注解不用 PEP 604 语法（pyproject requires-python >=3.8，P0-2）。失败抛 RuntimeError（由上层决定兜底）。"""
    req = urllib.request.Request(url, data=data, headers=headers or {"User-Agent": "InterSci-KD/4.9.0"})
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = float(e.headers.get("Retry-After", RETRY_BASE_DELAY * (attempt + 1)))
                time.sleep(retry_after)
                last_err = f"rate_limited(429) attempt={attempt + 1}"
                continue
            last_err = f"http_{e.code}"
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = f"{type(e).__name__}"
            time.sleep(RETRY_BASE_DELAY * (attempt + 1))
    raise RuntimeError(f"Semantic Scholar request failed: {last_err}")


def lookup_by_dois(dois: List[str]) -> Dict[str, Optional[dict]]:
    """批量查询 DOI 的被引数据。

    返回 {normalized_doi: {"citation_count": int, "influential_citation_count": int,
                           "title": str, "year": int} 或 None}；
    未收录/查询失败的 DOI 值为 None（调用方走兜底规则，不得臆断低影响力）。
    """
    normalized = [str(d).strip().lower() for d in dois if d and str(d).strip()]
    # DOI 归一化：去 https://doi.org/ 前缀与 arXiv 伪 DOI
    cleaned = []
    seen = set()
    for d in normalized:
        if d.startswith("https://doi.org/"):
            d = d[len("https://doi.org/"):]
        if d.startswith("arxiv:") or d.startswith("10.48550/arxiv"):
            continue  # 预印本非 S2 收录主键，跳过（调用方按预印本规则处理）
        if d and d not in seen:
            seen.add(d)
            cleaned.append(d)

    result: Dict[str, Optional[dict]] = {d: None for d in cleaned}
    if not cleaned:
        return result

    # 优先 batch 端点（一次 500 个，限速友好）
    for i in range(0, len(cleaned), BATCH_SIZE):
        chunk = cleaned[i:i + BATCH_SIZE]
        body = json.dumps({"ids": [f"DOI:{d}" for d in chunk]}).encode("utf-8")
        url = f"{S2_BASE}/paper/batch?fields={S2_FIELDS}"
        try:
            rows = _request_json(url, data=body, headers={
                "User-Agent": "InterSci-KD/4.9.0", "Content-Type": "application/json"})
        except RuntimeError:
            continue  # 整批失败：全部留 None
        for d, row in zip(chunk, rows):
            if row and isinstance(row, dict) and row.get("citationCount") is not None:
                result[d] = {
                    "citation_count": row["citationCount"],
                    "influential_citation_count": row.get("influentialCitationCount", 0),
                    "title": row.get("title", ""),
                    "year": row.get("year"),
                }
    return result


def enrich_papers_with_citations(papers: List[dict], existing=None) -> dict:
    """给 papers 列表补 citation_count / influential_citation_count 字段。

    返回 lookup 结果 dict（{doi: row 或 None}），供调用方持久化复用。
    - 已有 citation_count 的条目跳过（尊重 SCP 工具返回的值）
    - 查询失败的条目不写 citation_count 字段（保持"缺失→无法验证"兜底语义）
    """
    # existing: 之前的 lookup 缓存（避免重复请求）
    cache: Dict[str, Optional[dict]] = dict(existing or {})
    need = []
    for p in papers:
        doi = str(p.get("doi", "")).strip().lower()
        if not doi or doi.startswith("arxiv:") or doi.startswith("10.48550/arxiv"):
            continue
        if p.get("citation_count") is not None:
            continue  # SCP 工具已返回被引数
        if doi in cache:
            continue  # 已查过（含查不到的 None）
        need.append(doi)

    if need:
        cache.update(lookup_by_dois(need))

    for p in papers:
        doi = str(p.get("doi", "")).strip().lower()
        if not doi or doi not in cache or cache[doi] is None:
            continue
        row = cache[doi]
        p["citation_count"] = row["citation_count"]
        p["influential_citation_count"] = row.get("influential_citation_count", 0)

    return cache


def main():
    parser = argparse.ArgumentParser(description="Semantic Scholar 被引数据查询（激活【低影响力】状态）")
    parser.add_argument("--dois", nargs="*", help="要查询的 DOI 列表")
    parser.add_argument("--input", default=None, help="含 papers 的 JSON 文件（补 citation_count 字段）")
    parser.add_argument("--output", default=None, help="结果 JSON 输出路径")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    if args.dois:
        result = lookup_by_dois(args.dois)
        text = json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        print(text)
        return

    if args.input:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
        papers = data.get("papers", data) if isinstance(data, dict) else data
        cache = enrich_papers_with_citations(papers)
        text = json.dumps(data, ensure_ascii=False, indent=2 if args.pretty else None)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            # 顺带把 lookup 缓存写出来，供下次复用
            Path(args.output).with_suffix(".citations.json").write_text(
                json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        print(text)
        return

    parser.print_help()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
