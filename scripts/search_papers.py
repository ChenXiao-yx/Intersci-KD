from __future__ import annotations
import argparse
import json
import re
import sys
import os
from datetime import datetime
from pathlib import Path

# 确保能找到同级目录下的 scp_tools 模块
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from config_loader import get_valid_domains, load_dotenv

# 尝试导入 scp_tools，如果失败则使用兜底方案
try:
    from scp_tools import build_mock_result, _DOMAIN_TOOL_MAP, call_gateway
    _SCP_AVAILABLE = True
except ImportError:
    _SCP_AVAILABLE = False

_SCP_HUB_KEY = "SCP_HUB_API_KEY"


def _generate_fallback_mock(query, top_k):
    """兜底极简 Mock 生成器，仅当 scp_tools 不可用时使用。is_mock:true 强制隔离。"""
    return [
        {
            "rank": i,
            "match_score": 0,
            "title": f"Mock Paper {i} for '{query}'",
            "abstract": "This is a fallback mock abstract.",
            "year": 2023,
            "doi": f"10.0000/mock.{i}",
            "source_type": "Expert_opinion",
            "confidence": "low",
            "tags": ["mock"],
            "is_mock": True,
        }
        for i in range(1, top_k + 1)
    ]


def _output_json(data, args):
    """Output JSON to stdout or file (--output avoids shell redirection)."""
    text = json.dumps(data, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"OK: wrote {len(text)} bytes to {args.output}")
    else:
        print(text)


def _handle_empty_result_fallback(tool_name, query, top_k, domain):
    """empty_result 时尝试领域 fallback。返回 papers 列表或 None。

    P1-8：提取 search 与 _try_scp_delegate 共用的 fallback 逻辑，避免代码重复。
    """
    if domain not in ("hardware", "material"):
        return None
    print(
        f"INFO [domain_fallback]: {tool_name} returned empty for domain '{domain}'. "
        f"Retrying with 'sciverse' (academic literature) for broader coverage.",
        file=sys.stderr
    )
    fb_result, fb_ok, fb_err = call_gateway("sciverse", query, top_k)
    if fb_ok and fb_result:
        papers = fb_result.get("papers", [])
        for i, p in enumerate(papers, 1):
            p["rank"] = i
            if "match_score" not in p:
                p["match_score"] = 0
        return _enrich_papers(papers)
    print(
        f"WARNING [domain_fallback_failed]: sciverse fallback also failed (err={fb_err}).",
        file=sys.stderr
    )
    return None


def search(query, top_k, domain, force_real=False):
    """优先使用真实 API，失败时降级 Mock。"""
    if _SCP_AVAILABLE and os.environ.get(_SCP_HUB_KEY):
        tool_name = _DOMAIN_TOOL_MAP.get(domain or "", "origene-search")
        result, ok, error_type = call_gateway(tool_name, query, top_k)
        if ok and result:
            papers = result.get("papers", [])
            for i, p in enumerate(papers, 1):
                p["rank"] = i
                if "match_score" not in p:
                    p["match_score"] = 0
            return _enrich_papers(papers)
        if force_real:
            print(f"ERROR: Real API call failed (error={error_type}) and --force-real is active.", file=sys.stderr)
            sys.exit(1)
        # empty_result：后端正常返回但无匹配节点，触发领域 fallback（hardware/material → sciverse）
        # 不走 mock 兜底，避免把假数据当真实文献计入计分
        if error_type == "empty_result":
            fb_papers = _handle_empty_result_fallback(tool_name, query, top_k, domain)
            if fb_papers is not None:
                return fb_papers
        # 第六点评 P1（解 SCP 单点依赖）：任何走向 mock 的失败路径，先试 Crossref
        # 真实检索——mock 数据对真实研究没有价值，能拿到真文献就不给假数据。
        try:
            from providers.base import search_fallback
            xr_papers, xr_name = search_fallback(query, top_k, domain)
            if xr_papers:
                print(f"INFO [provider_fallback]: 已用 {xr_name} 返回真实检索结果（SCP 不可用）。", file=sys.stderr)
                for i, p in enumerate(xr_papers, 1):
                    p["rank"] = i
                return _enrich_papers(xr_papers)
        except Exception as e:  # noqa: BLE001 — provider 失败继续走 mock
            print(f"WARNING: provider fallback failed ({type(e).__name__}: {e})", file=sys.stderr)
        result = build_mock_result(tool_name, query, top_k)
        papers = result.get("papers", [])
        for i, p in enumerate(papers, 1):
            p["rank"] = i
            p["match_score"] = 0
        return _enrich_papers(papers)
    elif _SCP_AVAILABLE:
        tool_name = _DOMAIN_TOOL_MAP.get(domain or "", "origene-search")
        result = build_mock_result(tool_name, query, top_k)
        papers = result.get("papers", [])
        for i, p in enumerate(papers, 1):
            p["rank"] = i
            p["match_score"] = 0
        return _enrich_papers(papers)
    else:
        return _enrich_papers(_generate_fallback_mock(query, top_k))


