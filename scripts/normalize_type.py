"""证据类型归一化层（按研究设计分级，非出版 venue）。

策略：
1. DOI 前缀优先识别 venue（IEEE/ACM=会议，Nature/Elsevier=期刊）
2. 只从 title（非 abstract）判定研究设计，避免 abstract 中的词误匹配
3. 若 title 无明确研究设计信号，按 venue 兜底
"""
import re

# 研究设计模式（只匹配 title，不匹配 abstract，避免假阳性）
# 必须是非常明确的研究设计信号
STUDY_DESIGN_PATTERNS = [
    # 监管/认证
    (r"\bFDA\b|\bNMPA\b|510\(k\)|PMA|premarket approval", "FDA_NMPA_approval"),
    (r"\bCE.?mark\b|conformite europeenne", "CE_mark"),
    # 临床指南
    (r"^guideline|^practice guideline|^recommendation|^NICE guideline|^WHO guideline", "Guideline"),
    # 随机对照试验（title 必须明确写 RCT 或 randomized）
    (r"\bRCT\b|randomized controlled trial|randomised controlled trial|randomized trial", "RCT"),
    # Meta 分析 / 系统综述（title 必须明确写 meta-analysis 或 systematic review）
    (r"meta.?analysis|meta analysis", "Meta_analysis"),
    (r"systematic review|Cochrane review", "Systematic_review"),
    # 诊断准确性研究（title 必须明确写 diagnostic accuracy study）
    (r"diagnostic accuracy study|diagnostic performance evaluation", "Diagnostic_accuracy"),
    # 外部验证（title 必须明确写 external validation）
    (r"external validation|external test set validation|prospective validation", "External_validation"),
    # 队列研究
    (r"cohort study|longitudinal study|prospective cohort|retrospective cohort", "Cohort_study"),
    (r"case.control study", "Case_control"),
    # 专利
    (r"\bpatent\b|\bUS\d+|\bWO\d+|EP\d+", "Patent"),
    # 行业标准
    (r"industry standard|ISO\d+|IEEE std|GB/T", "Industry_standard"),
    # 文献综述（title 必须明确写 review）
    (r"^review|literature review|narrative review|review article|scoping review", "Literature_review"),
    # 基准测试（title 必须明确写 benchmark dataset/leaderboard）
    (r"benchmark dataset|leaderboard|shared task|competition dataset", "Benchmark_study"),
    # 案例研究
    (r"case study|case report|case series", "Case_study"),
    # 仿真/预印本
    (r"^simulation|simulated study|preprint", "Simulation"),
    # 新闻/观点
    (r"^news|^report|^blog|^press release", "News_report"),
    (r"^expert opinion|^editorial|^commentary|^perspective", "Expert_opinion"),
]

# DOI 前缀 → 默认 venue 类型（仅作为 venue 提示，非研究设计判定）
# 注意：期刊论文 ≠ 综述。只有标题明确写 review 才归 Literature_review（权重 1.5），
# 否则期刊论文归 Journal_article（权重 1.0）
DOI_VENUE_MAP = {
    "10.1109": "Conference_paper",   # IEEE 主要是会议
    "10.1145": "Conference_paper",   # ACM 主要是会议
    "10.1038": "Journal_article",    # Nature（期刊论文，非综述）
    "10.1016": "Journal_article",     # Elsevier
    "10.1126": "Journal_article",     # Science
    "10.1007": "Journal_article",     # Springer
    "10.3991": "Journal_article",     # ijoe 等
    "10.3390": "Journal_article",     # MDPI
    "10.1371": "Journal_article",     # PLOS
    "10.1186": "Journal_article",     # BMC
    "10.4108": "Journal_article",     # EAI 期刊
    "10.22214": "Journal_article",    # ijraset 期刊
    "10.1001": "Journal_article",     # JAMA / American Medical Association
    "10.3389": "Journal_article",     # Frontiers
    "10.2337": "Journal_article",     # Diabetes Care
    "10.3877": "Journal_article",     # 中华医学系列
    "10.1056": "Journal_article",     # NEJM
    "10.1161": "Journal_article",     # AHA（Circulation 等）
    "10.1002": "Journal_article",     # Wiley
    "10.1093": "Journal_article",     # Oxford University Press
    "10.1097": "Journal_article",     # Wolters Kluwer / Lippincott
}

