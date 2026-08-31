import argparse
import json
import sys
import os

# 确保能找到同级目录下的 scp_tools 模块
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

# 尝试导入 scp_tools，如果失败则使用兜底方案
try:
    from scp_tools import build_mock_result, _DOMAIN_TOOL_MAP, call_gateway
    _SCP_AVAILABLE = True
except ImportError:
    _SCP_AVAILABLE = False

_SCP_HUB_KEY = "SCP_HUB_API_KEY"


def _generate_fallback_mock(query, top_k):
    """兜底极简 Mock 生成器，仅当 scp_tools 不可用时使用"""
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
            "tags": ["mock"]
        }
        for i in range(1, top_k + 1)
    ]


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
            return papers
        if force_real:
            print(f"ERROR: Real API call failed (error={error_type}) and --force-real is active.", file=sys.stderr)
            sys.exit(1)
        result = build_mock_result(tool_name, query, top_k)
        papers = result.get("papers", [])
        for i, p in enumerate(papers, 1):
            p["rank"] = i
            p["match_score"] = 0
        return papers
    elif _SCP_AVAILABLE:
        tool_name = _DOMAIN_TOOL_MAP.get(domain or "", "origene-search")
        result = build_mock_result(tool_name, query, top_k)
        papers = result.get("papers", [])
        for i, p in enumerate(papers, 1):
            p["rank"] = i
            p["match_score"] = 0
        return papers
    else:
        return _generate_fallback_mock(query, top_k)


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

    if error_type == "auth_error":
        print("WARNING: SCP API token authentication failed. Falling back to mock data. "
              "Update the API Key in .env to use real data.", file=sys.stderr)

    result = build_mock_result(tool_name, query, top_k)
    papers = result.get("papers", [])
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

    已存在的环境变量不会被覆盖（尊重 shell 中的手动设置）。
    使用纯标准库实现，不依赖 python-dotenv。
    """
    from pathlib import Path

    current = Path(__file__).resolve().parent
    for directory in [current] + list(current.parents)[:3]:
        env_path = directory / ".env"
        if env_path.is_file():
            try:
                with open(env_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = value
            except Exception:
                pass
            break


def main():
    _load_dotenv()
    parser = argparse.ArgumentParser(description="Search papers from SCP gateway (mock mode)")
    parser.add_argument("--query", type=str, default=None, help="Search query string")
    parser.add_argument("--top_k", type=int, default=10, help="Number of results to return")
    parser.add_argument("--domain", type=str, default=None,
                        choices=["biotech", "hardware", "social", "education", "business", "psychology", "AI",
                                 "drug", "regulatory", "oncology", "chemistry", "material", "patent", "knowledge"])
    parser.add_argument("--format", type=str, default="json", choices=["json", "md"])
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
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
        if args.format == "md":
            for p in scp_result.get("papers", []):
                print(f"- [**{p.get('year', '')} {p.get('title', '')}**](https://doi.org/{p.get('doi', '')}) · {p.get('source_type', '')} · 置信度 {p.get('confidence', '')}")
            return
        if args.pretty:
            print(json.dumps(scp_result, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(scp_result, ensure_ascii=False))
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
        "papers": papers
    }
    if args.pretty:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
