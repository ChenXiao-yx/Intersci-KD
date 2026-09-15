#!/usr/bin/env python3
"""scp_tools.py — SCP 专业数据工具 MCP 网关客户端 CLI（v2 MCP 协议版）。

调用 11 个 SCP 数据工具（10 个 MCP 端点，数量单一事实源见本文件 TOOL_COUNT/ENDPOINT_COUNT）之一，通过 MCP Streamable HTTP 协议返回结构化证据 JSON。
- 真实模式：读取 SCP_HUB_API_KEY + 对应工具 MCP 端点，发起 JSON-RPC 2.0 tools/call。
- 降级模式：Key 缺失或网关不可达 → 返回 per-tool mock 数据，status=mock_fallback。

用法：
    python scripts/scp_tools.py --tool origene-chembl --query "aspirin" --top_k 5 --pretty

架构说明：
    单一通用 API Key：SCP_HUB_API_KEY（所有工具共用）
    每工具独立 MCP 端点：https://scp.intern-ai.org.cn/api/v1/mcp/{id}/{ToolName}
    认证 Header：SCP-HUB-API-KEY
    协议：MCP Streamable HTTP（JSON-RPC 2.0 over HTTP）
"""
import argparse
import json
import os
import re
import sys
import time
from typing import Optional


# ──────────────────────────────────────────────────────────────────────
# 基础配置
# ──────────────────────────────────────────────────────────────────────

BASE_URL = "https://scp.intern-ai.org.cn/api/v1"


def _extract_year(item: dict, *field_names) -> Optional[int]:
    """从字典中尝试多个字段名提取年份，返回 int 或 None。

    API 不返回年份时返回 None，让 score_evidence.calc_decay 走"未提供年份→不衰减"分支，
    而不是硬编码 2024 导致所有论文恒为"近年"计分。
    """
    for field in field_names:
        val = item.get(field) if isinstance(item, dict) else None
        if val is None:
            continue
        try:
            year = int(float(str(val).strip()))
            if 1900 <= year <= 2099:
                return year
        except (ValueError, TypeError):
            continue
    return None


def _extract_year_from_text(text: str, default: Optional[int] = None) -> Optional[int]:
    """从文本中提取 4 位年份（1900-2099）。用于 PubMed 纯文本响应等场景。"""
    m = re.search(r'\b(19\d{2}|20\d{2})\b', text or "")
    return int(m.group(1)) if m else default


# ──────────────────────────────────────────────────────────────────────
# 参数构建器：根据工具类型生成 MCP tools/call 的 arguments
# ──────────────────────────────────────────────────────────────────────

def _args_search(query, top_k, **kwargs):
    """通用文献检索参数构建器 — query + top_k/page_size。"""
    args = {"query": query}
    if top_k is not None:
        if kwargs.get("top_k_param"):
            args[kwargs["top_k_param"]] = min(top_k, kwargs.get("top_k_max", 50))
    if kwargs.get("extra_args"):
        args.update(kwargs["extra_args"])
    return args


def _args_cypher(query, top_k, **kwargs):
    """Neo4j Cypher 查询参数构建器 — SciGraph-Material 专用。支持多 KG 名称回退。"""
    # 先转义反斜杠，再转义单引号，防止 Cypher 注入
    safe_query = query.replace("\\", "\\\\").replace("'", "\\'")
    limit = min(top_k or 10, 100)
    cypher = (
        f"MATCH (n) WHERE n.name CONTAINS '{safe_query}' "
        f"OR n.description CONTAINS '{safe_query}' "
        f"RETURN n LIMIT {limit}"
    )
    kg_name = kwargs.get("kg_name", "Material")
    return {"cypher": cypher, "kg_name": kg_name, "limit": limit}


def _args_drug_search(query, top_k, **kwargs):
    """药物名称检索参数构建器 — FDA 等。"""
    args = {"drug_name": query}
    if top_k:
        args["limit"] = min(top_k, 100)
    return args


def _args_name_search(query, top_k, **kwargs):
    """通用名称检索参数构建器 — PubChem / NCBI 等。"""
    args = {kwargs.get("name_param", "name"): query}
    if top_k and kwargs.get("top_k_param"):
        args[kwargs["top_k_param"]] = min(top_k, kwargs.get("top_k_max", 50))
    return args


def _args_query_str(query, top_k, **kwargs):
    """query_str 参数构建器 — ChEMBL 专用。"""
    return {"query_str": query}


def _args_scholar_kg(query, top_k, **kwargs):
    """Scholar-KG 参数构建器 — query + subject + top_k。"""
    args = {"query": query}
    subject = kwargs.get("subject", "cs")
    valid_subjects = ("arxiv", "biology", "chemistry", "cs", "earth", "material", "physics")
    if subject not in valid_subjects:
        subject = "cs"
    args["subject"] = subject
    if top_k:
        args["top_k"] = min(top_k, 30)
    return args


def _args_opentargets(query, top_k, **kwargs):
    """OpenTargets 参数构建器 — queryString + entityNames + 分页。"""
    return {
        "queryString": query,
        "entityNames": ["target", "disease"],
        "pageIndex": 0,
        "pageSize": min(top_k or 10, 20),
    }


def _args_tcga(query, top_k, **kwargs):
    """TCGA 参数构建器 — 仅 query。"""
    return {"query": query}


# ──────────────────────────────────────────────────────────────────────
# 响应解析器：将不同 MCP 工具的输出归一化为标准 papers[] 格式
# ──────────────────────────────────────────────────────────────────────

