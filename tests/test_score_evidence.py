"""score_evidence 计分器边界测试。

覆盖：
- P0-1: SCP 工具证据类型归一化（base_weight 不落 0.3）
- P0-4: 无年份论文 decay_factor=1.0 + validity_status="无法验证"
- 核心证据门槛、mock 隔离、预印本、未来年份、监管批准、重复 DOI、年份衰减
"""
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from score_evidence import score_evidence, calc_decay, infer_type, _resolve_core_threshold
from normalize_type import normalize_type


class TestCalcDecay:
    """年份衰减计算。"""

    def test_recent_year_no_decay(self, current_year):
        df, note = calc_decay(2024, current_year)
        assert df == 1.0

    def test_year_decay_2018(self, current_year):
        """2018 年论文，当前 2026 → 衰减 0.85。"""
        df, note = calc_decay(2018, current_year)
        assert df == 0.85

    def test_decay_floor_1990(self, current_year):
        """1990 年论文 → 衰减地板 0.3。"""
        df, note = calc_decay(1990, current_year)
        assert df == 0.3

    def test_none_year_no_decay(self):
        df, note = calc_decay(None, 2026)
        assert df == 1.0
        assert "invalid" in note or "none" in note.lower()

    def test_zero_year_no_decay(self):
        df, note = calc_decay(0, 2026)
        assert df == 1.0


class TestCoreEvidenceThreshold:
    """核心证据门槛：无域级覆盖的域中，全是 Conference_paper(1.0) → insufficient。

    P1-1 注：AI/hardware/material 域有更低域级门槛（AI=1.5、hardware/material=2.0），
    会议论文在这些域不再永远 insufficient，见 TestAIDomain；
    本测试改用 biotech 域（Conference_paper=1.0 < 2.5）验证全局门槛仍然生效。
    """

    def test_all_conference_papers_insufficient(self, current_year):
        papers = [
            {"title": "Conf paper 1", "doi": "10.1109/A.2024.1", "year": 2024,
             "type": "Conference_paper", "confidence": "high"},
            {"title": "Conf paper 2", "doi": "10.1109/B.2024.2", "year": 2024,
             "type": "Conference_paper", "confidence": "high"},
        ]
        result = score_evidence(papers, "biotech", current_year)
        assert result["level"] == "insufficient"
        assert "no core evidence" in result["threshold_note"]


class TestAIDomain:
    """P1-1: AI 域级核心证据门槛（1.5）——AI 会议论文方向不再永远 insufficient。"""

    def test_resolve_core_threshold(self):
        """域级阈值解析：域级优先，回退全局。"""
        assert _resolve_core_threshold("AI") == 1.5
        assert _resolve_core_threshold("hardware") == 2.0
        assert _resolve_core_threshold("material") == 2.0
        assert _resolve_core_threshold("biotech") == 2.5
        # 社科域（第三轮评估③）：psychology/education 显式覆盖 2.0，social 同
        assert _resolve_core_threshold("psychology") == 2.0
        assert _resolve_core_threshold("education") == 2.0
        assert _resolve_core_threshold("social") == 2.0
        # 未映射域经 DOMAIN_MAP 归一后回退全局
        assert _resolve_core_threshold("business") == 2.5

    def test_ai_conference_with_domain_threshold(self, papers_ai_conference, current_year):
        """AI 域会议论文 5 篇 → 域级门槛 1.5 下不判 insufficient。"""
        result = score_evidence(papers_ai_conference, "AI", current_year)
        assert result["level"] != "insufficient"
        assert result["level"] == "yellow"
        assert result["max_core_base_weight"] >= 1.5
        assert result["core_evidence_threshold"] == 1.5

    def test_biotech_conference_still_insufficient(self, current_year):
        """对照：同样证据在无域级覆盖的域仍判 insufficient。"""
        papers = [
            {"title": f"Conf paper {i}", "doi": f"10.1109/X.2024.{i}", "year": 2024,
             "type": "Conference_paper", "confidence": "high"}
            for i in range(1, 6)
        ]
        result = score_evidence(papers, "biotech", current_year)
        assert result["level"] == "insufficient"
        assert result["core_evidence_threshold"] == 2.5


