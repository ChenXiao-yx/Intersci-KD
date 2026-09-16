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
from __future__ import annotations
import argparse
import json
import os
import sys
import time
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


def run_freeform_task(task: dict, reg_dir: Path) -> dict:
    """llm_freeform 任务（P1-2）：从 freeform_samples/ 读 LLM 自由生成结果并跑校验。

    与 output_validation（黄金样本自证基线）不同，本任务测的是真实 LLM 遵守率信号：
    - 样本不存在 → status=pending，不阻塞回归（等待真实运行数据接入）；
    - 样本存在 → 跑全量校验，统计各检查项通过率，供 freeform_baseline 对比。
    """
    sample_path = reg_dir / task.get("sample_path", f"freeform_samples/{task['id']}.md")
    if not sample_path.exists():
        return {
            "task": task["name"], "id": task["id"], "level": task.get("level"),
            "kind": "llm_freeform", "status": "pending",
            "hard_failures": 0, "rewrite_count": 0, "checks": {},
            "note": f"待提供 LLM 自由生成样本：{sample_path}",
        }
    text = sample_path.read_text(encoding="utf-8")
    results, fails = vo.run_all(text, score_json=None, level=task["level"])
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
    # 第五点评建议 1：内容质量分（启发式粗筛；LLM judge 可用时为真评审）
    quality = _content_quality(text)
    return {
        "task": task["name"], "id": task["id"], "level": task["level"],
        "kind": "llm_freeform", "status": "measured",
        "hard_failures": fails,
        "rewrite_count": sum(1 for v in checks.values() if v is False),
        "checks": checks,
        "content_quality": ({"overall": quality["overall"], "mode": quality["mode"]}
                            if quality else None),
    }


# ─── 第三轮评估①：真实 LLM 回归循环（--live）───
# 与 freeform（读已归档样本）不同，--live 现场调用 LLM 生成 → 立即校验 → 统计真实遵守率。
# 这是"低于 80% 即裁剪规则"减法机制的真实数据源。


def _content_quality(text: str):
    """内容质量分（第五点评建议 1）：quality_judge 启发式；失败返回 None 不阻塞回归。"""
    try:
        _SCRIPTS = str(_ROOT / "scripts")
        if _SCRIPTS not in sys.path:
            sys.path.insert(0, _SCRIPTS)
        from quality_judge import judge
        q = judge(text, prefer_llm=False)
        return {"overall": q["overall"], "mode": q["mode"]}
    except Exception:  # noqa: BLE001
        return None