def _parse_sciverse_response(text, tool_name="search_papers"):
    """解析 Sciverse search_papers 响应。格式: {"results": [{title, abstract, publication_published_year, doi, source_type, ...}]}"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

    papers = []
    items = []

    if isinstance(data, dict):
        for key in ["results", "papers", "publications", "items", "data"]:
            if key in data and isinstance(data[key], list):
                items = data[key]
                break

    for item in items:
        if not isinstance(item, dict):
            continue
        papers.append({
            "title": item.get("title", ""),
            "abstract": item.get("abstract", ""),
            "year": _extract_year(item, "publication_published_year", "year", "pub_year", "published_year"),
            "doi": item.get("doi", ""),
            "source_type": item.get("source_type", item.get("publication_venue_name_unified", "Academic_paper")),
            "confidence": "high" if item.get("score", 0) > 0.8 else "medium",
            "authors": item.get("author", item.get("authors", "")),
            "journal": item.get("publication_venue_name_unified", item.get("journal", "")),
        })

    return papers if papers else None


def _parse_semantic_search_response(text, tool_name="semantic_search"):
    """解析 Sciverse semantic_search 响应。格式: {"hits": [{abstract, chunk, chunk_id, ...}]}"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

    papers = []
    items = []

    if isinstance(data, dict):
        items = data.get("hits", data.get("chunks", []))
        if isinstance(items, dict):
            items = [items]

    for item in items:
        if not isinstance(item, dict):
            continue
        chunk = item.get("chunk", "")
        chunk_id = item.get("chunk_id", "")
        papers.append({
            "title": chunk[:120] if chunk else "",
            "abstract": chunk,
            "year": _extract_year(item, "year", "publication_year"),
            "doi": chunk_id,
            "source_type": "semantic_search",
            "confidence": "high" if item.get("score", 0) > 0.8 else "medium",
        })

    return papers if papers else None


def _parse_pubmed_text_response(text, tool_name="pubmed_search"):
    """解析 Origene-Search pubmed_search 纯文本响应。

    实际格式：MCP 返回的是 JSON 数组字符串，内部包含 \\n 转义的 PubMed 文本：
        ["1. journal. date;vol:issue. doi: 10.xxxx/xxx\\n\\nArticle Title\\n\\nAuthors..."]
    """
    if not text:
        return None

    # Step 1: Try to decode JSON array wrapper
    try:
        decoded = json.loads(text)
        if isinstance(decoded, list) and decoded:
            # Concatenate all strings in the list
            text = "\n".join(str(item) for item in decoded if isinstance(item, str))
    except (json.JSONDecodeError, TypeError):
        pass

    # Step 2: Unescape \\n to actual newlines
    text = text.replace("\\n", "\n").replace("\\t", "\t")

    papers = []

    blocks = re.split(r'\n(?=\d{1,2}[\.\)])', text)
    if len(blocks) <= 1:
        blocks = [text]

    for block in blocks:
        if not block.strip():
            continue

        title = ""
        abstract = ""
        doi = ""
        pmid = ""
        authors = ""

        lines = block.strip().split('\n')
        if not lines:
            continue

        first_line = lines[0].strip()

        doi_match = re.search(r'doi:\s*(\S+)', first_line, re.IGNORECASE)
        if doi_match:
            doi = doi_match.group(1).rstrip('.')

        pmid_match = re.search(r'PMID:\s*(\d+)', block)
        if pmid_match:
            pmid = pmid_match.group(1)

        title_lines = []
        collecting_title = False
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if i == 0:
                continue
            if not line_stripped:
                if collecting_title:
                    break
                continue
            if re.match(r'^(Authors|Abstract|Background|Methods|Results|Discussion|DOI|PMID)\b[:\s]', line_stripped, re.IGNORECASE):
                break
            if not collecting_title:
                collecting_title = True
            title_lines.append(line_stripped)

        if title_lines:
            title = ' '.join(title_lines)

        if not title:
            for i, line in enumerate(lines):
                line_stripped = line.strip()
                if i == 0:
                    continue
                if line_stripped and not re.match(r'^(Authors|Abstract|Background|Methods|Results|Discussion|DOI|PMID)\b[:\s]', line_stripped, re.IGNORECASE):
                    title = re.sub(r'^\d{1,2}[\.\)]\s*', '', line_stripped)
                    break

        authors_match = re.search(
            r'(?:Authors?)\s*[:\s]+(.+?)(?=\n\s*(?:Abstract|Background|Methods|Results|Discussion|DOI|PMID|$))',
            block, re.DOTALL | re.IGNORECASE
        )
        if authors_match:
            authors = authors_match.group(1).strip()

        abstract_match = re.search(
            r'(?:Abstract|BACKGROUND|Methods|Results|Discussion)\s*[:\s]+(.+?)(?=\n\s*(?:DOI|PMID|$))',
            block, re.DOTALL | re.IGNORECASE
        )
        if abstract_match:
            abstract = abstract_match.group(1).strip()

        if not title and not abstract:
            continue

        papers.append({
            "title": title or f"PubMed entry (PMID: {pmid})",
            "abstract": abstract,
            "year": _extract_year_from_text(first_line),
            "doi": doi,
            "source_type": "PubMed_literature",
            "confidence": "medium",
            "authors": authors,
            "journal": first_line[:120] if first_line else "",
        })

    return papers if papers else None


