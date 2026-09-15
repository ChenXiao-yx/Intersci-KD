"""normalize_type 类型归一化测试。

覆盖 P0-1 第三层防御：SCP 数据库工具 source_type → 标准证据类型键。
"""
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from normalize_type import normalize_type


class TestSourceTypeVenueMap:
    """SCP 数据库工具 source_type → 标准证据类型键映射。"""

    def test_fda_drug_maps_to_fda_approval(self):
        assert normalize_type(source_type="FDA_Drug") == "FDA_NMPA_approval"

    def test_ncbi_gene_maps_to_external_validation(self):
        assert normalize_type(source_type="NCBI_gene") == "External_validation"

    def test_chembl_activity_maps_to_journal(self):
        assert normalize_type(source_type="ChEMBL_activity") == "Journal_article"

    def test_pubchem_compound_maps_to_journal(self):
        assert normalize_type(source_type="PubChem_compound") == "Journal_article"

    def test_opentargets_maps_to_meta_analysis(self):
        assert normalize_type(source_type="OpenTargets_target") == "Meta_analysis"

    def test_scholar_kg_maps_to_systematic_review(self):
        assert normalize_type(source_type="Scholar_KG") == "Systematic_review"

    def test_knowledge_graph_maps_to_industry_standard(self):
        assert normalize_type(source_type="Knowledge_Graph") == "Industry_standard"

    def test_semantic_search_maps_to_journal(self):
        assert normalize_type(source_type="semantic_search") == "Journal_article"

    def test_academic_paper_maps_to_journal(self):
        assert normalize_type(source_type="Academic_paper") == "Journal_article"

    def test_pubmed_literature_maps_to_journal(self):
        assert normalize_type(source_type="PubMed_literature") == "Journal_article"

    def test_mcp_data_maps_to_journal(self):
        assert normalize_type(source_type="MCP_data") == "Journal_article"


class TestStudyDesignPatterns:
    """研究设计模式从 title 判定。"""

    def test_rct_from_title(self):
        assert normalize_type(title="A randomized controlled trial of CRISPR") == "RCT"

    def test_systematic_review_from_title(self):
        assert normalize_type(title="Systematic review of flexible sensors") == "Systematic_review"

    def test_meta_analysis_from_title(self):
        assert normalize_type(title="Meta-analysis of CGM devices") == "Meta_analysis"

    def test_fda_from_title(self):
        assert normalize_type(title="FDA approval of glucose monitor") == "FDA_NMPA_approval"

    def test_unknown_returns_unknown(self):
        assert normalize_type(source_type="", title="Some random title") == "Unknown"


class TestDOIVenueMap:
    """DOI 前缀 → venue 类型。"""

    def test_ieee_maps_to_conference(self):
        assert normalize_type(doi="10.1109/SENSOR.2023.12345") == "Conference_paper"

    def test_nature_maps_to_journal(self):
        assert normalize_type(doi="10.1038/s41586-024-01234") == "Journal_article"