def _validate_doi_format(doi: str) -> tuple[str, bool]:
    """检测并修正 DOI 的双层前缀问题。

    部分数据源会返回形如 `10.1145/10.1145/3644116.3644178` 的 DOI（前缀重复）。
    本函数检测此类异常，去掉第二个前缀，返回修正后的 DOI 和是否发生修正的标志。

    参数:
        doi: 原始 DOI 字符串，可能为空。

    返回:
        (corrected_doi, format_error)
        - 空 DOI 直接返回原值，format_error=False
        - 命中双层前缀模式 `^10.\\d+/10.\\d+/` 时修正为单层前缀，format_error=True
        - 否则原样返回，format_error=False
    """
    # 空 DOI 不做处理
    if not doi:
        return doi, False
    # 匹配双层前缀，如 10.1145/10.1145/，捕获第一个前缀用于回填
    match = re.match(r"^(10\.\d+/)10\.\d+/", doi)
    if match:
        # 用第一层前缀 + 去掉第二层前缀后的剩余部分
        corrected = match.group(1) + doi[match.end():]
        return corrected, True
    return doi, False


def _dedup_dois(papers: list[dict]) -> list[dict]:
    """按 DOI 去重：标记重复出现的 paper，但不从列表中移除。

    规则:
    - 首次出现的 DOI：保持原 rank，不设 is_duplicate
    - 之后再次出现相同 DOI 的 paper：设 is_duplicate=True，但仍保留在列表中
    - 空 DOI 不参与去重判定（避免误伤无 DOI 的条目）

    参数:
        papers: paper dict 列表，原地修改 is_duplicate 字段并返回。

    返回:
        原列表（已就地标记 is_duplicate）。
    """
    seen = set()
    for p in papers:
        doi = (p.get("doi") or "").strip()
        # 空 DOI 跳过去重判定
        if not doi:
            # 未命中重复时也明确置 False，避免后续逻辑误判为缺失
            p.setdefault("is_duplicate", False)
            continue
        if doi in seen:
            p["is_duplicate"] = True
        else:
            seen.add(doi)
            p.setdefault("is_duplicate", False)
    return papers


