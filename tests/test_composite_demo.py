# -*- coding: utf-8 -*-
"""composite_demo.md 最小底线校验（v4.8.0，第八点评建议 10）。

composite_demo 是纯化后唯一不参与 CI 的输出样本。本测试给它补上 smoke 底线：
三档（L0/L1/L2）分段分别按对应档位跑全量校验；复合文档的免责声明集中在文末，
按整体检查一次（分段检查会因免责位置误报）。任何硬失败都说明示例文件已腐化。
"""
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
for p in (str(_SCRIPTS),):
    if p not in sys.path:
        sys.path.insert(0, p)

import validate_output as vo

DEMO = _ROOT / "examples" / "composite_demo.md"


def _segments():
    text = DEMO.read_text(encoding="utf-8")
    m0 = re.search(r"(?m)^## 第一档.*?(?=^## 第二档)", text, re.DOTALL)
    m1 = re.search(r"(?m)^## 第二档.*?(?=^## 第三档)", text, re.DOTALL)
    m2 = re.search(r"(?m)^## 第零章.*?(?=^## 免责声明)", text, re.DOTALL)
    md = re.search(r"(?m)^## 免责声明.*\Z", text, re.DOTALL)
    assert m0 and m1 and m2 and md, "composite_demo.md 分段结构缺失，文件可能已损坏"
    return [
        ("L0", m0.group(0)),
        ("L1", m1.group(0)),
        ("L2", m2.group(0) + "\n\n" + md.group(0)),
    ]


class TestCompositeDemoSmoke:
    def test_file_exists_with_all_three_levels(self):
        segs = _segments()
        assert [s[0] for s in segs] == ["L0", "L1", "L2"]

    def test_l2_segment_passes_full_validation(self):
        level, seg = [s for s in _segments() if s[0] == "L2"][0]
        results, fails = vo.run_all(seg, None, level)
        failed = [(r[0], r[2]) for r in results if r[1] is False]
        assert fails == 0, f"composite_demo L2 段硬失败: {failed}"

    def test_l0_l1_segments_pass_level_checks(self):
        """L0/L1 段跑各自档位校验；免责声明集中在文末，分段免责误报过滤后须全绿。"""
        for level, seg in _segments():
            if level == "L2":
                continue
            results, fails = vo.run_all(seg, None, level)
            # 复合文档结构豁免：免责声明不随段走（整体在 test_full_document_disclaimer 验证）
            filtered = [r for r in results if not (r[1] is False and "免责" in r[0])]
            real_fails = [r for r in filtered if r[1] is False]
            assert not real_fails, f"composite_demo {level} 段硬失败: {[(r[0], r[2]) for r in real_fails]}"

    def test_full_document_disclaimer(self):
        text = DEMO.read_text(encoding="utf-8")
        ok, detail = vo.check_disclaimer(text, level="L2")
        assert ok, f"composite_demo 整体免责声明不合格: {detail}"

    def test_no_instruction_leakage(self):
        """指令性文字泄漏检测（校验第 20 项）对全文跑一次。"""
        text = DEMO.read_text(encoding="utf-8")
        ok, detail = vo.check_instruction_leakage(text) if hasattr(vo, "check_instruction_leakage") else (True, "n/a")
        if hasattr(vo, "check_instruction_leakage"):
            assert ok, f"composite_demo 指令泄漏: {detail}"
