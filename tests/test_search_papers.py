"""search_papers 测试。

覆盖：
- P0-5: 补检自动执行逻辑
- P0-6: domain 参数一致性
- DOI 修正/去重
"""
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import search_papers
from search_papers import _need_supplemental_search, _validate_doi_format, _dedup_dois
from config_loader import get_valid_domains


class TestDomainConsistency:
    """P0-6: domain 参数一致性。"""

    def test_search_papers_accepts_default_domain(self):
        """search_papers.py 的 choices 应包含 'default'。"""
        domains = get_valid_domains()
        assert "default" in domains

    def test_domains_match_config(self):
        """domain choices 与 evidence_weights.json 的 domain_map 键一致。"""
        from config_loader import load_config
        config = load_config()
        expected = set(config["domain_map"].keys())
        actual = set(get_valid_domains())
        assert expected == actual


class TestSupplementalSearch:
    """P0-5: 补检判定。"""

    def test_all_conference_papers_needs_supplemental(self):
        papers = [
            {"type": "Conference_paper", "title": "Conf paper 1"},
            {"type": "Conference_paper", "title": "Conf paper 2"},
        ]
        assert _need_supplemental_search(papers) is True

    def test_has_systematic_review_no_supplemental(self):
        papers = [
            {"type": "Systematic_review", "title": "SR of sensors"},
        ]
        assert _need_supplemental_search(papers) is False

    def test_has_rct_no_supplemental(self):
        papers = [
            {"type": "RCT", "title": "RCT of CRISPR"},
        ]
        assert _need_supplemental_search(papers) is False

    def test_has_fda_no_supplemental(self):
        papers = [
            {"type": "FDA_NMPA_approval", "title": "FDA approval"},
        ]
        assert _need_supplemental_search(papers) is False

    def test_title_keyword_no_supplemental(self):
        papers = [
            {"type": "Journal_article", "title": "A systematic review of sensors"},
        ]
        assert _need_supplemental_search(papers) is False

    def test_empty_papers_no_supplemental(self):
        assert _need_supplemental_search([]) is False

    def test_has_run_supplemental_search_function(self):
        assert hasattr(search_papers, "_run_supplemental_search")


class TestDOIValidation:
    """DOI 双层前缀修正。"""

    def test_double_prefix_corrected(self):
        doi = "10.1145/10.1145/3644116.3644178"
        corrected, error = _validate_doi_format(doi)
        assert corrected == "10.1145/3644116.3644178"
        assert error is True

    def test_normal_doi_unchanged(self):
        doi = "10.1109/SENSOR.2023.12345"
        corrected, error = _validate_doi_format(doi)
        assert corrected == doi
        assert error is False

    def test_empty_doi_unchanged(self):
        corrected, error = _validate_doi_format("")
        assert corrected == ""
        assert error is False


class TestDedupDOIs:
    """DOI 去重标记。"""

    def test_duplicate_marked(self):
        papers = [
            {"doi": "10.1109/A.2024.1", "title": "A"},
            {"doi": "10.1109/A.2024.1", "title": "B (dup)"},
        ]
        _dedup_dois(papers)
        assert papers[0]["is_duplicate"] is False
        assert papers[1]["is_duplicate"] is True

    def test_empty_doi_not_marked(self):
        papers = [
            {"doi": "", "title": "No DOI"},
            {"doi": "", "title": "Also no DOI"},
        ]
        _dedup_dois(papers)
        assert papers[0]["is_duplicate"] is False
        assert papers[1]["is_duplicate"] is False

    def test_unique_dois_all_false(self):
        papers = [
            {"doi": "10.1/A", "title": "A"},
            {"doi": "10.1/B", "title": "B"},
        ]
        _dedup_dois(papers)
        assert all(p["is_duplicate"] is False for p in papers)