def _enrich_papers(papers):
    """后处理：补 type 字段（调用 normalize_type）+ 重算 confidence（基于年份）。

    解决问题：
    - search_papers.py 返回的 JSON 无 type 字段，score_evidence.py 全 fallback 0.3
    - confidence 硬编码 medium，无依据

    本函数还会：
    - 调用 _validate_doi_format 修正 DOI 双层前缀，若 format_error 则标记 doi_format_error=True
    - 调用 _dedup_dois 标记重复 DOI（is_duplicate=True，但仍保留在列表中）
    """
    try:
        from normalize_type import normalize_type
    except ImportError:
        # 归一化层不可用时仍需执行 DOI 修正与去重
        normalize_type = None

    # Step 1: 先修正 DOI 双层前缀（在 type 归一化与去重之前）
    for p in papers:
        doi = p.get("doi", "")
        if doi:
            corrected, format_error = _validate_doi_format(doi)
            p["doi"] = corrected
            if format_error:
                p["doi_format_error"] = True

    # Step 2: 修正后按 DOI 去重标记
    _dedup_dois(papers)

    # 年份基准与 score_evidence.py 保持一致：动态取系统当前年份，
    # 硬编码会在跨年时把论文年龄算小，导致 confidence 虚高、计分失真
    current_year = datetime.now().year
    for p in papers:
        # 补 type 字段（若未规范化或不在标准键中）
        if normalize_type is not None and ("type" not in p or not p.get("type")):
            p["type"] = normalize_type(
                source_type=p.get("source_type", ""),
                title=p.get("title", ""),
                abstract=p.get("abstract", ""),
                doi=p.get("doi", ""),
            )
        # 重算 confidence（基于年份，不覆盖 mock 的 low）
        if p.get("is_mock"):
            p["confidence"] = "low"
            continue
        year = p.get("year")
        if isinstance(year, (int, float)) and year > 0:
            age = current_year - int(year)
            if age <= 2:
                p["confidence"] = "high"
            elif age <= 6:
                p["confidence"] = "medium"
            else:
                p["confidence"] = "low"
        elif not p.get("confidence"):
            p["confidence"] = "medium"

    # Step 3（第三轮评估②）：补被引数据，激活 validity_states 的【低影响力】枚举。
    # 仅对非 mock 且已带 DOI 的条目查 Semantic Scholar；失败静默跳过（
    # 保持"citation_count 缺失 → 状态【无法验证】"的既有兑底语义，不阻塞检索）。
    try:
        from citation_lookup import enrich_papers_with_citations
        enrich_papers_with_citations([p for p in papers if not p.get("is_mock")])
    except Exception as e:  # noqa: BLE001 — 被引属增强数据，任何失败都不阻塞检索主链路
        print(f"WARNING: citation enrichment skipped ({type(e).__name__}: {e})", file=sys.stderr)
    return papers


# Domain → preferred SCP tool mapping (imported from scp_tools)