def _parse_ncbi_response(text, tool_name="get_gene_metadata_by_gene_name"):
    """解析 Origene-NCBI 响应。格式: {"reports": [{"gene": {symbol, description, ...}}]}"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

    papers = []

    if isinstance(data, dict):
        reports = data.get("reports", [])
        if isinstance(reports, dict):
            reports = [reports]

        for report in reports:
            if not isinstance(report, dict):
                continue
            gene = report.get("gene", {})
            if not isinstance(gene, dict):
                gene = report

            symbol = gene.get("symbol", gene.get("gene_symbol", ""))
            description = gene.get("description", gene.get("gene_description", ""))
            if not symbol and not description:
                continue

            papers.append({
                "title": f"{symbol} — {description}" if symbol and description else (symbol or description[:120]),
                "abstract": description,
                "year": _extract_year(gene, "year", "publication_year"),
                "doi": gene.get("doi", gene.get("gene_id", "")),
                "source_type": "NCBI_gene",
                "confidence": "high",
            })

    return papers if papers else None


def _parse_chembl_response(text, tool_name="search_activity"):
    """解析 Origene-ChEMBL 响应。格式: {"activities": [{assay_description, molecule_chembl_id, ...}]}"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

    papers = []

    if isinstance(data, dict):
        items = data.get("activities", data.get("assays", data.get("data", [])))
        if isinstance(items, dict):
            items = [items]

        for item in items:
            if not isinstance(item, dict):
                continue
            display_name = item.get("molecule_name", item.get("molecule_chembl_id", ""))
            assay_desc = item.get("assay_description", "")
            if not display_name and not assay_desc:
                continue
            title_parts = [display_name] if display_name else []
            if assay_desc and assay_desc != display_name:
                title_parts.append(assay_desc)
            title = " — ".join(title_parts) if title_parts else "ChEMBL record"
            papers.append({
                "title": title,
                "abstract": item.get("description", item.get("assay_description", "")),
                "year": _extract_year(item, "year", "publication_year"),
                "doi": item.get("molecule_chembl_id", item.get("chembl_id", "")),
                "source_type": "ChEMBL_activity",
                "confidence": "high",
            })

    return papers if papers else None


def _parse_pubchem_response(text, tool_name="search_pubchem_by_name"):
    """解析 Origene-PubChem 响应。格式: {"PC_Compounds": [{id: {id: {cid}}, atoms, bonds, props, ...}]}"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

    papers = []

    if isinstance(data, dict):
        compounds = data.get("PC_Compounds", [])
        if isinstance(compounds, dict):
            compounds = [compounds]

        for comp in compounds:
            if not isinstance(comp, dict):
                continue

            cid = ""
            id_data = comp.get("id", {})
            if isinstance(id_data, dict):
                id_id = id_data.get("id", {})
                if isinstance(id_id, dict):
                    cid = str(id_id.get("cid", ""))

            formula = ""
            weight = ""
            compound_name = ""
            props = comp.get("props", [])
            if isinstance(props, list):
                for prop in props:
                    if isinstance(prop, dict):
                        label = prop.get("label", "")
                        value = prop.get("value", {})
                        if isinstance(value, dict):
                            if label == "Molecular Formula":
                                formula = value.get("sval", "")
                            elif label == "Molecular Weight":
                                weight = str(value.get("ival", value.get("fval", "")))
                            elif label in ("Compound Title", "IUPAC Name", "Compound Name"):
                                compound_name = value.get("sval", "")

            title = f"Compound CID {cid}" if cid else "PubChem compound"
            if compound_name:
                title += f" ({compound_name})"
            elif formula:
                title += f" ({formula})"

            papers.append({
                "title": title,
                "abstract": f"PubChem compound CID={cid}, Formula={formula}, Weight={weight}",
                "year": _extract_year(comp, "year", "publication_year"),
                "doi": cid,
                "source_type": "PubChem_compound",
                "confidence": "high",
            })

    return papers if papers else None


def _parse_fdadrug_response(text, tool_name="get_active_ingredient_info_by_drug_name"):
    """解析 Origene-FDADrug 响应。格式: {"results": [{"openfda.brand_name": [...], "openfda.generic_name": [...], "active_ingredient": [...]}]}"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

    papers = []

    if isinstance(data, dict):
        results = data.get("results", [])
        if isinstance(results, dict):
            results = [results]

        for item in results:
            if not isinstance(item, dict):
                continue

            brand_name = item.get("openfda.brand_name", [""])
            generic_name = item.get("openfda.generic_name", [""])
            active_ingredient = item.get("active_ingredient", "")

            if isinstance(brand_name, list):
                brand_name = brand_name[0] if brand_name else ""
            if isinstance(generic_name, list):
                generic_name = generic_name[0] if generic_name else ""

            display_name = brand_name or generic_name or active_ingredient or "FDA drug record"

            papers.append({
                "title": str(display_name),
                "abstract": f"Brand: {brand_name}, Generic: {generic_name}, Active Ingredient: {active_ingredient}",
                "year": _extract_year(item, "year", "publication_year"),
                "doi": item.get("application_number", ""),
                "source_type": "FDA_Drug",
                "confidence": "high",
            })

    return papers if papers else None


