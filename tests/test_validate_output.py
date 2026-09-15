"""validate_output 校验器测试。

覆盖：
- P0-2: 三档黄金样本 + score.json 全绿回归；校验器修复回归（check1 NameError/check2 引用块主结论/check9 DOI 双计）
- P0-3: L0 条件化结论容错
- P0-7: detect_level 已删除、level=None 报错
- P1-2: 校验项 20 指令性文字泄漏检测
- 校验器核心检查项：三选一结论、黑话检测、DOI 去重
"""
import sys
import json
import pytest
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import validate_output as vo


class TestDetectLevelRemoved:
    """P0-7: detect_level 已删除。"""

    def test_detect_level_not_exist(self):
        assert not hasattr(vo, "detect_level")

    def test_run_all_requires_level(self):
        """level=None 时 raise ValueError。"""
        with pytest.raises(ValueError, match="level is required"):
            vo.run_all("some text", level=None)


class TestConditionalConclusion:
    """P0-3: L0 条件化双结论容错。"""

    def test_conditional_branch_passes(self):
        """主结论在正文，条件分支在引用块 → 通过。"""
        text = """## 第九章：三选一决策建议

**结论**：🟡 建议持续追踪（若目标是算法研究）

> **条件分支**：
> - 若目标是产品部署（过审批）→ 🔴 建议暂时搁置（需补临床检索）
> - 若目标不确定 → 默认按算法研究处理，🟡 建议持续追踪

## 第十章：证据索引表
"""
        ok, detail = vo.check_three_choice_conclusion(text)
        assert ok is True
        assert "建议持续追踪" in detail

    def test_multiple_conclusions_no_blockquote_fails(self):
        """无引用块的多结论 → 失败。"""
        text = """## 第九章：三选一决策建议

**结论**：🟡 建议持续追踪 / 🔴 建议暂时搁置

## 第十章：证据索引表
"""
        ok, detail = vo.check_three_choice_conclusion(text)
        assert ok is False
        assert "多个主结论" in detail

    def test_single_conclusion_passes(self):
        """单一结论 → 通过。"""
        text = """## 第九章：三选一决策建议

**结论**：🟡 建议持续追踪

## 第十章：证据索引表
"""
        ok, detail = vo.check_three_choice_conclusion(text)
        assert ok is True

    def test_extract_conclusion_returns_first(self):
        """extract_conclusion 返回最先出现的结论。"""
        text = """## 第九章：三选一决策建议

**结论**：🟡 建议持续追踪

> 条件分支：若部署 → 🔴 建议暂时搁置

## 第十章：证据索引表
"""
        conclusion = vo.extract_conclusion(text)
        assert conclusion == "建议持续追踪"

    def test_extract_conclusion_none(self):
        """无结论 → None。"""
        text = "## 第九章\nNo conclusion here\n## 第十章\n"
        assert vo.extract_conclusion(text) is None


class TestJargonDetection:
    """P0-2 必测: 黑话检测。"""

    def test_script_name_detected(self):
        """交付物含 score_evidence.py → 第 19 项 fail。"""
        text = "## 某章\n\n使用了 score_evidence.py 进行计分。\n## 第十章\n"
        # check_no_internal_jargon 应检测到内部黑话
        ok, detail = vo.check_no_internal_jargon(text, vo.LEVEL_L2)
        assert ok is False

    def test_normal_text_passes(self):
        """正常中文不误伤。"""
        text = "## 第九章\n\n结论：建议持续追踪。证据来自系统综述。\n## 第十章\n"
        ok, detail = vo.check_no_internal_jargon(text, vo.LEVEL_L2)
        assert ok is True


class TestL0GoldenSample:
    """L0 黄金样本校验通过（不带 score.json）。"""

    def test_card_output_golden_passes_l0(self, scripts_dir):
        golden = scripts_dir.parent / "examples" / "card_output_golden.md"
        if not golden.exists():
            pytest.skip("Golden sample not found")
        text = golden.read_text(encoding="utf-8")
        results, fails = vo.run_all(text, level=vo.LEVEL_L0)
        assert fails == 0, f"L0 golden sample has {fails} failures: {[r[1] for r in results if r[1] is False]}"