def _try_scp_delegate(query, top_k, domain, force_real=False):
    """当检测到 SCP_HUB_API_KEY 时，委托 scp_tools.py 按领域选最相关工具调用。

    返回适配后的 result dict（含 status/papers），或 None 表示无 Key → 走本地 mock。
    当 force_real=True 时，API 失败直接报错退出，不降级 Mock。
    """
    if not os.environ.get(_SCP_HUB_KEY):
        return None

    tool_name = _DOMAIN_TOOL_MAP.get(domain or "", "origene-search")

    if not _SCP_AVAILABLE:
        print("WARNING: scp_tools.py not available for delegation; using local mock.", file=sys.stderr)
        return None

    result, ok, error_type = call_gateway(tool_name, query, top_k)
    if ok:
        papers = result.get("papers", [])
        papers = _enrich_papers(papers)  # 后处理：补 type 字段 + 重算 confidence
        return {
            "status": result.get("status", "success"),
            "query": query,
            "top_k": top_k,
            "domain": domain,
            "count": len(papers),
            "papers": papers,
            "source": f"scp_tools:{tool_name}",
        }

    if force_real:
        print(f"ERROR: Real API call failed (error={error_type}) and --force-real is active.", file=sys.stderr)
        sys.exit(1)

    # empty_result（后端正常返回但无匹配节点）：触发领域 fallback，不再降级 mock
    # SciGraph-Material 是材料图谱，对生物医学/传感器查询常返回空；
    # hardware/material 域 fallback 到 sciverse（学术文献），覆盖更广
    # P1-8：复用 _handle_empty_result_fallback 避免代码重复
    if error_type == "empty_result":
        fb_papers = _handle_empty_result_fallback(tool_name, query, top_k, domain)
        if fb_papers is not None:
            return {
                "status": "success",
                "query": query,
                "top_k": top_k,
                "domain": domain,
                "count": len(fb_papers),
                "papers": fb_papers,
                "source": f"scp_tools:sciverse (fallback from {tool_name})",
            }

    # 第六点评 P1（解 SCP 单点依赖）：所有将产生 mock 的失败路径（network/auth/server），
    # 透传 mock 前先试 Crossref 真实检索——mock 数据对真实研究没有价值，能拿到真文献就不给假数据。
    try:
        from providers.base import search_fallback
        xr_papers, xr_name = search_fallback(query, top_k, domain)
        if xr_papers:
            print(f"INFO [provider_fallback]: SCP 失败（{error_type}），已用 {xr_name} 返回真实检索结果。",
                  file=sys.stderr)
            for i, p in enumerate(xr_papers, 1):
                p["rank"] = i
            return {
                "status": "success",
                "query": query,
                "top_k": top_k,
                "domain": domain,
                "count": len(xr_papers),
                "papers": xr_papers,
                "source": f"providers:{xr_name} (fallback from {tool_name})",
            }
    except Exception as e:  # noqa: BLE001 — provider 失败继续走 mock 透传
        print(f"WARNING: provider fallback failed ({type(e).__name__}: {e})", file=sys.stderr)

    # error_type=="mock_fallback"：call_gateway 已嵌入带警告的 mock（如 TCGA 后端不可达），透传保留上下文
    if error_type == "mock_fallback" and result is not None:
        papers = result.get("papers", [])
        papers = _enrich_papers(papers)  # 后处理：补 type 字段 + 重算 confidence
        return {
            "status": result.get("status", "mock_fallback"),
            "query": query,
            "top_k": top_k,
            "domain": domain,
            "count": len(papers),
            "papers": papers,
            "source": f"scp_tools:{tool_name}",
        }

    if error_type == "auth_error":
        print("WARNING: SCP API token authentication failed. Falling back to mock data. "
              "Update the API Key in .env to use real data.", file=sys.stderr)

    result = build_mock_result(tool_name, query, top_k)
    papers = result.get("papers", [])
    papers = _enrich_papers(papers)  # 后处理：补 type 字段 + 重算 confidence
    return {
        "status": result.get("status", "mock_fallback"),
        "query": query,
        "top_k": top_k,
        "domain": domain,
        "count": len(papers),
        "papers": papers,
        "source": f"scp_tools:{tool_name}",
    }


def _load_dotenv():
    """从脚本所在目录及上级目录查找 .env 文件并加载到 os.environ。

    已委托 config_loader.load_dotenv 实现，保留函数名以兼容现有调用点。
    """
    load_dotenv()


def _need_supplemental_search(papers: list[dict]) -> bool:
    """判断是否需要补检系统综述/RCT/监管文件。

    触发条件（满足任一即补检）：
    - 所有论文都是 Journal_article / Conference_paper 类型（无 Systematic_review/RCT/监管批准）
    - 无任何论文标题含 systematic review / meta-analysis / RCT / randomized / FDA / NMPA / CE mark
    - 检索结果以 AI 算法研究领域为主时尤其中（这类领域会议论文多但临床证据稀缺）

    返回 True/False。
    """
    if not papers:
        return False
    # 类型检查：若已含高等级证据类型，无需补检
    # FDA_NMPA_approval = normalize_type/配置的标准键；FDA_NMPA 保留以兼容
    # scp_tools 工具层 mock 路径写入的 source_type
    high_rank_types = {
        "Systematic_review", "Meta_analysis", "RCT",
        "FDA_NMPA_approval", "FDA_NMPA", "CE_mark",
    }
    for p in papers:
        if p.get("type") in high_rank_types or p.get("source_type") in high_rank_types:
            return False
    # 标题关键词检查：若已含系统综述/RCT/监管关键词，无需补检
    keywords = (
        "systematic review", "meta-analysis", "meta analysis",
        "randomized", "rct", "controlled trial",
        "fda", "nmpa", "ce mark", "regulatory",
        "external validation", "real-world",
    )
    for p in papers:
        title_lower = (p.get("title") or "").lower()
        if any(k in title_lower for k in keywords):
            return False
    # 全是会议/期刊论文，且无上述关键词 → 需补检
    return True


