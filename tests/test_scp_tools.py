"""scp_tools 解析器与工具注册表测试。

覆盖：
- P0-1: TOOL_REGISTRY evidence_type 全部是标准键
- P0-4: 解析器不硬编码年份 2024（无年份返回 None）
- P0-1: _inject_standard_type 注入逻辑
"""
import sys
import json
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import scp_tools
from scp_tools import TOOL_REGISTRY, _inject_standard_type, _extract_year, _extract_year_from_text
from config_loader import load_config


# evidence_weights.json 的标准键集合
_CONFIG = load_config()
STANDARD_KEYS = set(_CONFIG["evidence_weights"].keys())


class TestToolRegistryEvidenceType:
    """P0-1 Layer 1: TOOL_REGISTRY evidence_type 全部是标准键。"""

    def test_all_evidence_types_are_standard(self):
        """所有工具的 evidence_type 必须是 evidence_weights.json 的标准键。"""
        for tool_name, entry in TOOL_REGISTRY.items():
            evidence_type = entry[3]  # 第 4 个元素是 evidence_type
            assert evidence_type in STANDARD_KEYS, (
                f"Tool '{tool_name}' evidence_type '{evidence_type}' is not a standard key. "
                f"Standard keys: {sorted(STANDARD_KEYS)}"
            )

    def test_fdadrug_is_fda_approval(self):
        assert TOOL_REGISTRY["origene-fdadrug"][3] == "FDA_NMPA_approval"

    def test_ncbi_is_external_validation(self):
        assert TOOL_REGISTRY["origene-ncbi"][3] == "External_validation"

    def test_search_is_journal_article(self):
        assert TOOL_REGISTRY["origene-search"][3] == "Journal_article"


class TestInjectStandardType:
    """P0-1 Layer 2: _inject_standard_type 注入逻辑。"""

    def test_injects_when_type_missing(self):
        papers = [{"title": "Test", "source_type": "FDA_Drug"}]
        result = _inject_standard_type(papers, "FDA_NMPA_approval")
        assert result[0]["type"] == "FDA_NMPA_approval"

    def test_preserves_existing_type(self):
        papers = [{"title": "Test", "type": "RCT"}]
        result = _inject_standard_type(papers, "FDA_NMPA_approval")
        assert result[0]["type"] == "RCT"

    def test_empty_papers(self):
        assert _inject_standard_type([], "FDA_NMPA_approval") == []

    def test_none_type_overwritten(self):
        papers = [{"title": "Test", "type": None}]
        result = _inject_standard_type(papers, "Journal_article")
        assert result[0]["type"] == "Journal_article"


class TestExtractYear:
    """P0-4: 年份提取辅助函数。"""

    def test_extract_year_from_dict(self):
        item = {"year": 2023}
        assert _extract_year(item, "year") == 2023

    def test_extract_year_missing_returns_none(self):
        item = {"title": "No year"}
        assert _extract_year(item, "year") is None

    def test_extract_year_multiple_fields(self):
        item = {"pub_year": 2021, "year": None}
        assert _extract_year(item, "year", "pub_year") == 2021

    def test_extract_year_from_text(self):
        assert _extract_year_from_text("1. journal. 2023;vol:issue.") == 2023

    def test_extract_year_from_text_none(self):
        assert _extract_year_from_text("No year here") is None


class TestParserNoHardcodedYear:
    """P0-4: 解析器不硬编码年份 2024。"""

    def test_pubchem_no_year_returns_none(self):
        """PubChem 解析器：无年份数据 → year is None。"""
        mock_response = json.dumps({
            "PC_Compounds": [{
                "id": {"id": {"cid": 2244}},
                "props": []
            }]
        })
        papers = scp_tools._parse_pubchem_response(mock_response)
        assert papers is not None
        assert papers[0]["year"] is None

    def test_scigraph_no_year_returns_none(self):
        """SciGraph 解析器：无年份数据 → year is None。"""
        mock_response = json.dumps({
            "success": True,
            "count": 1,
            "data": [{"n": {"name": "Fluorographene", "description": "test"}}]
        })
        papers = scp_tools._parse_scigraph_response(mock_response)
        assert papers is not None
        assert papers[0]["year"] is None

    def test_opentargets_no_year_returns_none(self):
        """OpenTargets 解析器：无年份数据 → year is None。"""
        mock_response = json.dumps({
            "data": {
                "search": {
                    "hits": [{
                        "id": "ENSG00000141510",
                        "name": "TP53",
                        "description": "Tumor protein p53",
                        "entity": "target",
                        "score": 0.9
                    }]
                }
            }
        })
        papers = scp_tools._parse_opentargets_response(mock_response)
        assert papers is not None
        assert papers[0]["year"] is None

    def test_pubmed_text_extracts_year(self):
        """PubMed 文本响应：从首行提取年份。"""
        mock_response = json.dumps([
            "1. Nature. 2023;15:123. doi: 10.1038/s41586-023-12345\n\nCRISPR gene editing study\n\nAuthors: Zhang et al."
        ])
        papers = scp_tools._parse_pubmed_text_response(mock_response)
        assert papers is not None
        assert papers[0]["year"] == 2023


class TestMockPaperYear:
    """P0-4: mock paper 不再硬编码 2024。"""

    def test_mock_paper_year_none(self):
        paper = scp_tools._mock_paper("sciverse", "Patent", "test", 1)
        assert paper["year"] is None