def _llm_chat(prompt: str, max_tokens: int = 4096, temperature: float = 0.3) -> str:
    """调用 .env 配置的 OpenAI 兼容后端生成文本。

    后端优先级：LLM_BACKEND 指定 → INTERNLM → COMPETITION → OPENAI（任意兼容端点兜底）。
    生成纪律：temperature 压低到 0.3，减少随机性对遵守率度量的干扰。
    """
    _SCRIPTS = str(_ROOT / "scripts")
    if _SCRIPTS not in sys.path:
        sys.path.insert(0, _SCRIPTS)
    from config_loader import load_dotenv
    load_dotenv()

    import requests

    candidates = []
    backend = os.environ.get("LLM_BACKEND", "")
    if os.environ.get("INTERNLM_API_KEY"):
        candidates.append(("internlm", os.environ["INTERNLM_BASE_URL"],
                           os.environ["INTERNLM_API_KEY"], os.environ.get("INTERNLM_MODEL", "internlm3-latest")))
    if os.environ.get("COMPETITION_API_KEY"):
        candidates.append(("competition", os.environ.get("COMPETITION_BASE_URL", ""),
                           os.environ["COMPETITION_API_KEY"], os.environ.get("COMPETITION_MODEL", "")))
    # 通用 OpenAI 兼容端点兜底（第六点评 P0 路径 A）：DeepSeek/Moonshot/本地 vLLM/Ollama 均可
    # Ollama 原生 /api/chat 适配（第八点评 P4）：无鉴权、响应结构不同。
    # 若 OLLAMA_BASE_URL 以 /v1 结尾会自然走 OpenAI 兼容路径，但 OPENAI_API_KEY 缺失时
    # 不建 OPENAI 候选，因此这里单独兜底原生端点；模型默认 qwen2.5:7b 可用 OLLAMA_MODEL 覆盖。
    _ollama_base = (os.environ.get("OLLAMA_BASE_URL") or os.environ.get("OLLAMA_HOST") or "").rstrip("/")
    if _ollama_base and not _ollama_base.endswith("/v1"):
        candidates.append(("ollama", _ollama_base, "ollama",
                           os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")))
    if os.environ.get("OPENAI_API_KEY"):
        candidates.append(("openai", os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                           os.environ["OPENAI_API_KEY"], os.environ.get("OPENAI_MODEL", "gpt-4o-mini")))
    if backend:
        candidates.sort(key=lambda c: 0 if c[0] == backend else 1)
    if not candidates:
        raise RuntimeError("无可用 LLM 后端：请在 .env 配置 INTERNLM_API_KEY 或 COMPETITION_API_KEY")

    last_err = None
    for name, base_url, api_key, model in candidates:
        if not base_url or not api_key:
            continue
        try:
            if name == "ollama":
                resp = requests.post(
                    f"{base_url}/api/chat",
                    json={"model": model, "stream": False, "temperature": temperature,
                          "messages": [{"role": "user", "content": prompt}]},
                    timeout=180,
                )
                resp.raise_for_status()
                return resp.json()["message"]["content"]
            resp = requests.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "temperature": temperature, "max_tokens": max_tokens,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=180,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:  # noqa: BLE001 — 换下一个后端
            last_err = f"{name}: {type(e).__name__}: {e}"
    raise RuntimeError(f"所有 LLM 后端调用失败：{last_err}")


def _build_live_prompt(task: dict) -> str:
    """构造 live 生成 prompt：指向仓库根的 SKILL.md，要求按档位规则生成。"""
    level = task["level"]
    level_desc = {
        "L0": "仅输出 L0 卡片（30 秒决策卡片，结论先行+定位问题+证据分数+最大不确定性+下一步，结尾给展开选项），不要输出其他档位",
        "L1": "输出 L1 精简五块（一句话判断/在解决什么/现在做到哪/下一步怎么验证/结论+坦诚）",
        "L2": "输出 L2 完整十章审计（第零章至第十章，每章判断带标签，含检索审计段与计分明细子表）",
    }[level]
    skill_path = Path(_ROOT) / "SKILL.md"
    template_path = Path(_ROOT) / "references" / "output-template.md"
    return (
        f"你是 InterSci-KD 跨学科知识蒸馏引擎。请严格按 {skill_path} "
        f"与 {template_path} 的规则执行蒸馏任务。\n\n"
        f"任务主题：{task['prompt']}\n"
        f"输出要求：{level_desc}\n\n"
        f"硬性纪律：证据锚定（无检索能力时用模拟数据并声明 is_mock，或按无证据路径处理）；"
        f"结论三选一（优先整合/持续追踪/暂时搁置）；每句判断带【确证】/【推断】/【无法判断】标签；"
        f"末尾原样附加规定格式的免责声明；禁止出现任何内部术语（脚本名/档位代号/规则编号）。"
    )


def _decide_exit_code(task_results: list, live_results: list,
                      below_threshold: list, regressions: list,
                      allow_llm_error: bool = False) -> int:
    """退出码判定（第五轮 P0-3 抽出的纯函数，可单测）。

    规则：
    - 离线任务有硬失败 / 低于阈值项 / 基线回退 → 1；
    - live 任务 llm_error（基础设施失败）→ 1，除非 allow_llm_error；
    - live 的 LLM 违规（hard_failures）是交付物，不影响退出码。
    """
    any_fail = any(tr["hard_failures"] > 0 for tr in task_results)
    live_llm_error = any(tr.get("status") == "llm_error" for tr in live_results)
    if live_llm_error and allow_llm_error:
        print("注意: --live-allow-llm-error 生效，后端不可达不置退出码 1", file=sys.stderr)
        live_llm_error = False
    return 1 if (any_fail or below_threshold or regressions or live_llm_error) else 0


def run_live_task(task: dict, out_dir: Path, rounds: int = 1) -> dict:
    """--live 任务：现场调用 LLM 生成 → 保存原始输出 → 立即校验。

    rounds>1 时对同一任务多次采样（遵守率统计更稳）；原始输出按
    live_runs/{task_id}_r{n}.md 落盘供复查（这是真实证据，不是黄金样本）。
    """
    task_id = task["id"]
    level = task["level"]
    prompt = _build_live_prompt(task)
    rounds_results = []
    for n in range(1, rounds + 1):
        try:
            text = _llm_chat(prompt)
        except Exception as e:  # noqa: BLE001 — LLM 失败记录后继续，不阻塞其他任务
            rounds_results.append({"round": n, "status": "llm_error",
                                   "note": str(e)[:200], "checks": {}})
            continue
        out_path = out_dir / f"{task_id}_r{n}.md"
        header = f"<!-- live run: task={task_id} level={level} round={n} date={date.today()} -->\n\n"
        out_path.write_text(header + text, encoding="utf-8")
        results, fails = vo.run_all(text, score_json=None, level=level)
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
        quality = _content_quality(text)
        rounds_results.append({"round": n, "status": "measured", "output": str(out_path),
                               "hard_failures": fails,
                               "rewrite_count": sum(1 for v in checks.values() if v is False),
                               "checks": checks,
                               "content_quality": ({"overall": quality["overall"], "mode": quality["mode"]}
                                                   if quality else None)})
        time.sleep(1)  # 限速礼貌间隔

    measured = [r for r in rounds_results if r["status"] == "measured"]
    # 多轮合并：任一轮该项实际执行且为 False 即计 fail（保守口径），仅当所有轮次通过才计 pass
    merged_checks: dict[int, str] = {}
    for num in sorted({int(k) for r in measured for k in r["checks"]}): 
        states = [r["checks"].get(num) for r in measured if num in r["checks"]]
        if any(s is False for s in states):
            merged_checks[num] = False
        elif all(s in (True, "warning", "skipped") for s in states):
            merged_checks[num] = True if any(s is True for s in states) else "skipped"
    return {
        "task": task["name"], "id": task_id, "level": level, "kind": "live",
        "status": "measured" if measured else "llm_error",
        "rounds": len(measured), "llm_errors": len(rounds_results) - len(measured),
        "hard_failures": sum(r["hard_failures"] for r in measured),
        "rewrite_count": sum(r["rewrite_count"] for r in measured),
        "checks": merged_checks,
        "round_details": rounds_results,
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
    parser.add_argument("--live", action="store_true",
                        help="真实 LLM 回归循环（第三轮评估①）：对 live 任务现场调用 LLM 生成并校验，测出真实遵守率")
    parser.add_argument("--live-only", action="store_true", help="仅跑 live 任务（跳过黄金样本自证任务，配合 --live）")
    parser.add_argument("--live-rounds", type=int, default=1, help="每个 live 任务的采样轮数（默认 1，多轮更稳）")
    parser.add_argument("--live-allow-llm-error", action="store_true",
                        help="后端不可达（llm_error）时不置退出码 1——CI 无稳定后端时用此开关把 live 放独立 job")
    args = parser.parse_args()

    tasks_doc = json.loads((REG_DIR / "tasks.json").read_text(encoding="utf-8"))
    current_year = tasks_doc.get("current_year", 2026)
    min_pass_rate = float(tasks_doc.get("min_pass_rate", 0.8))

    task_results = []
    live_results = []
    live_tasks = [t for t in tasks_doc["tasks"] if t.get("kind") == "live"]
    # --live：现场调用真实 LLM（独立于离线主循环，不拖慢黄金样本回归）
    if args.live:
        if not live_tasks:
            print("警告: tasks.json 中无 kind=live 任务，--live 无事可做", file=sys.stderr)
        out_dir = REG_DIR / "live_runs"
        out_dir.mkdir(exist_ok=True)
        for task in live_tasks:
            print(f"... live generating: {task['id']} ({task['level']}, rounds={args.live_rounds})", file=sys.stderr)
            live_results.append(run_live_task(task, out_dir, rounds=max(1, args.live_rounds)))

    for task in tasks_doc["tasks"]:
        if args.live_only:
            break  # --live-only：跳过离线任务
        if task["kind"] == "live":
            continue  # live 任务只在 --live 模式跑（离线循环跳过）
        if task["kind"] == "output_validation":
            task_results.append(run_output_task(task))
        elif task["kind"] == "score_check":
            task_results.append(run_score_task(task, current_year))
        elif task["kind"] == "llm_freeform":
            task_results.append(run_freeform_task(task, REG_DIR))
        else:
            task_results.append({"task": task["name"], "id": task["id"],
                                 "hard_failures": 0, "rewrite_count": 0,
                                 "mismatches": [f"未知任务类型: {task['kind']}"]})

    # --live-only 时 task_results 为空，离线聚合全部安全跳过
    rates = aggregate_check_pass_rate(task_results)
    below_threshold = [k for k, v in rates.items() if v < min_pass_rate] if task_results else []

    # P1-2：真实 LLM 信号层（freeform）通过率单独聚合，不与黄金样本自证基线混合
    measured_freeform = [tr for tr in task_results
                         if tr.get("kind") == "llm_freeform" and tr.get("status") == "measured"]
    pending_freeform = [tr for tr in task_results if tr.get("status") == "pending"]
    freeform_rates = aggregate_check_pass_rate(measured_freeform)
    # 第三轮评估①：--live 真实遵守率另列（与 freeform 区别：现场生成 vs 已归档样本）
    live_rates = aggregate_check_pass_rate(live_results)
    below_live = [k for k, v in live_rates.items() if v < min_pass_rate] if live_rates else []

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
        "freeform_check_pass_rate": freeform_rates,
        "freeform_pending": [tr["id"] for tr in pending_freeform],
        "live_check_pass_rate": live_rates,
        "_quality_note": "live/freeform 任务附 content_quality（quality_judge 5 维内容质量分：挑战具体性/冲突支撑/验证可执行/坦诚度/可证伪性，各 0~2，overall 0~10）——格式遵守率之外的内容维度信号。",
        "live_below_threshold": below_live,
        "_comment": "当前版本各校验项通过率基线。由 run_regression.py --update-baseline 生成；低于 min_pass_rate 的规则应优先删除或改为脚本兜底。check_pass_rate 来自黄金样本自证；freeform_check_pass_rate 来自已归档 LLM 样本；live_check_pass_rate 来自 --live 现场生成（真实遵守率，最可信的裁剪依据）。",
        "task_results": task_results + live_results,
        "below_threshold_checks": below_threshold,
        "baseline_regressions": regressions,
    }

    if args.update_baseline:
        baseline_doc = {
            "generated": report["generated"],
            "current_year": current_year,
            "min_pass_rate": min_pass_rate,
            "check_pass_rate": rates,
            "freeform_baseline": {
                "_comment": "真实 LLM 自由生成的遵守率基线（P1-2）。样本放在 freeform_samples/ 目录；低于 min_pass_rate 的规则应优先裁剪。初始为空，接入真实运行数据后由 --update-baseline 填充。",
                "check_pass_rate": freeform_rates,
            },
            "live_baseline": {
                "_comment": "真实 LLM 现场生成的遵守率基线（第三轮评估①，--live 产出）。这是规则裁剪（去提示词化）的最可信数据源；空=尚未跑过 --live。",
                "check_pass_rate": live_rates,
            },
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
    print(f"校验项通过率（黄金样本自证）: {rates}", file=sys.stderr)
    if freeform_rates:
        print(f"校验项通过率（真实 LLM 自由生成）: {freeform_rates}", file=sys.stderr)
    if live_rates:
        print(f"校验项通过率（--live 现场生成，真实遵守率）: {live_rates}", file=sys.stderr)
    if below_live:
        print(f"警告: live 低于 {min_pass_rate:.0%} 的规则（真实裁剪信号）: {below_live}", file=sys.stderr)
    if pending_freeform:
        print(f"⏳ freeform 任务待样本: {[tr['id'] for tr in pending_freeform]}", file=sys.stderr)
    if below_threshold:
        print(f"⚠ 低于 {min_pass_rate:.0%} 的规则清单（优先考虑删除该规则或改为脚本兜底）: "
              f"{below_threshold}", file=sys.stderr)
    if regressions:
        print(f"⚠ 相对基线回退: {regressions}", file=sys.stderr)

    return _decide_exit_code(
        task_results, live_results, below_threshold, regressions,
        allow_llm_error=getattr(args, "live_allow_llm_error", False),
    )


if __name__ == "__main__":
    sys.exit(main())