def _run_supplemental_search(query, domain, top_k):
    """补检系统综述/RCT/监管文件。返回补充 papers 列表。

    当 _need_supplemental_search 返回 True 时调用，自动追加一轮检索，
    覆盖系统综述/Meta 分析/RCT/FDA 批准/临床指南等高权重证据类型。
    """
    supplemental_queries = [
        f"{query} systematic review",
        f"{query} meta-analysis",
        f"{query} randomized controlled trial",
        f"{query} FDA approval",
        f"{query} clinical guideline",
    ]
    extra_papers = []
    for q in supplemental_queries:
        tool_name = _DOMAIN_TOOL_MAP.get(domain or "", "origene-search")
        result, ok, _ = call_gateway(tool_name, q, min(top_k, 5))
        if ok and result:
            extra_papers.extend(result.get("papers", []))
    return _enrich_papers(extra_papers) if extra_papers else []


def _build_search_audit(query: str, domain: str, papers: list[dict]) -> dict:
    """构建检索审计字段，记录检索式、数据库、时间范围、去重策略等元信息。

    用于 L2/L3 审计简报的"检索审计"段，让用户能追溯本次检索的边界与去重逻辑。
    所有字段名使用 snake_case，与脚本其余输出保持一致。

    参数:
        query: 检索式（来自 args.query）。
        domain: 领域标识（来自 args.domain，用于推断常用学术数据库）。
        papers: 检索+去重后的论文列表（含 is_duplicate 标记）。

    返回:
        search_audit dict，包含 query/database/time_range/dedup_strategy/
        filter_flow/total_raw/total_after_dedup 七个字段。
    """
    # 数据库推断：根据 domain 映射到该领域常用的学术数据库
    if domain == "AI":
        database = "IEEE Xplore/ACM Digital Library"
    elif domain == "biotech":
        database = "PubMed/Crossref"
    else:
        database = "Crossref/OpenAlex"

    # 时间范围：从 papers 的 year 字段动态计算实际范围，无有效年份时默认 2020-2026
    years = [
        p.get("year")
        for p in papers
        if isinstance(p.get("year"), (int, float)) and p.get("year") > 0
    ]
    if years:
        time_range = f"{int(min(years))}-{int(max(years))}"
    else:
        time_range = "2020-2026"

    # 去重后有效数：is_duplicate 为 False 的条目数（未参与去重判定的也计为有效）
    total_after_dedup = sum(1 for p in papers if not p.get("is_duplicate", False))

    return {
        "query": query,
        "database": database,
        "time_range": time_range,
        "dedup_strategy": "DOI 精确匹配去重（重复标记 is_duplicate，不计入有效）",
        "filter_flow": "检索→DOI 格式校验→DOI 去重→type 归一化→confidence 计算",
        "total_raw": len(papers),
        "total_after_dedup": total_after_dedup,
    }


