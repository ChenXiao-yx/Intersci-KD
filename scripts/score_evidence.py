"""InterSci-KD 确定性证据计分器。纯标准库实现，无第三方依赖。用法见 --help。"""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime


def _load_config():
    """加载证据权重配置，JSON 文件缺失时使用兜底硬编码。"""
    config_path = Path(__file__).parent / "config" / "evidence_weights.json"
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        # 兜底硬编码（仅当配置文件丢失时使用，确保脚本不会崩溃）
        return {
            "evidence_weights": {
                "FDA_NMPA": 5.0, "CE_mark": 5.0, "RCT": 5.0,
                "Meta_analysis": 2.5, "Industry_standard": 3.0, "Patent": 3.0,
                "NCBI_database": 2.5, "Systematic_review": 2.0,
                "ChEMBL_compound": 2.0, "PubMed_literature": 2.0,
                "Prototype_implementation": 1.5, "Literature_review": 1.5,
                "Algorithm_benchmark": 1.0, "Animal_experiment": 1.0,
                "Case_study": 1.0, "In_vitro_study": 1.0,
                "Simulation": 0.5, "Expert_opinion": 0.5, "News_report": 0.5
            },
            "default_weight": 0.3,
            "confidence_multipliers": {"high": 1.0, "medium": 0.5, "low": 0.25},
            "domain_map": {
                "education": "social", "psychology": "social",
                "default": "biotech", "biotech": "biotech",
                "social": "social", "business": "business",
            }
        }


CONFIG = _load_config()
EVIDENCE_WEIGHTS = CONFIG["evidence_weights"]
DEFAULT_WEIGHT = CONFIG["default_weight"]
CONFIDENCE_MULTIPLIERS = CONFIG["confidence_multipliers"]
DOMAIN_MAP = CONFIG["domain_map"]


def resolve_domain(d):
    return DOMAIN_MAP.get(d, "biotech")


def infer_type(ev):
    if "type" in ev:
        return ev["type"]
    if "source_type" in ev:
        return ev["source_type"]
    t = (ev.get("source") or ev.get("category") or ev.get("kind") or "")
    return t if t else "Unknown"


def load_json_str_or_path(s):
    s = s.strip()
    if s.startswith("{") or s.startswith("["):
        return json.loads(s)
    with open(s, "r", encoding="utf-8") as f:
        return json.load(f)


def collect_evidence(args):
    if args.single:
        out = []
        for s in args.single:
            obj = json.loads(s)
            if isinstance(obj, list):
                out.extend(obj)
            else:
                out.append(obj)
        return out
    if args.input_json:
        with open(args.input_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            if "papers" in data and isinstance(data["papers"], list):
                arr = data["papers"]
            elif "evidence_sources" in data and isinstance(data["evidence_sources"], list):
                arr = data["evidence_sources"]
            else:
                arr = [data]
        else:
            arr = data if isinstance(data, list) else []
        return arr
    if args.papers:
        out = []
        for p in args.papers:
            obj = load_json_str_or_path(p)
            if isinstance(obj, list):
                out.extend(obj)
            elif isinstance(obj, dict):
                if "papers" in obj and isinstance(obj["papers"], list):
                    out.extend(obj["papers"])
                else:
                    out.append(obj)
        return out
    return []


def calc_decay(year, cy):
    # bool 是 int 子类，视为无效年份；None 同样无效
    if isinstance(year, bool) or year is None:
        return 1.0, "year_type_invalid, no_decay_applied"
    # 容忍数字型字符串（如 "2022"），强转后正常衰减
    if isinstance(year, str):
        try:
            year = int(year.strip())
        except (ValueError, TypeError):
            return 1.0, "year_type_mismatch, no_decay_applied"
    elif not isinstance(year, int):
        return 1.0, "year_type_unknown, no_decay_applied"
    years_old = cy - year
    if years_old > 5:
        df = max(0.3, 1.0 - (years_old - 5) * 0.05)
        return df, f"years_old={years_old}, linear_decay_applied"
    return 1.0, ""


def score_evidence(evidence_list, domain, current_year):
    detailed = []
    total = 0.0
    for idx, ev in enumerate(evidence_list, 1):
        ev_type = infer_type(ev)
        confidence = ev.get("confidence", "medium")
        year = ev.get("year")
        title = ev.get("title", ev.get("description", ""))
        base_weight = EVIDENCE_WEIGHTS.get(ev_type, DEFAULT_WEIGHT)
        multiplier = CONFIDENCE_MULTIPLIERS.get(confidence, 0.5)
        wac = base_weight * multiplier
        decay_factor, note = calc_decay(year, current_year)
        weight = round(wac * decay_factor, 2)
        total += weight
        item = {
            "id": idx, "type": ev_type, "confidence": confidence,
            "base_weight": base_weight, "multiplier": multiplier,
            "decay_factor": round(decay_factor, 2), "weight": weight,
            "score": weight, "year": year, "description": title, "note": note,
        }
        detailed.append(item)
    total_score = round(total, 2)
    if total_score >= 8.0:
        level, emoji = "green", "🟢"
    elif total_score >= 4.0:
        level, emoji = "yellow", "🟡"
    else:
        level, emoji = "red", "🔴"
    return {
        "total_score": total_score, "level": level, "level_emoji": emoji,
        "domain": domain, "source_count": len(evidence_list),
        "weight_breakdown": "see references/evidence-rubric.md §1",
        "detailed_scores": detailed,
    }


def main():
    parser = argparse.ArgumentParser(description="InterSci-KD 确定性证据计分器")
    parser.add_argument("--papers", action="append", default=[], help="JSON字符串或文件路径")
    parser.add_argument("--single", action="append", default=None, help="单条证据JSON字符串（可多次）")
    parser.add_argument("--input-json", default=None, help="输入JSON文件路径")
    parser.add_argument("--domain", default="biotech",
                        choices=["biotech", "social", "education", "psychology", "business", "default",
                                 "hardware", "AI", "drug", "regulatory", "oncology", "chemistry",
                                 "material", "patent", "knowledge"])
    parser.add_argument("--current_year", type=int, default=datetime.now().year)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    try:
        domain = resolve_domain(args.domain)
        ev_list = collect_evidence(args)
        result = score_evidence(ev_list, domain, args.current_year)
        indent = 2 if args.pretty else None
        print(json.dumps(result, ensure_ascii=False, indent=indent))
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