# source_type 关键词 → venue 类型（当 DOI 无法识别时）
# 第三层防御：即使 call_gateway 未注入 type 字段，normalize_type 也能把
# SCP 数据库工具的 source_type 映射到标准证据类型键，避免落入 default_weight(0.3)。
SOURCE_TYPE_VENUE_MAP = {
    # 已有：出版 venue 关键词
    "conference": "Conference_paper",
    "symposium": "Conference_paper",
    "proceedings": "Conference_paper",
    "workshop": "Conference_paper",
    "journal": "Journal_article",      # 期刊论文，非综述
    "transactions": "Journal_article", # 期刊论文
    "preprint": "Simulation",
    # SCP 数据库工具 source_type → 标准证据类型键（双保险）
    "fda_drug": "FDA_NMPA_approval",
    "fda_nmpa": "FDA_NMPA_approval",
    "ncbi_gene": "External_validation",
    "ncbi_database": "External_validation",
    "chembl_activity": "Journal_article",
    "chembl_compound": "Journal_article",
    "pubchem_compound": "Journal_article",
    "opentargets": "Meta_analysis",      # 覆盖 OpenTargets_target / OpenTargets_disease
    "scholar_kg": "Systematic_review",
    "knowledge_graph": "Industry_standard",
    "semantic_search": "Journal_article",
    "academic_paper": "Journal_article",
    "pubmed_literature": "Journal_article",
    "mcp_data": "Journal_article",
}


def normalize_type(source_type: str = "", title: str = "",
                   abstract: str = "", doi: str = "") -> str:
    """归一化证据类型。

    策略：
    1. 只从 title 判定研究设计（避免 abstract 假阳性）
    2. 若 title 无明确研究设计信号，用 DOI 前缀决定 venue 类型
    3. 若 DOI 也无法识别，用 source_type 关键词
    4. 都不行 → Unknown
    """
    # Step 1: 只从 title 判定研究设计
    title_lower = (title or "").lower()
    for pattern, ev_type in STUDY_DESIGN_PATTERNS:
        if re.search(pattern, title_lower, re.I):
            return ev_type

    # Step 2: DOI 前缀决定 venue 类型
    if doi:
        for prefix, ev_type in DOI_VENUE_MAP.items():
            if doi.lower().startswith(prefix):
                return ev_type

    # Step 3: source_type 关键词
    source_lower = (source_type or "").lower()
    for keyword, ev_type in SOURCE_TYPE_VENUE_MAP.items():
        if keyword in source_lower:
            return ev_type

    # Step 4: 兜底
    return "Unknown"


def validate_doi(doi: str = "") -> tuple:
    """检测并修正 DOI 的双层前缀问题，供其他脚本复用。

    部分数据源会返回形如 `10.1145/10.1145/3644116.3644178` 的 DOI（前缀重复）。
    本函数检测此类异常，去掉第二个前缀，返回修正后的 DOI 和是否发生修正的标志。

    与 search_papers.py 中的 _validate_doi_format 逻辑一致，独立实现以解耦依赖。

    参数:
        doi: 原始 DOI 字符串，可能为空。

    返回:
        (corrected_doi, format_error)
        - 空 DOI 直接返回原值，format_error=False
        - 命中双层前缀模式 `^10.\\d+/10.\\d+/` 时修正为单层前缀，format_error=True
        - 否则原样返回，format_error=False
    """
    # 空 DOI 不做处理
    if not doi:
        return doi, False
    # 匹配双层前缀，如 10.1145/10.1145/，捕获第一层前缀用于回填
    match = re.match(r"^(10\.\d+/)10\.\d+/", doi)
    if match:
        # 用第一层前缀 + 去掉第二层前缀后的剩余部分
        corrected = match.group(1) + doi[match.end():]
        return corrected, True
    return doi, False