class TestGoldenSamplesWithScore:
    """P0-2: 三档黄金样本 + 配套 score.json 必须全绿。"""

    @pytest.mark.parametrize("level,golden,score", [
        ("L0", "card_output_golden.md", "card_output_golden.score.json"),
        ("L1", "brief_output_golden.md", "brief_output_golden.score.json"),
        ("L2", "full_output_golden.md", "full_output_golden.score.json"),
    ])
    def test_golden_samples_pass(self, level, golden, score, scripts_dir):
        """三档黄金样本必须能通过各自档位的完整校验（含 score_json）。"""
        golden_path = scripts_dir.parent / "examples" / golden
        score_path = scripts_dir.parent / "examples" / score
        if not golden_path.exists() or not score_path.exists():
            pytest.skip(f"{golden} 或 {score} 不存在")
        text = golden_path.read_text(encoding="utf-8")
        score_json = json.loads(score_path.read_text(encoding="utf-8"))
        results, fails = vo.run_all(text, score_json=score_json, level=level)
        failed = [(r[0], r[2]) for r in results if r[1] is False]
        assert fails == 0, f"{golden} ({level}) 有 {fails} 项硬失败: {failed}"

    def test_score_jsons_are_identical(self, scripts_dir):
        """三档数据同源：三份 score.json 内容一致（同一 10 条证据一次计分）。"""
        base = scripts_dir.parent / "examples"
        hashes = set()
        for name in ("full_output_golden.score.json", "card_output_golden.score.json", "brief_output_golden.score.json"):
            p = base / name
            if not p.exists():
                pytest.skip(f"{name} 不存在")
            hashes.add(p.read_text(encoding="utf-8").strip())
        assert len(hashes) == 1


class TestValidatorBugfixes:
    """P0-2 修复的三个校验器缺陷回归。"""

    def test_check1_no_nameerror_on_l2(self):
        """第 1 项在 L2 下不再 NameError（原 CHECKS lambda 闭包引用未定义 level）。"""
        text = "## 第零章：跨学科全景扫描\n\n正文。\n"
        ok, detail = vo.check_chapter_zero_first(text, level=vo.LEVEL_L2)
        assert ok is True

    def test_check2_quote_block_main_conclusion(self):
        """L2 模板第九章主结论在引用块（> **结论：…**）可被识别。"""
        text = """## 第九章：跨学科综合置信度

> **结论：建议持续追踪**
>
> **结论依据**：存在未消解的核心冲突。

## 第十章：多源证据锚点
"""
        ok, detail = vo.check_three_choice_conclusion(text)
        assert ok is True, detail

    def test_check9_link_and_url_same_doi_not_duplicate(self):
        """同一 DOI 的链接文字与 URL 双形式不再误报重复。"""
        text = """## 第十章：多源证据锚点

| 序号 | 标题 | 学科 | 来源 | 有效性状态 | 支撑结论 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Paper A | AI | [10.1001/x.2024.1](https://doi.org/10.1001/x.2024.1) | 有效 | 支撑A |
| 2 | Paper B | AI | [10.1109/y.2024.2](https://doi.org/10.1109/y.2024.2) | 有效 | 支撑B |
"""
        ok, detail = vo.check_doi_dedup(text)
        assert ok is True, detail

    def test_check9_real_duplicate_detected(self):
        """跨行重复 DOI 仍被检出。"""
        text = """## 第十章：多源证据锚点

| 序号 | 标题 | 学科 | 来源 | 有效性状态 | 支撑结论 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | Paper A | AI | [10.1001/x.2024.1](https://doi.org/10.1001/x.2024.1) | 有效 | 支撑A |
| 2 | Paper A dup | AI | [10.1001/x.2024.1](https://doi.org/10.1001/x.2024.1) | 有效 | 支撑A |
"""
        ok, detail = vo.check_doi_dedup(text)
        assert ok is False

    def test_ch7_fallback_for_condensed_views(self):
        """P0-2: L0/L1 无第七章区域时，按行检测未消解冲突信号。"""
        card = "**结论**：🟢 建议持续追踪（强证据 + 第七章未消解冲突）\n"
        assert vo._chapter7_has_unresolved_conflict(card) is True
        clean = "**结论**：🟢 建议优先整合\n"
        assert vo._chapter7_has_unresolved_conflict(clean) is False


class TestInstructionLeak:
    """P1-2: 校验项 20 指令性文字泄漏检测。"""

    def test_leak_detected_in_quote_block(self):
        """泄漏文字即使在引用块中也应被检出（方案验收样本）。"""
        text = "## 免责声明\n> 本简报基于公开学术论文和通用知识生成，不得修改措辞。\n"
        ok, detail = vo.check_no_instruction_leak(text, vo.LEVEL_L0)
        assert ok is False
        assert "指令性文字泄漏" in detail

    def test_clean_text_passes(self):
        text = "## 免责声明\n> 本简报基于公开文献生成，不构成研究决策依据。\n"
        ok, detail = vo.check_no_instruction_leak(text, vo.LEVEL_L0)
        assert ok is True

    def test_check20_applies_to_all_levels(self):
        for lvl in (vo.LEVEL_L0, vo.LEVEL_L1, vo.LEVEL_L2, vo.LEVEL_L3):
            assert 20 in vo.APPLICABLE_CHECKS[lvl]
