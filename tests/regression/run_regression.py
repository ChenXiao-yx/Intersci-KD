#!/usr/bin/env python3
"""InterSci-KD 端到端回归 + 规则遵守率度量（P2-1）。

对 tasks.json 中每个任务执行确定性链路并输出度量：
- kind=output_validation：读交付样本 + 可选 score.json → validate_output.run_all →
  收集各校验项通过状态，统计每项通过率。
- kind=score_check：读证据 fixture → score_evidence → 与 expect 字段比对
  （level / valid_evidence_count / max_core_base_weight / core_evidence_threshold）。

输出：
- 每任务结果（hard_failures / 期望比对）；
- 全局"校验项通过率"（仅统计该项实际执行的样本，warning 计为通过）；
- 低于 min_pass_rate（默认 0.8）的校验项清单——按方案，此类规则应
  "优先考虑删除该规则或改为脚本兜底"，而不是继续加提示词。

用法：
    python tests/regression/run_regression.py --baseline tests/regression/baseline.json
    python tests/regression/run_regression.py --update-baseline   # 以当前结果重写基线

退出码：0=所有任务通过且无遵守率回退；1=有硬失败/期望不符/低于阈值/低于基线。

说明：真实 LLM 生成无法在脚本内复现，rewrite_count 以"硬失败的检查项数"计
（每项至少需要一轮重写）；LLM 会话级遵守率埋点留待真实运行数据接入。
当前基线是"理想输入→理想输出"的自证结果（全 1.0 属必然），其价值在于
守护交付样本回归、并为将来接入真实 LLM 生成循环提供对照基线。
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import validate_output as vo  # noqa: E402
from score_evidence import score_evidence  # noqa: E402

REG_DIR = Path(__file__).resolve().parent


def _resolve(rel: str) -> Path:
    """把 tasks.json 中的相对路径解析到仓库根。"""
    p = Path(rel)
    return p if p.is_absolute() else _ROOT / p


def run_output_task(task: dict) -> dict:
    text = _resolve(task["output"]).read_text(encoding="utf-8")
    score_json = None
    if task.get("score"):
        score_json = json.loads(_resolve(task["score"]).read_text(encoding="utf-8"))
    results, fails = vo.run_all(text, score_json=score_json, level=task["level"])

    checks = {}
    for name, ok, _detail in results:
        num = name.split(".")[0]
        try:
            num_i = int(num)
        except ValueError:
            continue
        if ok is None:
            checks[num_i] = "skipped"
        elif ok == "warning":
            checks[num_i] = "warning"
        else:
            checks[num_i] = bool(ok)
    return {
        "task": task["name"],
        "id": task["id"],
        "level": task["level"],
        "hard_failures": fails,
        # 离线度量：硬失败的检查项数（每项至少需一轮重写）
        "rewrite_count": sum(1 for v in checks.values() if v is False),
        "checks": checks,
    }


def run_score_task(task: dict, current_year: int) -> dict:
    papers = json.loads(_resolve(task["papers"]).read_text(encoding="utf-8"))
    result = score_evidence(papers, task["domain"], current_year)
    mismatches = []
    for key, expected in task.get("expect", {}).items():
        actual = result.get(key)
        if isinstance(expected, float):
            ok = actual is not None and abs(float(actual) - expected) < 1e-6
        else:
            ok = actual == expected
        if not ok:
            mismatches.append(f"{key}: expect={expected!r} actual={actual!r}")
    return {
        "task": task["name"],
        "id": task["id"],
        "domain": task["domain"],
        "hard_failures": len(mismatches),
        "rewrite_count": len(mismatches),
        "mismatches": mismatches,
        "actual": {k: result.get(k) for k in task.get("expect", {})},
    }


def aggregate_check_pass_rate(task_results: list) -> dict:
    """按校验项编号聚合通过率：仅统计该项实际执行的样本；warning 计为通过。"""
    stats: dict[int, dict[str, int]] = {}
    for tr in task_results:
        for num, state in tr.get("checks", {}).items():
            s = stats.setdefault(num, {"pass": 0, "fail": 0})
            if state is True or state == "warning":
                s["pass"] += 1
            elif state is False:
                s["fail"] += 1
            # skipped 不计入分母
    rates = {}
    for num in sorted(stats):
        total = stats[num]["pass"] + stats[num]["fail"]
        if total:
            rates[str(num)] = round(stats[num]["pass"] / total, 4)
    return rates


def main() -> int:
    parser = argparse.ArgumentParser(description="InterSci-KD 端到端回归 + 遵守率度量")
    parser.add_argument("--baseline", default=None, help="基线文件路径（比对遵守率回退）")
    parser.add_argument("--update-baseline", action="store_true", help="以当前结果重写基线")
    parser.add_argument("--output", default=None, help="报告 JSON 输出路径（默认仅 stdout）")
    args = parser.parse_args()

    tasks_doc = json.loads((REG_DIR / "tasks.json").read_text(encoding="utf-8"))
    current_year = tasks_doc.get("current_year", 2026)
    min_pass_rate = float(tasks_doc.get("min_pass_rate", 0.8))

    task_results = []
    for task in tasks_doc["tasks"]:
        if task["kind"] == "output_validation":
            task_results.append(run_output_task(task))
        elif task["kind"] == "score_check":
            task_results.append(run_score_task(task, current_year))
        else:
            task_results.append({"task": task["name"], "id": task["id"],
                                 "hard_failures": 0, "rewrite_count": 0,
                                 "mismatches": [f"未知任务类型: {task['kind']}"]})

    rates = aggregate_check_pass_rate(task_results)
    below_threshold = [k for k, v in rates.items() if v < min_pass_rate]

    # 基线比对：某项通过率低于基线 → 视为遵守率回退
    baseline = None
    regressions = []
    if args.baseline and Path(args.baseline).exists():
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        base_rates = baseline.get("check_pass_rate", {})
        regressions = [
            f"{k}: baseline={base_rates[k]}, current={rates.get(k)}"
            for k in base_rates
            if rates.get(k, 0) < base_rates[k] - 1e-9
        ]

    report = {
        "generated": str(date.today()),
        "current_year": current_year,
        "min_pass_rate": min_pass_rate,
        "check_pass_rate": rates,
        "_comment": "当前版本各校验项通过率基线。由 run_regression.py --update-baseline 生成；低于 min_pass_rate 的规则应优先删除或改为脚本兜底。",
        "task_results": task_results,
        "below_threshold_checks": below_threshold,
        "baseline_regressions": regressions,
    }

    if args.update_baseline:
        baseline_doc = {
            "generated": report["generated"],
            "current_year": current_year,
            "min_pass_rate": min_pass_rate,
            "check_pass_rate": rates,
            "_comment": report["_comment"],
        }
        Path(REG_DIR / "baseline.json").write_text(
            json.dumps(baseline_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"baseline written to {REG_DIR / 'baseline.json'}", file=sys.stderr)

    out_json = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(out_json, encoding="utf-8")
    print(out_json)

    # 人类可读摘要
    print("── 回归摘要 ─────────────────────────────────", file=sys.stderr)
    for tr in task_results:
        status = "PASS" if tr["hard_failures"] == 0 else "FAIL"
        extra = ""
        if "mismatches" in tr and tr["mismatches"]:
            extra = " | " + "; ".join(tr["mismatches"][:3])
        print(f"[{status}] {tr['task']} (hard_failures={tr['hard_failures']}"
              f", rewrite_count={tr['rewrite_count']}){extra}", file=sys.stderr)
    print(f"校验项通过率: {rates}", file=sys.stderr)
    if below_threshold:
        print(f"⚠ 低于 {min_pass_rate:.0%} 的规则清单（优先考虑删除该规则或改为脚本兜底）: "
              f"{below_threshold}", file=sys.stderr)
    if regressions:
        print(f"⚠ 相对基线回退: {regressions}", file=sys.stderr)

    any_fail = any(tr["hard_failures"] > 0 for tr in task_results)
    return 1 if (any_fail or below_threshold or regressions) else 0


if __name__ == "__main__":
    sys.exit(main())
