# -*- coding: utf-8 -*-
"""run_regression.py 关键行为的回归测试（第五轮 P0-3）。

覆盖：
- _decide_exit_code 纯函数的退出码语义（--live-allow-llm-error 开关等价物）
- citation_lookup 的 PEP 585/604 兼容性（模块可导入 + 注解形态）
"""
import io
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
for p in (str(_SCRIPTS), str(_ROOT / "tests" / "regression")):
    if p not in sys.path:
        sys.path.insert(0, p)

import run_regression as rr


class TestDecideExitCode:
    """--live-allow-llm-error 的退出码语义（P0-3）。"""

    def test_llm_error_affects_exit_code_by_default(self):
        """无开关时，llm_error 使退出码为 1（strict 默认）。"""
        live = [{"status": "llm_error"}]
        code = rr._decide_exit_code([], live, [], [], allow_llm_error=False)
        assert code == 1

    def test_allow_flag_swallows_llm_error(self):
        """带开关时，llm_error 不影响退出码。"""
        live = [{"status": "llm_error"}]
        code = rr._decide_exit_code([], live, [], [], allow_llm_error=True)
        assert code == 0

    def test_live_violations_do_not_affect_exit_code(self):
        """live 的 hard_failures 是真实违规数据（交付物），不影响退出码。"""
        live = [{"status": "measured", "hard_failures": 3}]
        code = rr._decide_exit_code([], live, [], [], allow_llm_error=False)
        assert code == 0

    def test_offline_hard_failure_fails(self):
        """离线任务硬失败 → 1（不受开关影响）。"""
        offline = [{"hard_failures": 1}]
        assert rr._decide_exit_code(offline, [], [], [], allow_llm_error=True) == 1

    def test_below_threshold_fails(self):
        """遵守率低于阈值 → 1。"""
        assert rr._decide_exit_code([], [], ["17"], [], allow_llm_error=True) == 1

    def test_baseline_regression_fails(self):
        """相对基线回退 → 1。"""
        assert rr._decide_exit_code([], [], [], ["19: baseline=1.0, current=0.8"], allow_llm_error=True) == 1

    def test_all_clean_passes(self):
        """全部正常 → 0。"""
        assert rr._decide_exit_code([], [], [], [], allow_llm_error=False) == 0


class TestPythonCompat:
    """P0-1/P1-2 联动：注解语法与 requires-python 一致。"""

    def test_citation_lookup_importable(self):
        """citation_lookup 可导入（本解释器下无 TypeError）。"""
        import citation_lookup  # noqa: F401

    def test_no_pep604_in_scripts(self):
        """scripts/ 无 __future__ 的文件不得含 PEP 604 注解（与 check_consistency 同规则的双保险）。"""
        for py in (_SCRIPTS).glob("*.py"):
            text = io.open(py, encoding="utf-8").read()
            if "from __future__ import annotations" in text:
                continue
            assert not re.search(r":\s*\w+\s*\|\s*None", text), f"{py.name} 含 PEP 604"
            assert not re.search(r"->\s*\w+\s*\|\s*None", text), f"{py.name} 含 PEP 604"

    def test_pyproject_and_future_flags_consistent(self):
        """requires-python >=3.8 时，含内置泛型注解的文件必须有 __future__ 导入或 typing 风格。"""
        pyproject = io.open(_ROOT / "pyproject.toml", encoding="utf-8").read()
        m = re.search(r'requires-python\s*=\s*["\']>=\s*(\d+)\.(\d+)', pyproject)
        assert m, "pyproject 缺 requires-python"
        major, minor = int(m.group(1)), int(m.group(2))
        if (major, minor) >= (3, 10):
            return
        for py in (_SCRIPTS).glob("*.py"):
            text = io.open(py, encoding="utf-8").read()
            if "from __future__ import annotations" in text:
                continue
            # 允许 typing.Dict/List/Optional 与字符串注解；禁止裸内置泛型注解
            code_only = "\n".join(l for l in text.split("\n") if not l.strip().startswith("#"))
            assert not re.search(r":\s*(list|dict|tuple|set)\[", code_only), \
                f"{py.name} 含 PEP 585 裸泛型注解且无 __future__"