def _parse_opentargets_response(text, tool_name="multi_entity_search_by_query_string"):
    """解析 Origene-OpenTargets 响应。格式: {"data": {"search": {"hits": [{id, entity, description, name, score}]}}}"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

    papers = []

    if isinstance(data, dict):
        search_data = data.get("data", {})
        if isinstance(search_data, dict):
            search = search_data.get("search", {})
            if isinstance(search, dict):
                hits = search.get("hits", [])
                if isinstance(hits, dict):
                    hits = [hits]

                for hit in hits:
                    if not isinstance(hit, dict):
                        continue

                    name = hit.get("name", "")
                    description = hit.get("description", "")
                    entity = hit.get("entity", "")
                    score = hit.get("score", 0)
                    hit_id = hit.get("id", "")

                    papers.append({
                        "title": str(name or hit_id or "OpenTargets entry"),
                        "abstract": str(description or ""),
                        "year": _extract_year(hit, "year", "publication_year"),
                        "doi": str(hit_id or ""),
                        "source_type": f"OpenTargets_{entity}",
                        "confidence": "high" if score and score > 0.8 else "medium",
                        "match_score": score,
                    })

    return papers if papers else None


def _parse_scigraph_response(text, tool_name="query_cypher"):
    """解析 SciGraph-Material 响应。格式: {"success":true,"kg_name":"Material","count":0,"data":[{"n.name":"...","n.description":"..."}]}

    Cypher 查询返回列名格式的键（如 "n.name", "n.description"），需提取并构建标准 papers。
    当 data 为空且 count=0 时返回 None。若 data 为空，尝试其他候选键。
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict):
        return None

    data_list = data.get("data", None)

    if data_list is None:
        for alt_key in ("results", "nodes", "items", "matches", "records"):
            if alt_key in data and isinstance(data[alt_key], list):
                data_list = data[alt_key]
                break

    if data_list is None:
        return None

    if not isinstance(data_list, list):
        return None

    if len(data_list) == 0:
        return None

    count = data.get("count", None)
    if count is not None and count == 0:
        return None

    papers = []

    for item in data_list:
        if not isinstance(item, dict):
            continue

        name = ""
        description = ""
        cid = ""

        # Handle nested dict values (e.g., {"n": {"name": "Fluorographene"}})
        for key, value in item.items():
            if isinstance(value, dict):
                # Nested dict like {"n": {"name": "...", "description": "..."}}
                nested = value
                name = str(nested.get("name", nested.get("title", "")))
                description = str(nested.get("description", nested.get("summary", "")))
                cid = str(nested.get("id", nested.get("cid", "")))
            elif isinstance(value, str):
                clean_key = key.split(".")[-1] if "." in key else key
                if clean_key == "name" and not name:
                    name = value
                elif clean_key == "description" and not description:
                    description = value
                elif clean_key == "id" and not cid:
                    cid = value

        # Fallback: check for properties sub-dict
        if not name:
            props = item.get("properties", {})
            if isinstance(props, dict):
                name = str(props.get("name", props.get("title", "")))
                description = str(props.get("description", props.get("summary", "")))
                cid = str(props.get("id", ""))

        if not name:
            continue

        papers.append({
            "title": name,
            "abstract": description,
            "year": _extract_year(item, "year", "publication_year"),
            "doi": cid,
            "source_type": "Knowledge_Graph",
            "confidence": "medium",
        })

    return papers if papers else None


def _parse_scholar_response(text, tool_name="query_paper"):
    """解析 Scholar-KG 响应。处理 papers/kg_json 及 LanceDB 未加载错误。"""
    if not text:
        return None

    if "lancedb" in text.lower() and ("not loaded" in text.lower() or "not found" in text.lower()):
        return None

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

    papers = []

    if isinstance(data, dict):
        items = []
        for key in ["output", "papers", "results", "items", "kg_json", "data", "matches"]:
            if key in data and isinstance(data[key], list):
                items = data[key]
                break

        if not items and "data" in data:
            data_val = data["data"]
            if isinstance(data_val, list):
                items = data_val

        for item in items:
            if not isinstance(item, dict):
                continue
            # Scholar-KG specific: paper_title, node_text, matched_node_id
            title = item.get("paper_title", item.get("title", item.get("name", item.get("node_text", ""))))
            if not title:
                continue
            abstract = item.get("abstract", item.get("description", ""))
            if not abstract and "node_text" in item:
                # Extract abstract from node_text which is like "Paper: Title. Details: ..."
                node_text = item.get("node_text", "")
                if "Details:" in node_text:
                    abstract = node_text.split("Details:", 1)[1].strip()[:300]
            papers.append({
                "title": str(title),
                "abstract": str(abstract),
                "year": _extract_year(item, "year", "publication_year"),
                "doi": item.get("doi", item.get("paper_id", item.get("matched_node_id", ""))),
                "source_type": "Scholar_KG",
                "confidence": "medium",
                "match_score": item.get("similarity_score", 0),
            })

    return papers if papers else None


