#!/usr/bin/env python3
"""quality_judge.py — 内容质量度量（第五点评建议 1：从"格式合规"补"内容质量"）。

21 项格式校验回答"输出长得对不对"；本脚本回答"输出说得好不好"。
对一份 L2 十章简报，按 5 个内容维度打 0~2 分（0=不达标 1=部分 2=达标）：

  Q1 核心挑战具体性  —— 第零章的"核心科学挑战"是否点出该交叉点的要害，
                        而非"X 与 Y 的交叉"这类正确废话。
  Q2 冲突证据支撑    —— 第七章的"未消解冲突"是否有具体文献/数据支撑，
                        而非为凑结论分支硬写的泛化冲突。
  Q3 验证动作可执行  —— 第八章的"验证动作"是否是可操作的下一步（含具体
                        实验/检索/比较方式），而非"构建关联图并交叉校验"类空话。
  Q4 坦诚度          —— 第九章是否承认了真实的证据缺口与不利信号，
                        而非通篇正面。
  Q5 可证伪性        —— 结论是否暗含"什么新证据会改变结论"（可证伪），
                        而非永远正确的措辞。

判定方式（两层）：
- LLM judge（推荐）：--llm 用 .env 的 OpenAI 兼容后端按 rubric 逐维打分，返回 JSON；
- 启发式 fallback（无 LLM 时）：可测的客观代理信号——具体数字/文献锚点密度、
  空话短语命中、可执行动作动词密度。fallback 分数标注 "mode": "heuristic"，
  只作粗筛参考，不替代 LLM judge。

结果落 JSON：{"q1": {...}, ..., "overall": x/10, "mode": "llm|heuristic"}。
供 run_regression --quality 聚合为 content_quality 基线（区别于格式遵守率）。
"""
import argparse
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

# 内容空话黑名单（出现即扣分的信号短语——黑名单只做粗筛，不是门禁）
VAGUE_PHRASES = [
    "构建关联图并交叉校验",
    "进一步深入研究",
    "持续关注最新进展",
    "加强产学研合作",
    "多学科交叉融合",
    "提升整体水平",
    "有待进一步验证",
]
# 可执行动作信号（具体动词/比较结构）
ACTION_SIGNALS = [
    "头对头", "对照实验", "多中心", "消融", "复现", "基准测试",
    "外部验证", "A/B", "随机对照", "样本量", "招募", "随访",
]
EVIDENCE_ANCHOR = re.compile(
    r"10\.\d{4,}/"        # DOI
    r"|\d+(?:\.\d+)?%"    # 百分比
    r"|\b\d{4}\b"         # 年份
    r"|\d+\.\d+"          # 小数指标（AUC/kappa 等）
    r"|[\u3010\u3011]"     # 【】标签符号
    r"|JAMA|NEJM|Lancet|Nature|Science|IEEE|FDA|NMPA|CE"  # 权威来源名
)

RUBRIC_PROMPT = """你是研究简报的内容质量评审。按以下 5 个维度对这份 L2 简报打分（每维 0~2 分）：
Q1 核心挑战具体性：第零章是否点出交叉点的要害（2=具体且带证据；1=部分具体；0=正确废话）。
Q2 冲突证据支撑：第七章冲突是否有文献/数据支撑（2=有具体来源与数字；1=泛化但有方向；0=为凑分支硬写）。
Q3 验证动作可执行：第八章是否给出可操作的下一步（2=含具体实验/比较/样本设计；1=方向对但笼统；0=空话）。
Q4 坦诚度：第九章是否承认真实缺口与不利信号（2=明确列出缺口与反例；1=部分承认；0=通篇正面）。
Q5 可证伪性：结论是否说明什么新证据会改变结论（2=明确的升降级条件；1=含糊提及；0=无）。

只输出 JSON：{"q1": {"score": 0-2, "reason": "一句话"}, ..., "q5": {...}, "overall": 0-10}
简报内容：
"""


def _heuristic_section(text: str, start_pat: str) -> str:
    """粗提取某章正文（到下一个 ## 前），找不到返回空串。"""
    m = re.search(start_pat + r"(.*?)(?=\n## |\Z)", text, re.DOTALL)
    return m.group(1) if m else ""


def heuristic_score(text: str) -> dict:
    """无 LLM 时的客观代理信号打分（粗筛，非内容判断）。"""
    ch0 = _heuristic_section(text, r"##\s*第零章[:：]?")
    ch7 = _heuristic_section(text, r"##\s*第七章[:：]?")
    ch8 = _heuristic_section(text, r"##\s*第八章[:：]?")
    ch9 = _heuristic_section(text, r"##\s*第九章[:：]?")

    def score_dim(section: str, anchor_density_target: float, vague_weight: float,
                  action_weight: float = 0.0) -> dict:
        if not section.strip():
            return {"score": 0, "reason": "章节缺失"}
        anchors = len(EVIDENCE_ANCHOR.findall(section))
        density = anchors / max(1, len(section.split("\n")))
        vague = sum(1 for p in VAGUE_PHRASES if p in section)
        actions = sum(1 for a in ACTION_SIGNALS if a in section)
        s = 2
        reasons = []
        if density < anchor_density_target:
            s -= 1
            reasons.append(f"证据锚点密度低({anchors}处)")
        if vague > 0:
            s -= min(2, vague * vague_weight)
            reasons.append(f"空话短语{vague}处")
        if action_weight and actions == 0:
            s -= 1
            reasons.append("无可执行动作信号")
        return {"score": max(0, s), "reason": "；".join(reasons) or "信号良好"}

    out = {
        "q1": score_dim(ch0, 0.25, 1),
        "q2": score_dim(ch7, 0.20, 1),
        "q3": score_dim(ch8, 0.12, 1, action_weight=1),
        "q4": score_dim(ch9, 0.18, 1),
        "q5": {"score": 2 if ("若" in ch9 or "上调" in ch9 or "下调" in ch9) else 0,
               "reason": "含升降级条件" if ("若" in ch9 or "上调" in ch9) else "无可证伪条件"},
    }
    out["overall"] = sum(v["score"] for v in out.values())
    out["mode"] = "heuristic"
    return out


def llm_score(text: str) -> dict:
    """LLM judge 打分（复用 run_regression._llm_chat 的后端选择）。"""
    reg = _ROOT / "tests" / "regression"
    if str(reg) not in sys.path:
        sys.path.insert(0, str(reg))
    from run_regression import _llm_chat
    raw = _llm_chat(RUBRIC_PROMPT + text[:12000], max_tokens=1024, temperature=0.0)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"LLM 未返回 JSON: {raw[:200]}")
    data = json.loads(m.group(0))
    data["mode"] = "llm"
    return data


def judge(text: str, prefer_llm: bool = True) -> dict:
    if prefer_llm:
        try:
            return llm_score(text)
        except Exception as e:  # noqa: BLE001 — LLM 不可用自动降级
            print(f"WARNING: LLM judge 不可用（{type(e).__name__}），降级为启发式。", file=sys.stderr)
    return heuristic_score(text)


def main():
    parser = argparse.ArgumentParser(description="内容质量度量（5 维 0~2 分，LLM judge 或启发式）")
    parser.add_argument("--input", required=True, help="L2 简报 Markdown 路径")
    parser.add_argument("--output", default=None, help="结果 JSON 输出路径")
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM judge，直接用启发式")
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    text = Path(args.input).read_text(encoding="utf-8")
    result = judge(text, prefer_llm=not args.no_llm)
    result["input"] = args.input
    out = json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
