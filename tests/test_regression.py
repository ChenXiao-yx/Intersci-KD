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

import os

import pytest

import run_regression as rr
import search_papers


def _network_available():
    """第八点评 #4：实网测试防抖——离线 CI/无网环境跳过，而不是 flaky。"""
    import socket
    try:
        socket.create_connection(("api.crossref.org", 443), timeout=3).close()
        return True
    except OSError:
        return False


NET_AVAILABLE = _network_available()


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


class TestContentQuality:
    """第五点评建议 1：内容质量度量（quality_judge）。"""

    def test_heuristic_importable_and_runs(self):
        import quality_judge as qj
        golden = (_ROOT / "examples" / "full_output_golden.md").read_text(encoding="utf-8")
        result = qj.heuristic_score(golden)
        assert result["mode"] == "heuristic"
        assert 0 <= result["overall"] <= 10
        # 黄金样本是标定点：内容质量应接近满分（>=9）
        assert result["overall"] >= 9, f"golden 标定分 {result['overall']} 过低"

    def test_empty_sections_score_zero(self):
        import quality_judge as qj
        result = qj.heuristic_score("# 无章节内容\n\n一段普通文字。\n")
        assert result["overall"] <= 4

    def test_vague_phrases_penalized(self):
        import quality_judge as qj
        vague = (
            "## 第零章：跨学科全景扫描\n\n本方向需进一步深入研究、加强产学研合作【推断】。\n"
            "## 第七章：认知冲突与消解策略\n\n持续关注最新进展【推断】。\n"
            "## 第八章：蒸馏验证路径\n\n构建关联图并交叉校验【推断】。\n"
            "## 第九章：跨学科综合置信度\n\n一切良好【确证】。\n"
        )
        result = qj.heuristic_score(vague)
        assert result["overall"] <= 5

    def test_judge_degrades_gracefully(self):
        """prefer_llm=True 但无后端时降级为启发式且不抛异常。"""
        import quality_judge as qj
        golden = (_ROOT / "examples" / "full_output_golden.md").read_text(encoding="utf-8")
        result = qj.judge(golden, prefer_llm=True)
        assert result["mode"] in ("llm", "heuristic")
        assert "overall" in result



class TestProviderFallback:
    """第六点评 P1：Crossref 真实检索兜底（解 SCP 单点依赖）。"""

    def test_crossref_provider_module(self):
        """providers.base 可导入且 CrossrefProvider 可用。"""
        from providers.base import CrossrefProvider, PROVIDER_CHAIN
        assert any(p.name == "crossref" for p in PROVIDER_CHAIN)
        assert CrossrefProvider().available() is True

    def test_crossref_search_real(self):
        """Crossref 实网检索返回真实 DOI 文献（无 Key、全学科）。"""
        if not NET_AVAILABLE:
            pytest.skip("网络不可达，跳过实网检索测试")
        from providers.base import CrossrefProvider
        papers = CrossrefProvider().search("diabetic retinopathy deep learning", 3)
        assert len(papers) >= 1
        for p in papers:
            assert p["doi"].startswith("10.")
            assert p["title"]
            assert p.get("is_mock") is not True  # Crossref 真实文献，无 mock 标记
            assert p.get("provider") == "crossref"

    def test_search_fallback_returns_crossref(self):
        """search_fallback 链返回 crossref 结果。"""
        if not NET_AVAILABLE:
            pytest.skip("网络不可达，跳过实网检索测试")
        from providers.base import search_fallback
        papers, name = search_fallback("wearable ECG sensor", 2)
        assert name == "crossref"
        assert papers and all(p["doi"] for p in papers)

    def test_delegate_auth_error_falls_to_crossref(self):
        """无效 Key → auth_error → Crossref 兜底返回真实文献（非 mock）。"""
        if not NET_AVAILABLE:
            pytest.skip("网络不可达，跳过实网检索测试")
        os.environ["SCP_HUB_API_KEY"] = "invalid-test-key-12345"
        result = search_papers._try_scp_delegate("wearable ECG sensor", 2, None)
        assert result is not None
        assert result["source"].startswith("providers:crossref")
        for p in result["papers"]:
            assert p.get("is_mock") is not True
            assert p.get("doi", "").startswith("10.")