class TestMockIsolation:
    """mock 隔离：is_mock=True 不计入有效证据。"""

    def test_all_mock_rule2_triggered(self, papers_mock, current_year):
        result = score_evidence(papers_mock, "biotech", current_year)
        assert result["valid_evidence_count"] == 0
        assert result["rule2_triggered"] is True


class TestPreprint:
    """预印本：arXiv DOI → 待核验，不计有效。"""

    def test_preprint_not_valid(self, papers_preprint, current_year):
        result = score_evidence(papers_preprint, "biotech", current_year)
        assert result["valid_evidence_count"] == 0
        detail = result["detailed_scores"][0]
        assert detail["validity_status"] == "待核验"


class TestFutureYear:
    """未来年份：year=2099 → 待核验。"""

    def test_future_year_pending(self, papers_future_year, current_year):
        result = score_evidence(papers_future_year, "AI", current_year)
        detail = result["detailed_scores"][0]
        assert detail["is_future_year"] is True
        assert detail["validity_status"] == "待核验"


class TestRegulatoryApproval:
    """监管批准：FDA_NMPA_approval + 官方编号 → 进 core。"""

    def test_regulatory_enters_core(self, papers_regulatory, current_year):
        result = score_evidence(papers_regulatory, "regulatory", current_year)
        detail = result["detailed_scores"][0]
        assert detail["validity_status"] == "监管批准"
        assert detail["tier"] == "core"
        assert detail["base_weight"] == 5.0


class TestDuplicateDOI:
    """重复 DOI：第二条 is_duplicate=True。"""

    def test_duplicate_marked(self, papers_duplicate_doi, current_year):
        result = score_evidence(papers_duplicate_doi, "AI", current_year)
        detail = result["detailed_scores"][1]
        assert detail["is_duplicate"] is True
        assert result["duplicate_count"] == 1


class TestSCPTypeNormalization:
    """P0-1: SCP 工具证据类型归一化。

    确保 SCP 数据库工具的 mock 数据经计分后 base_weight 不落 0.3。
    """

    def test_fda_drug_base_weight_5(self):
        """origene-fdadrug mock 数据 → base_weight == 5.0（而非 0.3）。"""
        paper = {
            "title": "FDA Drug: Aspirin",
            "doi": "DEN180001",
            "year": 2023,
            "type": "FDA_NMPA_approval",
            "confidence": "high",
        }
        result = score_evidence([paper], "regulatory", 2026)
        assert result["detailed_scores"][0]["base_weight"] == 5.0

    def test_ncbi_database_not_default(self):
        """NCBI 数据库记录 → base_weight != 0.3（External_validation=2.5）。"""
        paper = {
            "title": "TP53 — Tumor protein p53",
            "doi": "NCBI_12345",
            "year": 2024,
            "type": "External_validation",
            "confidence": "high",
        }
        result = score_evidence([paper], "biotech", 2026)
        assert result["detailed_scores"][0]["base_weight"] == 2.5

    def test_chembl_not_default(self):
        """ChEMBL 记录 → base_weight != 0.3（Journal_article=1.0）。"""
        paper = {
            "title": "Aspirin — COX inhibitor",
            "doi": "CHEMBL12345",
            "year": 2024,
            "type": "Journal_article",
            "confidence": "high",
        }
        result = score_evidence([paper], "drug", 2026)
        assert result["detailed_scores"][0]["base_weight"] == 1.0


class TestNoYearPaper:
    """P0-4: 无年份论文。"""

    def test_no_year_decay_1(self, current_year):
        paper = {
            "title": "Paper without year",
            "doi": "10.1109/NOYEAR.2024.1",
            "year": None,
            "type": "Journal_article",
            "confidence": "high",
        }
        result = score_evidence([paper], "AI", current_year)
        detail = result["detailed_scores"][0]
        assert detail["decay_factor"] == 1.0
        assert detail["validity_status"] == "无法验证"

    def test_none_year_validity(self, current_year):
        paper = {
            "title": "No year paper",
            "doi": "10.1038/no.2024.1",
            "year": None,
            "type": "Journal_article",
            "confidence": "high",
        }
        result = score_evidence([paper], "biotech", current_year)
        detail = result["detailed_scores"][0]
        assert detail["validity_status"] == "无法验证"
        assert result["valid_evidence_count"] == 0
