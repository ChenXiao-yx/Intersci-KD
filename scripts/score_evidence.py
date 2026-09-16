"""InterSci-KD 确定性证据计分器。纯标准库实现，无第三方依赖。用法见 --help。

P1-1 计分签名：每次计分输出含 scored_by / scored_by_version / scored_at 三个字段，
供 validate_output.py 第 21 项验证计分结果确实由本脚本产出（防 LLM 手写绕过）。
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

# 允许从仓库根直接运行（python scripts/score_evidence.py）：自举同目录进 sys.path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from config_loader import get_valid_domains

__version__ = "4.7.1"

# 标准 DOI 正则：10.XXXX/...（XXXX 至少 4 位数字）
# 用于 has_doi 判定，避免把 "DEN180001"、"10.0000/mock" 等非标准编号当 DOI
DOI_PATTERN = re.compile(r'^10\.\d{4,}/')


def _load_config() -> dict:
    """加载证据权重配置。配置文件缺失或损坏时 fail-fast，禁止使用过期硬编码兜底。

    历史教训：硬编码兜底表曾与 evidence_weights.json 漂移 9 个证据类型键
    （如 FDA_NMPA vs FDA_NMPA_approval），配置丢失时 FDA 批准被静默按
    default_weight(0.3) 计分。因此配置缺失一律抛错，由调用方走「脚本失败→
    按 SKILL.md 声明手算」的显式降级路径，而不是静默算错。
    """
    config_path = Path(__file__).parent / "config" / "evidence_weights.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


CONFIG = _load_config()
EVIDENCE_WEIGHTS = CONFIG["evidence_weights"]
DEFAULT_WEIGHT = CONFIG["default_weight"]
CONFIDENCE_MULTIPLIERS = CONFIG["confidence_multipliers"]
DOMAIN_MAP = CONFIG["domain_map"]
# P1-4: 领域特定权重覆盖。按 domain 键覆盖 evidence_weights 的同名键。
DOMAIN_OVERRIDES = CONFIG.get("domain_overrides", {})
# 核心证据门槛：core 层无单条 base_weight≥此值 → 直接判 insufficient。
# 单一事实源为 evidence_weights.json 的 core_evidence_threshold（默认 2.5），
# 不得在代码另立常量，避免重蹈硬编码表与配置漂移的历史问题。
# P1-1：域级阈值覆盖见 _resolve_core_threshold（AI 1.5 / hardware 2.0 / material 2.0）。
CORE_EVIDENCE_THRESHOLD = CONFIG.get("core_evidence_threshold", 2.5)


def _resolve_core_threshold(domain: str) -> float:
    """解析域级 core 门槛：域级阈值优先，回退全局值。

    P1-1：AI/硬件/材料域以会议论文与原型实现为主要证据形态，
    单条基础权重天然低于临床/监管域（AI 会议论文经域覆盖后 1.5、
    硬件原型实现 2.0）；若无域级覆盖，20 篇真实可验证的 AI 会议论文
    仍会永远判 insufficient。域级阈值只降低"是否有一条像样硬证据"
    的判定线，不改变 green/yellow/red 的 8.0/4.0 分界。
    """
    by_domain = CONFIG.get("core_evidence_threshold_by_domain", {})
    domain_key = DOMAIN_MAP.get(domain, domain)
    return float(by_domain.get(domain_key, CORE_EVIDENCE_THRESHOLD))


def resolve_domain(d: str) -> str:
    """将输入 domain 解析为规范 domain。未知 domain 显式报错，禁止静默回落 biotech。"""
    if d in DOMAIN_MAP:
        return DOMAIN_MAP[d]
    raise ValueError(
        f"Unknown domain: {d!r}. Valid domains: {sorted(DOMAIN_MAP.keys())}. "
        f"Either add it to scripts/config/evidence_weights.json domain_map, "
        f"or pass a known --domain."
    )


def infer_type(ev: dict) -> str:
    # 优先使用已规范化的 type 字段（若已是标准键则直接用）
    if "type" in ev and ev["type"] in EVIDENCE_WEIGHTS:
        return ev["type"]
    # 调用归一化层：把 source_type 原始字符串映射到标准证据类型键
    from normalize_type import normalize_type
    ev_type = normalize_type(
        source_type=ev.get("source_type", ""),
        title=ev.get("title", ""),
        abstract=ev.get("abstract", ""),
        doi=ev.get("doi", ""),
    )
    if ev_type != "Unknown":
        return ev_type
    # 兜底：尝试其他字段名
    t = (ev.get("source") or ev.get("category") or ev.get("kind") or "")
    return t if t else "Unknown"


def load_json_str_or_path(s):
    s = s.strip()
    if s.startswith("{") or s.startswith("["):
        return json.loads(s)
    with open(s, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def collect_evidence(args):
    """收集证据。优先级：--single > --input-json > --papers。

    P1-17：明确输入源优先级，避免同时传入多个参数时行为不明确。
    """
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
        with open(args.input_json, "r", encoding="utf-8-sig") as f:
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


def calc_decay(year: object, cy: int) -> tuple[float, str]:
    # bool 是 int 子类，视为无效年份；None 同样无效
    if isinstance(year, bool) or year is None:
        return 1.0, "year_type_invalid, no_decay_applied"
    # year=0 表示无年份，不衰减
    if year == 0:
        return 1.0, "year_is_zero, no_decay_applied"
    # 容忍数字型字符串（如 "2022"）和 float（如 2026.0），统一强转 int
    if isinstance(year, str):
        try:
            year = int(float(year.strip()))
        except (ValueError, TypeError):
            return 1.0, "year_type_mismatch, no_decay_applied"
    elif isinstance(year, float):
        try:
            year = int(year)
        except (ValueError, TypeError):
            return 1.0, "year_type_float_uncastable, no_decay_applied"
    elif not isinstance(year, int):
        return 1.0, "year_type_unknown, no_decay_applied"
    years_old = cy - year
    if years_old > 5:
        df = max(0.3, 1.0 - (years_old - 5) * 0.05)
        return df, f"years_old={years_old}, linear_decay_applied"
    return 1.0, ""


def score_evidence(evidence_list: list[dict], domain: str, current_year: int) -> dict:
    detailed = []
    total = 0.0
    total_core = 0.0  # 仅 core 的加权分累计（等级判定用）
    total_supplemental = 0.0  # supplemental 加权分累计（审计用）
    valid_count = 0  # 有效证据数（非 mock + 非 duplicate + 非 doi 格式错误 + 可验证）
    core_count = 0  # core 层条目数
    supplemental_count = 0  # supplemental 层条目数
    reference_count = 0  # reference 层条目数
    unverifiable_count = 0  # 无法验证的文献数（缺 DOI 或缺年份）
    duplicate_count = 0  # 重复 DOI 条目数（is_duplicate==True）
    doi_format_error_count = 0  # DOI 格式错误条目数（doi_format_error==True）
    max_base_weight = 0.0  # 单条最大基础权重（含 supplemental，审计用）
    max_base_weight_core = 0.0  # 仅 core 的单条最大基础权重（核心证据门槛用）
    for idx, ev in enumerate(evidence_list, 1):
        ev_type = infer_type(ev)
        confidence = ev.get("confidence", "medium")
        year = ev.get("year")
        title = ev.get("title", ev.get("description", ""))
        doi = ev.get("doi", "")
        # P1-4: 领域特定权重覆盖。优先使用 domain_overrides 中的权重，
        # 回退到 evidence_weights 默认值，最后回退 default_weight。
        domain_key = DOMAIN_MAP.get(domain, domain)
        domain_weights = DOMAIN_OVERRIDES.get(domain_key, {})
        base_weight = domain_weights.get(
            ev_type, EVIDENCE_WEIGHTS.get(ev_type, DEFAULT_WEIGHT)
        )
        # P0-3：标注权重来源，供审计时区分全局权重与域级覆盖
        weight_source = (
            f"domain_override:{domain_key}" if ev_type in domain_weights else "global"
        )
        multiplier = CONFIDENCE_MULTIPLIERS.get(confidence, 0.5)
        wac = base_weight * multiplier
        decay_factor, note = calc_decay(year, current_year)
        weight = round(wac * decay_factor, 2)
        total += weight
        # mock 强隔离：is_mock=true 的条目不计入有效证据
        is_mock = bool(ev.get("is_mock", False))
        # 预印本识别：显式标记 / "arxiv:" 伪 DOI / arxiv.org 来源 / DataCite 形式 10.48550/arXiv.xxx
        # 预印本未同行评审：状态"待核验"、不计有效论文、不进 core（见 output-template.md 枚举说明）
        doi_lc = str(doi).lower()
        is_preprint = (
            bool(ev.get("is_preprint", False))
            or doi_lc.startswith("arxiv:")
            or "arxiv.org" in str(ev.get("source", "")).lower()
            or "10.48550/arxiv" in doi_lc
        )
        # 重复 DOI 标记：is_duplicate=true 的条目不计入有效证据
        is_duplicate = bool(ev.get("is_duplicate", False))
        # DOI 格式错误标记：doi_format_error=true 的条目不计入有效证据
        doi_format_error = bool(ev.get("doi_format_error", False))
        # 未来年份标记：year > current_year 时标"待核验"，不计入有效证据
        # 解决问题：2026 年会议论文被当"有效"但会议可能尚未召开
        # 支持 int / float / 数字型字符串，统一强转后比较
        is_future_year = False
        year_int = None
        if isinstance(year, bool):
            year_int = None  # bool 不当年份
        elif isinstance(year, int):
            year_int = year
        elif isinstance(year, float):
            try:
                year_int = int(year)
            except (ValueError, TypeError):
                year_int = None
        elif isinstance(year, str):
            try:
                year_int = int(float(year.strip()))
            except (ValueError, TypeError):
                year_int = None
        if year_int is not None and year_int > current_year:
            is_future_year = True
        if is_duplicate:
            duplicate_count += 1
        if doi_format_error:
            doi_format_error_count += 1
        # 监管批准识别（用于 has_doi 特殊放行）
        ev_type_str = str(ev_type)
        is_regulatory_approval = (
            ev_type_str == "FDA_NMPA_approval"
            or ev_type_str.startswith("FDA_NMPA_approval")
            or ev_type_str == "CE_mark"
            or ev_type_str.startswith("CE_mark")
        )
        # 有效性判定：有 DOI + 有年份 + 非未来年份 → 可验证
        # has_doi 需匹配标准 DOI 正则（10.XXXX/...），避免把 "DEN180001" 当 DOI
        has_doi = bool(
            doi and doi.strip()
            and not doi.startswith("10.0000/mock")
            and DOI_PATTERN.match(doi.strip())
        )
        # 监管批准特殊放行：官方文件编号（如 DEN180001、510k 编号）不是标准 DOI 但同样有效
        if is_regulatory_approval and doi and doi.strip():
            has_doi = True
        has_year = bool(year and str(year).strip() not in ("", "0", "None"))
        validity_status = "有效" if (has_doi and has_year and not is_future_year) else "无法验证"
        is_verifiable = (validity_status == "有效")
        # 状态优先级：mock > duplicate > doi_format_error > 未来年份 > 监管批准 > 缺 DOI/年份
        if is_mock:
            validity_status = "mock_fallback"
        elif is_duplicate:
            validity_status = "duplicate_doi"
        elif doi_format_error:
            validity_status = "doi_format_error"
        elif is_future_year:
            validity_status = "待核验"
            unverifiable_count += 1
        elif is_preprint:
            # 预印本（含 arXiv DataCite DOI）：非同行评审，标"待核验"，不计有效论文
            validity_status = "待核验"
        elif is_regulatory_approval:
            # 监管批准（FDA/NMPA 批准、CE mark）单独标注，与普通"有效"文献区分
            # 仍计入 valid_count：has_doi 已特殊放行为 True，is_verifiable=True
            validity_status = "监管批准"
        elif not is_verifiable:
            validity_status = "无法验证"
            unverifiable_count += 1
        # 有效证据 = 非 mock + 非 duplicate + 非 doi 格式错误 + 非未来年份 + 非预印本 + 可验证
        if not is_mock and not is_duplicate and not doi_format_error and not is_future_year and not is_preprint and is_verifiable:
            valid_count += 1
        if base_weight > max_base_weight:
            max_base_weight = base_weight
        # 计分明细四字段（供第十章"计分明细"子表逐项复现）：
        #   base_weight   = 基础权重（来自 EVIDENCE_WEIGHTS 的值）
        #   confidence    = 置信度标签（high/medium/low，向后兼容；数值倍率见 multiplier）
        #   multiplier    = 置信度倍率（1.0/0.5/0.25，即公式中的 confidence 数值）
        #   decay_factor  = 衰减因子（基于年份，≤5年=1.0，>5年线性衰减）
        #   weighted_score= 加权分 = base_weight × multiplier × decay_factor
        # 证据分层 tier：
        #   - core: 同行评审原始研究/综述/监管批准，有 DOI + 有年份 + 非 mock + 非 duplicate + 非格式错误 + 非未来年份 + 非预印本
        #   - supplemental: 非批准类监管文件 / 预印本 / 待核验条目（DOI 未核验或未来年份）
        #   - reference: 缺 DOI 或缺年份的纯参考条目（不计入任何有效计数）
        # 分层用途：等级判定只看 core 的 total_score；supplemental 仅展示计分供审计
        # 监管批准（FDA_NMPA_approval、CE_mark）是硬证据，进 core；其他监管文件（警告、召回）进 supplemental
        # ev_type_str / is_regulatory_approval 已在 has_doi 段计算
        is_regulatory_other = (
            (ev_type_str.startswith("FDA_NMPA") and not is_regulatory_approval)
            or ev_type_str.startswith("Regulatory")
        )
        is_supplemental_type = (
            is_regulatory_other  # 非批准类监管文件
            or is_preprint  # arXiv 等预印本（含 10.48550/arXiv.xxx DataCite DOI）
        )
        if is_mock or is_duplicate or doi_format_error or is_future_year:
            tier = "supplemental"  # 待核验/未来年份归入补充证据
        elif is_supplemental_type:
            tier = "supplemental"  # 监管文件/预印本归入补充证据
        elif not is_verifiable:
            tier = "reference"  # 缺 DOI 或缺年份的纯参考
        else:
            tier = "core"
        # tier 分层累计（用于等级判定）
        if tier == "core":
            total_core += weight
            max_base_weight_core = max(max_base_weight_core, base_weight)
            core_count += 1
        elif tier == "supplemental":
            total_supplemental += weight
            supplemental_count += 1
        else:
            reference_count += 1
        item = {
            "id": idx, "type": ev_type, "confidence": confidence,
            "base_weight": base_weight, "multiplier": multiplier,
            "weight_source": weight_source,  # P0-3：global 或 domain_override:<域>
            "decay_factor": round(decay_factor, 2), "weight": weight,
            "score": weight, "weighted_score": weight,  # 加权分=base_weight×multiplier×decay_factor，与 weight 同值
            "year": year, "description": title, "note": note,
            "is_mock": is_mock, "doi": doi, "validity_status": validity_status,
            "is_duplicate": is_duplicate, "doi_format_error": doi_format_error,
            "is_future_year": is_future_year,
            "tier": tier,  # 新增分层字段
        }
        detailed.append(item)
    # total_score 仍按原口径（含 supplemental）展示供审计
    total_score = round(total, 2)
    # total_core 是仅 core 的加权分，用于等级判定
    total_core = round(total_core, 2)
    total_supplemental = round(total_supplemental, 2)
    core_threshold = _resolve_core_threshold(domain)
    threshold_note = ""
    # 核心证据门槛：core 里无单条 base_weight≥有效门槛（域级优先）→ 直接判定证据不足
    # 不再"算高分再降级"，而是直接 insufficient
    if max_base_weight_core < core_threshold:
        level, emoji = "insufficient", "⚪"
        threshold_note = (
            f"insufficient: no core evidence (max_core_base_weight={max_base_weight_core}"
            f"<{core_threshold}), cannot give directional conclusion"
        )
    elif total_core >= 8.0:
        level, emoji = "green", "🟢"
    elif total_core >= 4.0:
        level, emoji = "yellow", "🟡"
    else:
        level, emoji = "red", "🔴"
    # 注意：重复 DOI / 格式错误计数通过独立字段 duplicate_count /
    # doi_format_error_count 输出，绝不写入 threshold_note。
    # threshold_note 仅承载 insufficient 说明；消费方（validate_output）以
    # "非空即 yellow 降级" 的历史语义读取本字段，混入审计计数会把 green 误杀。
    # 规则2：有效论文为0（含全 mock + 全无法验证 + 全 duplicate + 全 doi 格式错误）→ 标志降级
    rule2_triggered = (valid_count == 0 and len(evidence_list) > 0)
    return {
        "total_score": total_score,  # 含 supplemental 的全量合计（审计用）
        "total_core": total_core,  # 仅 core 的加权分（等级判定用）
        "total_supplemental": total_supplemental,  # supplemental 的合计（审计用）
        "level": level, "level_emoji": emoji,
        "domain": domain, "source_count": len(evidence_list),
        # P1-1 计分签名：证明本结果由 score_evidence.py 产出（第 21 项校验依据）
        "scored_by": "score_evidence.py",
        "scored_by_version": __version__,
        "scored_at": datetime.now().isoformat(timespec="seconds"),
        "valid_evidence_count": valid_count,
        "core_evidence_count": core_count,
        "supplemental_evidence_count": supplemental_count,
        "reference_evidence_count": reference_count,
        "unverifiable_count": unverifiable_count,
        "duplicate_count": duplicate_count,
        "doi_format_error_count": doi_format_error_count,
        "max_single_base_weight": round(max_base_weight, 2),
        "max_core_base_weight": round(max_base_weight_core, 2),
        "core_evidence_threshold": core_threshold,
        "rule2_triggered": rule2_triggered,
        "threshold_note": threshold_note,
        "weight_breakdown": "see references/evidence-rubric.md §1",
        "detailed_scores": detailed,
    }


def main():
    parser = argparse.ArgumentParser(
        description="InterSci-KD 确定性证据计分器",
        epilog=(
            "输入源优先级：--single > --input-json > --papers（同时传入多个时按此优先级取第一个）。\n"
            "Windows/PowerShell 提示：命令行内联 JSON（--single）易因引号转义损坏，"
            "建议优先使用 --input-json 文件方式：将证据写入临时 JSON 文件后传入路径。\n"
            "示例：python score_evidence.py --input-json papers.json --domain hardware\n"
            "          python score_evidence.py --input-json papers.json --output score.json --pretty"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--papers", action="append", default=[],
                        help="JSON字符串或文件路径（优先级最低）")
    parser.add_argument("--single", action="append", default=None,
                        help="单条证据JSON字符串，可多次（优先级最高）")
    parser.add_argument("--input-json", default=None,
                        help="输入JSON文件路径（优先级中）")
    parser.add_argument("--domain", default="biotech",
                        choices=get_valid_domains())
    parser.add_argument("--current_year", type=int, default=datetime.now().year)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--output", type=str, default=None,
                        help="Output file path (writes directly, avoids shell redirection)")
    args = parser.parse_args()
    try:
        domain = resolve_domain(args.domain)
        ev_list = collect_evidence(args)
        result = score_evidence(ev_list, domain, args.current_year)
        indent = 2 if args.pretty else None
        text = json.dumps(result, ensure_ascii=False, indent=indent)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            print(f"OK: wrote {len(text)} bytes to {args.output}")
        else:
            print(text)
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