def _parse_generic_response(text, tool_name=""):
    """通用响应解析器 — 尝试从任意 JSON 中提取 papers。"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, dict):
        return None

    papers = []

    def extract_items(obj, depth=0):
        if depth > 3:
            return []
        for key in ["papers", "results", "items", "data", "matches", "list", "hits", "records"]:
            if key in obj and isinstance(obj[key], list) and obj[key]:
                sample = obj[key][0]
                if isinstance(sample, dict) and ("title" in sample or "name" in sample or "abstract" in sample):
                    return obj[key]
        for v in obj.values():
            if isinstance(v, dict):
                sub = extract_items(v, depth + 1)
                if sub:
                    return sub
        return []

    items = extract_items(data)
    for item in items:
        if not isinstance(item, dict):
            continue
        title = item.get("title", item.get("name", item.get("compound_name", item.get("drug_name", ""))))
        if not title:
            continue
        papers.append({
            "title": str(title),
            "abstract": item.get("abstract", item.get("description", "")),
            "year": _extract_year(item, "year", "publication_year"),
            "doi": item.get("doi", item.get("chembl_id", item.get("id", ""))),
            "source_type": item.get("source_type", tool_name or "Database_record"),
            "confidence": "medium",
        })

    return papers if papers else None


# ──────────────────────────────────────────────────────────────────────
# 工具注册表（FINAL — 经实际 API 调用验证）
# 格式: {简化名: (MCP路径, MCP工具名, 领域, 证据类型, 参数构建器, 响应解析器, 额外配置)}
# evidence_type 必须是 evidence_weights.json 的 evidence_weights 段中的标准键，
# 由 call_gateway 的 _inject_standard_type 注入到每篇论文的 type 字段，
# 确保 score_evidence.infer_type 直接命中 EVIDENCE_WEIGHTS 而不走 default_weight(0.3)。
TOOL_REGISTRY = {
    "sciverse": (
        "/mcp/43/Sciverse", "search_papers", "general", "Patent",
        _args_search, _parse_sciverse_response,
        {"top_k_param": "page_size", "top_k_max": 50}
    ),
    "semantic_search": (
        "/mcp/43/Sciverse", "semantic_search", "general", "Journal_article",
        _args_search, _parse_semantic_search_response,
        {"top_k_param": "top_k", "top_k_max": 30}
    ),
    "origene-ncbi": (
        "/mcp/9/Origene-NCBI", "get_gene_metadata_by_gene_name", "biotech", "External_validation",
        _args_name_search, _parse_ncbi_response,
        {"name_param": "name"}
    ),
    "origene-search": (
        "/mcp/7/Origene-Search", "pubmed_search", "general", "Journal_article",
        _args_search, _parse_pubmed_text_response,
        {}
    ),
    "scholar-kg": (
        "/mcp/42/Scholar-KG", "query_paper", "knowledge", "Systematic_review",
        _args_scholar_kg, _parse_scholar_response,
        {"subject": "cs"}
    ),
    "origene-chembl": (
        "/mcp/4/Origene-ChEMBL", "search_activity", "drug", "Journal_article",
        _args_query_str, _parse_chembl_response,
        {}
    ),
    "origene-pubchem": (
        "/mcp/8/Origene-PubChem", "search_pubchem_by_name", "chemistry", "Journal_article",
        _args_name_search, _parse_pubchem_response,
        {"name_param": "name"}
    ),
    "origene-fdadrug": (
        "/mcp/14/Origene-FDADrug", "get_active_ingredient_info_by_drug_name", "regulatory", "FDA_NMPA_approval",
        _args_drug_search, _parse_fdadrug_response,
        {}
    ),
    "origene-opentargets": (
        "/mcp/15/Origene-OpenTargets", "multi_entity_search_by_query_string", "drug", "Meta_analysis",
        _args_opentargets, _parse_opentargets_response,
        {}
    ),
    "origene-tcga": (
        "/mcp/11/Origene-TCGA", "tcga_differential_expression_analysis", "oncology", "External_validation",
        _args_tcga, _parse_generic_response,
        {"allow_mock_fallback": True}
    ),
    "scigraph-material": (
        "/mcp/40/SciGraph-Material", "query_cypher", "material", "Industry_standard",
        _args_cypher, _parse_scigraph_response,
        {}
    ),
}

# Domain → preferred SCP tool mapping
_DOMAIN_TOOL_MAP = {
    "biotech": "origene-ncbi",
    "hardware": "scigraph-material",
    "social": "sciverse",
    "education": "sciverse",
    "business": "sciverse",
    "psychology": "sciverse",
    "AI": "sciverse",
    "drug": "origene-chembl",
    "regulatory": "origene-fdadrug",
    "oncology": "origene-tcga",
    "chemistry": "origene-pubchem",
    "material": "scigraph-material",
    "patent": "sciverse",
    "knowledge": "scholar-kg",
}

# 工具数量单一事实源（P0-3）：所有文档引用此常量，禁止硬编码数字。
# 口径：11 个工具 / 10 个端点（Sciverse 端点提供 search_papers + semantic_search 两个工具）。
TOOL_COUNT = len(TOOL_REGISTRY)
ENDPOINT_COUNT = len({entry[0] for entry in TOOL_REGISTRY.values()})


# ──────────────────────────────────────────────────────────────────────
# Mock 数据生成
# ──────────────────────────────────────────────────────────────────────

def _mock_paper(tool_name: str, evidence_type: str, query: str, rank: int) -> dict:
    """生成单条 per-tool mock 证据。is_mock:true 强制隔离，下游 score_evidence 不计入有效论文。"""
    return {
        "rank": rank,
        "title": f"[{tool_name}] Mock evidence #{rank} for query '{query}'",
        "abstract": "Mock fallback record generated because the MCP API Key was missing or the gateway was unreachable.",
        "year": None,
        "doi": f"10.0000/mock.{tool_name.replace('-', '')}.{rank}",
        "source_type": evidence_type,
        "confidence": "medium",
        "tags": [tool_name, "mock_fallback"],
        "tool": tool_name,
        "is_mock": True,
    }


def build_mock_result(tool_name, query, top_k, warning=None):
    """构造 per-tool mock 返回。"""
    if tool_name not in TOOL_REGISTRY:
        tool_name = "sciverse"
    _, _, domain, evidence_type, _, _, _ = TOOL_REGISTRY[tool_name]
    papers = [_mock_paper(tool_name, evidence_type, query, i) for i in range(1, min(top_k, 3) + 1)]
    result = {
        "status": "mock_fallback",
        "tool": tool_name,
        "query": query,
        "top_k": top_k,
        "domain": domain,
        "evidence_type": evidence_type,
        "count": len(papers),
        "papers": papers,
        "reason": "SCP_HUB_API_KEY not set or MCP gateway unreachable; returning mock data.",
    }
    if warning:
        result["warning"] = warning
    return result


# ──────────────────────────────────────────────────────────────────────
# 安全工具
# ──────────────────────────────────────────────────────────────────────

def _mask_key(api_key):
    """脱敏 API Key。"""
    if not api_key or len(api_key) <= 6:
        return "***"
    return f"{api_key[:3]}***{api_key[-3:]}"


def _classify_error(e, status_code=None):
    """将异常分类为标准错误类型。"""
    if status_code is not None:
        if status_code in (401, 403):
            return "auth_error"
        if status_code == 404:
            return "not_found"
        if 500 <= status_code < 600:
            return "server_error"
    try:
        import requests
        if isinstance(e, requests.Timeout):
            return "timeout"
        if isinstance(e, requests.ConnectionError):
            return "network_error"
    except ImportError:
        pass
    return "unknown"


def _should_retry(error_type):
    """判断错误类型是否可重试。"""
    return error_type in ("server_error", "network_error", "timeout")


# ──────────────────────────────────────────────────────────────────────
# MCP 协议核心
# ──────────────────────────────────────────────────────────────────────

def _mcp_post(url, method, params, req_id, headers, timeout=20):
    """发送 JSON-RPC 2.0 请求到 MCP 端点。"""
    import requests
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    return requests.post(url, json=payload, headers=headers, timeout=timeout)


def _mcp_initialize(endpoint_url, headers):
    """MCP 初始化握手。"""
    import requests
    init_params = {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "intersci-kd", "version": "2.0"}
    }
    try:
        resp = _mcp_post(endpoint_url, "initialize", init_params, 1, headers)
        if resp.status_code == 200:
            return True, resp.json()
        return False, resp.status_code
    except Exception:
        return False, None


def _mcp_tools_call(endpoint_url, mcp_tool_name, arguments, headers):
    """MCP tools/call — 调用指定工具。返回 (status_code, result_dict_or_error)。"""
    import requests
    call_params = {"name": mcp_tool_name, "arguments": arguments}
    try:
        resp = _mcp_post(endpoint_url, "tools/call", call_params, 2, headers)
        if resp.status_code == 200:
            return 200, resp.json()
        elif resp.status_code in (401, 403):
            try:
                body = resp.json()
                msg = body.get("message", resp.text[:200])
            except Exception:
                msg = resp.text[:200]
            return resp.status_code, msg
        elif resp.status_code == 404:
            return 404, resp.text[:200]
        else:
            return resp.status_code, resp.text[:300]
    except requests.Timeout:
        return None, "timeout"
    except requests.ConnectionError:
        return None, "connection_error"
    except Exception as e:
        return None, str(e)


def _extract_text_from_mcp_response(result_dict):
    """从 MCP tools/call 响应中提取 text 内容。"""
    if not isinstance(result_dict, dict):
        return None
    result = result_dict.get("result", {})
    content = result.get("content", [])
    if not isinstance(content, list):
        return None
    texts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            texts.append(item.get("text", ""))
    return "\n".join(texts) if texts else None


def _normalize_mcp_response(text, parser, mcp_tool_name):
    """使用指定解析器将 MCP 响应文本归一化为 papers[]。"""
    if not text:
        return None

    if parser:
        result = parser(text, mcp_tool_name)
        if result:
            return result

    result = _parse_generic_response(text, mcp_tool_name)
    if result:
        return result

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            for key, val in data.items():
                if isinstance(val, list) and val and isinstance(val[0], dict):
                    papers = []
                    for item in val[:10]:
                        papers.append({
                            "title": str(item.get("title", item.get("name", json.dumps(item, ensure_ascii=False)[:80]))),
                            "abstract": str(item.get("abstract", item.get("description", ""))),
                            "year": _extract_year(item, "year", "publication_year"),
                            "doi": item.get("doi", ""),
                            "source_type": "MCP_data",
                            "confidence": "low",
                        })
                    if papers:
                        return papers
    except (json.JSONDecodeError, TypeError):
        pass

    return None


def _inject_standard_type(papers: list[dict], evidence_type: str) -> list[dict]:
    """把工具标准证据类型注入每篇论文的 type 字段。

    优先级：papers 已有的 type > 工具 evidence_type > 不注入（交给 normalize_type）。
    确保 score_evidence.infer_type 直接命中 EVIDENCE_WEIGHTS 标准键，
    避免 SCP 数据库工具（FDA/NCBI/ChEMBL 等）被误判为 Unknown 后按 default_weight(0.3) 计分。
    """
    if not papers:
        return papers
    for p in papers:
        if not p.get("type"):
            p["type"] = evidence_type
    return papers


def call_gateway(tool_name: str, query: str, top_k: int, max_retries: int = 1) -> tuple[Optional[dict], bool, str]:
    """向 SCP MCP 网关发起真实请求。返回 (result_dict, ok_bool, error_type_or_None)。

    使用单一 SCP_HUB_API_KEY 认证，通过 MCP Streamable HTTP 协议调用工具。
    返回格式: {"status": "success", "tool": ..., "papers": [...], ...}
    """
    if tool_name not in TOOL_REGISTRY:
        tool_name = _DOMAIN_TOOL_MAP.get("biotech", "sciverse")

    mcp_path, mcp_tool, domain, evidence_type, arg_builder, parser, extra_cfg = TOOL_REGISTRY[tool_name]

    api_key = os.environ.get("SCP_HUB_API_KEY", "")
    if not api_key:
        return None, False, "auth_error"

    try:
        import requests
    except ImportError:
        print(f"WARNING: 'requests' package not installed; falling back to mock for {tool_name}.", file=sys.stderr)
        return None, False, "unknown"

    endpoint_url = f"{BASE_URL}{mcp_path}"
    headers = {
        "SCP-HUB-API-KEY": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    extra = dict(extra_cfg) if extra_cfg else {}
    arguments = arg_builder(query, top_k, **extra)

    last_error_type = "unknown"
    for attempt in range(max_retries + 1):
        try:
            init_ok, init_resp = _mcp_initialize(endpoint_url, headers)

            status_code, result = _mcp_tools_call(endpoint_url, mcp_tool, arguments, headers)

            if status_code == 200:
                if isinstance(result, dict):
                    resp_result = result.get("result", {})
                    content = resp_result.get("content", [])
                    if content and isinstance(content[0], dict) and content[0].get("isError"):
                        error_text = content[0].get("text", "Unknown tool error")

                        if tool_name == "scholar-kg" and "lancedb" in error_text.lower():
                            print(
                                f"ERROR [lancedb_error]: Scholar-KG backend LanceDB not loaded.\n"
                                f"  Detail: {error_text[:300]}\n"
                                f"  Suggestion: The LanceDB vector database is not available for scholar-kg. "
                                f"Try 'sciverse' or 'semantic_search' instead.",
                                file=sys.stderr
                            )
                        elif tool_name == "origene-tcga" and (
                            "connection refused" in error_text.lower() or "connection" in error_text.lower()
                        ):
                            print(
                                f"ERROR [tcga_backend_down]: TCGA backend is currently unreachable.\n"
                                f"  Detail: {error_text[:300]}\n"
                                f"  Suggestion: The TCGA backend is down. Returning mock with backend-down warning.",
                                file=sys.stderr
                            )
                        else:
                            print(
                                f"ERROR [tool_error]: MCP tool '{mcp_tool}' returned error for {tool_name}.\n"
                                f"  Detail: {error_text[:300]}",
                                file=sys.stderr
                            )
                        return None, False, "client_error"

                text = _extract_text_from_mcp_response(result)
                papers = _normalize_mcp_response(text, parser, mcp_tool)

                if papers:
                    papers = _inject_standard_type(papers, evidence_type)
                    for i, p in enumerate(papers, 1):
                        p["rank"] = i
                        if "match_score" not in p:
                            p["match_score"] = 0

                    data = {
                        "status": "success",
                        "tool": tool_name,
                        "query": query,
                        "top_k": top_k,
                        "domain": domain,
                        "evidence_type": evidence_type,
                        "count": len(papers),
                        "papers": papers,
                    }
                    if attempt > 0:
                        print(f"INFO: MCP retry succeeded for {tool_name} (attempt {attempt + 1}).", file=sys.stderr)
                    return data, True, None
                else:
                    if tool_name == "origene-tcga" and text:
                        if '"status":"error"' in text or '"status": "error"' in text:
                            print(
                                f"ERROR [tcga_backend_down]: TCGA backend returned error response.\n"
                                f"  Detail: {text[:300]}\n"
                                f"  Suggestion: TCGA backend is unreachable. Returning mock with backend-down warning.",
                                file=sys.stderr
                            )
                            mock_result = build_mock_result(
                                tool_name, query, top_k,
                                warning="TCGA backend is currently unreachable. Connection refused."
                            )
                            # ok=False：mock 不当成功；error_type="mock_fallback" 供调用方透传嵌入的 mock
                            return mock_result, False, "mock_fallback"

                    if tool_name == "scigraph-material" and text:
                        for fallback_kg in ["ElementKG", "MatKG"]:
                            extra_fb = dict(extra) if extra else {}
                            extra_fb["kg_name"] = fallback_kg
                            args_fb = arg_builder(query, top_k, **extra_fb)
                            status_code_fb, result_fb = _mcp_tools_call(
                                endpoint_url, mcp_tool, args_fb, headers
                            )
                            if status_code_fb == 200 and isinstance(result_fb, dict):
                                text_fb = _extract_text_from_mcp_response(result_fb)
                                papers_fb = _normalize_mcp_response(text_fb, parser, mcp_tool)
                                if papers_fb:
                                    print(
                                        f"INFO: SciGraph fallback KG '{fallback_kg}' returned {len(papers_fb)} results.",
                                        file=sys.stderr
                                    )
                                    papers_fb = _inject_standard_type(papers_fb, evidence_type)
                                    for i, p in enumerate(papers_fb, 1):
                                        p["rank"] = i
                                        if "match_score" not in p:
                                            p["match_score"] = 0
                                    data = {
                                        "status": "success",
                                        "tool": tool_name,
                                        "query": query,
                                        "top_k": top_k,
                                        "domain": domain,
                                        "evidence_type": evidence_type,
                                        "count": len(papers_fb),
                                        "papers": papers_fb,
                                    }
                                    return data, True, None

                    # 区分「后端返回空结果」与「JSON 解析失败」两种语义。
                    # 空结果（success=true 但 count=0/data=[]）是后端正常响应，不应标 parse_error。
                    is_empty_result = False
                    if text:
                        try:
                            payload = json.loads(text)
                            if isinstance(payload, dict):
                                count_val = payload.get("count", None)
                                data_val = payload.get("data", None)
                                if count_val == 0 or (isinstance(data_val, list) and len(data_val) == 0):
                                    is_empty_result = True
                        except (json.JSONDecodeError, TypeError):
                            pass

                    if is_empty_result:
                        # 后端正常返回但无匹配节点：返回空 papers + empty_result 状态
                        # 不走 mock 兜底，让上层（如 search_papers._try_scp_delegate）
                        # 触发领域 fallback（hardware/material → sciverse 学术文献）
                        print(
                            f"INFO [empty_result]: MCP backend returned no matches for {tool_name}.\n"
                            f"  Tool: {mcp_tool}, Endpoint: {mcp_path}\n"
                            f"  This is a normal empty response, not a parse failure. "
                            f"Caller should try domain fallback (e.g. hardware → sciverse).",
                            file=sys.stderr
                        )
                        empty_data = {
                            "status": "empty_result",
                            "tool": tool_name,
                            "query": query,
                            "top_k": top_k,
                            "domain": domain,
                            "evidence_type": evidence_type,
                            "count": 0,
                            "papers": [],
                        }
                        # ok=False 触发上层 fallback 逻辑；error_type=empty_result 供调用方分流
                        return empty_data, False, "empty_result"

                    print(
                        f"WARNING [parse_error]: MCP call succeeded but response could not be parsed for {tool_name}.\n"
                        f"  Tool: {mcp_tool}, Endpoint: {mcp_path}\n"
                        f"  Falling back to mock data.",
                        file=sys.stderr
                    )
                    return None, False, "client_error"

            elif status_code in (401, 403):
                print(
                    f"ERROR [auth_error]: SCP MCP gateway returned {status_code} for {tool_name}.\n"
                    f"  Message: {str(result)[:300]}\n"
                    f"  API Key (SCP_HUB_API_KEY): {_mask_key(api_key)}\n"
                    f"  Suggestion: Check if the SCP_HUB_API_KEY has expired. "
                    f"Update it in .env with a valid token from the SCP service provider.",
                    file=sys.stderr
                )
                return None, False, "auth_error"

            elif status_code == 404:
                print(
                    f"ERROR [not_found]: MCP endpoint not found for {tool_name}.\n"
                    f"  URL: {endpoint_url}, Tool: {mcp_tool}",
                    file=sys.stderr
                )
                return None, False, "not_found"

            elif status_code is None:
                if result == "timeout":
                    error_type = "timeout"
                elif result == "connection_error":
                    error_type = "network_error"
                else:
                    error_type = "unknown"

                if _should_retry(error_type) and attempt < max_retries:
                    print(
                        f"WARNING [{error_type}]: MCP call for {tool_name} failed (attempt {attempt + 1}/{max_retries + 1}). "
                        f"Retrying in 2s...",
                        file=sys.stderr
                    )
                    time.sleep(2)
                    continue

                if tool_name == "origene-tcga":
                    print(
                        f"WARNING [tcga_backend_down]: TCGA MCP gateway call failed. "
                        f"Returning mock with backend-down warning.",
                        file=sys.stderr
                    )

                print(
                    f"WARNING [{error_type}]: MCP gateway call failed for {tool_name}: {result}. "
                    f"Falling back to mock.",
                    file=sys.stderr
                )
                return None, False, error_type

            else:
                error_type = "server_error" if 500 <= status_code < 600 else "client_error"
                if _should_retry(error_type) and attempt < max_retries:
                    print(
                        f"WARNING [{error_type}]: MCP call for {tool_name} returned {status_code} (attempt {attempt + 1}/{max_retries + 1}). "
                        f"Retrying in 2s...",
                        file=sys.stderr
                    )
                    time.sleep(2)
                    continue

                print(
                    f"WARNING [{error_type}]: MCP gateway call failed for {tool_name}.\n"
                    f"  Status: {status_code}\n"
                    f"  Detail: {str(result)[:200]}\n"
                    f"  Falling back to mock data.",
                    file=sys.stderr
                )
                return None, False, error_type

        except Exception as e:
            error_type = _classify_error(e)
            last_error_type = error_type

            if _should_retry(error_type) and attempt < max_retries:
                print(
                    f"WARNING [{error_type}]: MCP call for {tool_name} failed (attempt {attempt + 1}/{max_retries + 1}). "
                    f"Retrying in 2s...",
                    file=sys.stderr
                )
                time.sleep(2)
                continue

            print(
                f"WARNING [{error_type}]: MCP gateway call failed for {tool_name}: {type(e).__name__}: {str(e)[:200]}. "
                f"Falling back to mock.",
                file=sys.stderr
            )
            return None, False, error_type

    return None, False, last_error_type


# ──────────────────────────────────────────────────────────────────────
# Dotenv 加载
# ──────────────────────────────────────────────────────────────────────

def _load_dotenv():
    """从脚本所在目录及上级目录查找 .env 文件并加载到 os.environ。

    已委托 config_loader.load_dotenv 实现，保留函数名以兼容现有调用点。
    """
    from config_loader import load_dotenv
    load_dotenv()


# ──────────────────────────────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────────────────────────────

def main():
    _load_dotenv()
    # 首次运行引导：检测 SCP_HUB_API_KEY 缺失时交互式引导用户输入
    try:
        from key_setup import ensure_scp_key
        ensure_scp_key()
    except ImportError:
        pass  # key_setup 模块不可用时静默跳过，保持向后兼容
    parser = argparse.ArgumentParser(
        description="SCP 专业数据工具 MCP 网关客户端 — 通过 MCP Streamable HTTP 协议调用 11 个数据工具。",
    )
    parser.add_argument("--tool", type=str, required=True,
                        choices=list(TOOL_REGISTRY.keys()),
                        help="数据工具名")
    parser.add_argument("--query", type=str, required=True, help="检索查询字符串")
    parser.add_argument("--top_k", type=int, default=10, help="返回结果数上限（默认 10）")
    parser.add_argument("--pretty", action="store_true", help="格式化输出 JSON")
    parser.add_argument("--force-real", action="store_true",
                        help="强制使用真实 API，失败时不降级 Mock 而是输出错误并退出")
    args = parser.parse_args()

    if args.top_k <= 0:
        print("ERROR: --top_k must be a positive integer", file=sys.stderr)
        sys.exit(2)

    result, ok, error_type = call_gateway(args.tool, args.query, args.top_k)
    if not ok:
        if args.force_real:
            err_detail = f" (error_type={error_type})" if error_type else ""
            print(f"ERROR: SCP MCP gateway call failed{err_detail}. --force-real active, not falling back to mock.", file=sys.stderr)
            sys.exit(1)

        warning = None
        if args.tool == "origene-tcga" and error_type in ("network_error", "server_error", "client_error"):
            warning = "TCGA backend is currently unreachable; returning mock data as fallback."
        elif args.tool == "scholar-kg" and error_type == "client_error":
            warning = "Scholar-KG LanceDB not loaded; returning mock data as fallback."

        result = build_mock_result(args.tool, args.query, args.top_k, warning=warning)

    if args.pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)