def main():
    _load_dotenv()
    # 首次运行引导：检测 SCP_HUB_API_KEY 缺失时交互式引导用户输入
    try:
        from key_setup import ensure_scp_key
        ensure_scp_key()
    except ImportError:
        pass  # key_setup 模块不可用时静默跳过，保持向后兼容
    parser = argparse.ArgumentParser(description="Search papers from SCP gateway (mock mode)")
    parser.add_argument("--query", type=str, default=None, help="Search query string")
    parser.add_argument("--top_k", type=int, default=10, help="Number of results to return")
    parser.add_argument("--domain", type=str, default=None,
                        choices=get_valid_domains())
    parser.add_argument("--format", type=str, default="json", choices=["json", "md"])
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    parser.add_argument("--output", type=str, default=None,
                        help="Output file path (writes directly, avoids shell redirection)")
    parser.add_argument("--force-real", action="store_true",
                        help="Force real API calls; exit with error on failure instead of falling back to mock")
    args = parser.parse_args()

    if not args.query or not args.query.strip():
        parser.print_usage(sys.stderr)
        print("ERROR: --query is required and cannot be empty", file=sys.stderr)
        sys.exit(2)

    if args.top_k <= 0:
        print("ERROR: --top_k must be a positive integer", file=sys.stderr)
        sys.exit(2)

    # 若任一 SCP 工具 Key 存在，委托 scp_tools.py 按领域选最相关工具调用
    scp_result = _try_scp_delegate(args.query, args.top_k, args.domain, force_real=args.force_real)
    if scp_result is not None:
        # 注入检索审计字段（L2/L3 简报"检索审计"段的数据来源）
        scp_result["search_audit"] = _build_search_audit(
            args.query, args.domain, scp_result.get("papers", [])
        )
        # 补检标记：若全是会议/期刊论文，提示 LLM 工作流补一轮 WebSearch
        scp_result["supplemental_needed"] = _need_supplemental_search(
            scp_result.get("papers", [])
        )
        # 自动补检：若检测结果全是会议/期刊论文且 SCP Key 可用，
        # 自动追加一轮检索（系统综述/Meta/RCT/FDA/临床指南），避免高权重证据永远缺失
        if scp_result.get("supplemental_needed") and os.environ.get(_SCP_HUB_KEY):
            print("INFO: 检测到全是会议/期刊论文，自动补检系统综述/RCT/监管文件...",
                  file=sys.stderr)
            extra = _run_supplemental_search(args.query, args.domain, args.top_k)
            if extra:
                # 合并去重：按 DOI 去重，已有 DOI 的跳过
                existing_dois = {p.get("doi") for p in scp_result["papers"] if p.get("doi")}
                for p in extra:
                    if p.get("doi") and p["doi"] in existing_dois:
                        continue
                    scp_result["papers"].append(p)
                # 重排序
                for i, p in enumerate(scp_result["papers"], 1):
                    p["rank"] = i
                scp_result["count"] = len(scp_result["papers"])
                # 重建检索审计
                scp_result["search_audit"] = _build_search_audit(
                    args.query, args.domain, scp_result["papers"]
                )
                # 重新评估补检需求
                scp_result["supplemental_needed"] = _need_supplemental_search(
                    scp_result["papers"]
                )
                print(f"INFO: 补检完成，新增 {len(extra)} 条，总计 {scp_result['count']} 条。",
                      file=sys.stderr)
        if args.format == "md":
            for p in scp_result.get("papers", []):
                print(f"- [**{p.get('year', '')} {p.get('title', '')}**](https://doi.org/{p.get('doi', '')}) · {p.get('source_type', '')} · 置信度 {p.get('confidence', '')}")
            return
        _output_json(scp_result, args)
        return

    try:
        papers = search(args.query, args.top_k, args.domain, force_real=args.force_real)
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    if args.format == "md":
        for p in papers:
            print(f"- [**{p['year']} {p['title']}**](https://doi.org/{p['doi']}) · {p['source_type']} · 置信度 {p['confidence']}")
        return

    out = {
        "status": "success",
        "query": args.query,
        "top_k": args.top_k,
        "domain": args.domain,
        "count": len(papers),
        "papers": papers,
        # 检索审计字段：L2/L3 简报"检索审计"段的数据来源
        "search_audit": _build_search_audit(args.query, args.domain, papers),
        # 补检标记：若全是会议/期刊论文，提示 LLM 工作流补一轮 WebSearch
        # 触发后 LLM 应检索：系统综述/Meta/RCT/FDA/CE/外部验证/真实世界
        "supplemental_needed": _need_supplemental_search(papers),
    }
    _output_json(out, args)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
