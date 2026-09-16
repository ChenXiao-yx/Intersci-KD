# -*- coding: utf-8 -*-
"""判别效度对照测试（v4.8.0 #93，第八点评建议 2）。

黄金样本自证只说明"好输出得高分/能过校验"；本模块用故意写坏的对照样本
验证反向命题——"坏输出真会掉分/真会被拦"：

- bad_yellow_overclaim.md：黄区谎报优先整合 + 6 类硬伤（双层 DOI/重复 DOI/
  有 DOI 标无法验证/预测无标注/内部黑话/冲突硬编）→ 21 项校验器必须硬失败
- bad_vague_quality.md：全空话简报 → quality_judge 启发式必须显著低于黄金标定分
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
for p in (str(_SCRIPTS),):
    if p not in sys.path:
        sys.path.insert(0, p)

import validate_output as vo
from config_loader import load_dotenv

load_dotenv()

BAD_DIR = _ROOT / "tests" / "regression" / "fixtures" / "bad_samples"
OVERCLAIM = BAD_DIR / "bad_yellow_overclaim.md"
VAGUE = BAD_DIR / "bad_vague_quality.md"


class TestBadOverclaimInterception:
    """坏样本 1：黄区谎报优先整合必须被硬拦截。"""

    def test_overclaim_has_hard_failures(self):
        text = OVERCLAIM.read_text(encoding="utf-8")
        results, fails = vo.run_all(text, None, "L2")
        assert fails > 0, "坏样本必须产生硬失败，否则校验器无判别力"

    def test_overclaim_blocked_by_matrix_with_score_json(self):
        """带 score_json（level=yellow）时，矩阵强校验必须拦截「优先整合」。"""
        text = OVERCLAIM.read_text(encoding="utf-8")
        score_json = {"level": "yellow", "valid_evidence_count": 2, "rule2_triggered": False}
        ok, detail = vo.check_matrix_strong_validation(text, score_json)
        assert ok is False, f"黄区+优先整合必须被矩阵强校验拦截，实际: {detail}"

    def test_overclaim_hits_expected_checks(self):
        """坏样本至少命中 3 类不同硬伤（DOI/黑话/预测/有效性 任三）。"""
        text = OVERCLAIM.read_text(encoding="utf-8")
        results, fails = vo.run_all(text, None, "L2")
        failed_names = [r[0] for r in results if r[1] is False]
        assert len(failed_names) >= 3, f"预期至少 3 类硬伤，实际失败项: {failed_names}"
        joined = " ".join(failed_names)
        assert any(k in joined for k in ("DOI", "有效性")), "DOI/有效性类硬伤未命中"
        assert any(k in joined for k in ("黑话", "预测")), "黑话/预测类硬伤未命中"


class TestBadVagueQuality:
    """坏样本 2：空话简报必须被内容质量度量识别。"""

    def test_vague_scores_far_below_golden(self):
        import quality_judge as qj
        golden = (_ROOT / "examples" / "full_output_golden.md").read_text(encoding="utf-8")
        golden_score = qj.heuristic_score(golden)["overall"]
        bad_score = qj.heuristic_score(VAGUE.read_text(encoding="utf-8"))["overall"]
        assert golden_score - bad_score >= 3, (
            f"黄金标定 {golden_score} 与坏样本 {bad_score} 差距不足 3 分，判别力不足"
        )

    def test_vague_below_threshold(self):
        import quality_judge as qj
        result = qj.heuristic_score(VAGUE.read_text(encoding="utf-8"))
        assert result["overall"] <= 5, f"空话简报得分 {result['overall']} 过高"


class TestGoldenStillPasses:
    """对照平衡：坏样本拦截的同时，黄金样本必须仍然全绿（防校验器过拟合到坏特征）。"""

    def test_golden_l2_still_zero_failures(self):
        golden = (_ROOT / "examples" / "full_output_golden.md").read_text(encoding="utf-8")
        score = (_ROOT / "examples" / "full_output_golden.score.json")
        import json
        score_json = json.loads(score.read_text(encoding="utf-8")) if score.exists() else None
        results, fails = vo.run_all(golden, score_json, "L2")
        failed = [r for r in results if r[1] is False]
        assert fails == 0, f"黄金样本被误伤: {[(r[0], r[2]) for r in failed]}"
