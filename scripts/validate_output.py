"""InterSci-KD 输出校验器。纯标准库，零依赖。

检查项（对应方案验收标准）：
  1. 首行第零章标题存在（前 20 字含「第零章：跨学科全景扫描」）
  2. 三选一结论存在（第九章含 优先整合/持续追踪/暂时搁置 之一）
  3. 有效性状态非空（第十章证据表 6 列，有效性状态列不得留空）
  4. 连续 3 处判断句无标签 → 失败（【确证】【推断】【无法判断】）
  5. 免责声明原文存在（文末原样附加，不得改写）
  6. L0 卡片结论与审计层（第九章/L3 JSON）结论一致
  7. §14 矩阵强校验：黄区不得写"优先整合"；红区不得写"优先整合/持续追踪"；有效论文为0不得写"优先整合"
  8. 有效性状态一致性：有 DOI/PMID 不得标"无法验证"（除非注明解析失败）
  9. 第十章 DOI 去重（证据索引表 DOI 列无重复）
  10. DOI 格式校验（无 10.x/10.x/ 双层前缀错误）
  11. 计分明细子表（L2/L3，第十章含"计分明细"或"基础权重"+"加权分"）
  12. 检索审计段（L2/L3，含"检索审计"或"检索式"+"数据库"+"去重策略"）
  13. 年份/卷期一致性（L2/L3）：标题年份与 DOI 卷期年份不得矛盾
  14. 计分明细加和一致性（L2/L3）：加权分列之和 = 合计行值
  15. 检索审计完整性（L2/L3）：检索式/数据库/时间范围/去重策略/筛选流程 5 字段全有
  16. 证据分数格式（L0）：`证据：{强/中/弱} 核心证据分 X.X（满分 8.0）`，等级标签与分数一致
  17. 支撑结论去同质化（L2/L3）：第十章"支撑结论"列连续 3 行不得完全相同
  18. 无依据预测标注（全档位）：含 4 周/2026-2029/1-2 人/年均 50+ 等关键词必须有【推断】或引用
  19. 内部黑话检测（全档位）：禁止 max_single/base_weight/search_papers.py 等内部术语出现在用户输出
  20. 指令性文字泄漏检测（全档位）：两层短语——严格短语全文扫描，免责区专属短语仅在「## 免责声明」后检查
  21. 计分签名校验（全档位，提供 score_json 或文本含 L3 JSON 审计日志时生效）：scored_by 必须
      为 score_evidence.py，防 LLM 手写计分结果绕过确定性计分器（P1-1）

档位识别（v4.4.1 起 --level 为必填参数，不再从交付文本解析）：
  - 调用必须显式传 --level L0/L1/L2/L3
  - L2/L3 完整审计：跑 19 项（第 16 项证据分数仅 L0；第 13 项年份一致性为警告不阻断）
  - L0 卡片：跑 5/6/7/8/9/10/16/18/19/20/21 共 11 项（不校验第零章与十章专属项）
  - L1 五块：跑 5/6/7/8/9/10/18/19/20/21 共 10 项

结果三态：每条结果 ok 为 true（通过）/false（硬失败）/"warning"（警告不阻断）/
"skipped"（档位不适用）；JSON 顶层 hard_failures 只计 false，warnings 计警告数，
警告场景退出码仍为 0。

用法：
    python scripts/validate_output.py --input <简报.md> --level L2 [--json score.json]
    python scripts/validate_output.py --input examples/full_output_golden.md --level L2 \
        --json <(python scripts/score_evidence.py ...) --pretty

退出码：0=全部通过；1=有硬失败；2=命令行错误。
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

from config_loader import (
    get_validity_states, get_internal_jargon, get_conclusion_options,
    get_disclaimer_phrases, get_internal_jargon_word_boundary,
    get_internal_jargon_contextual,
)


# ──────────────────────────────────────────────────────────────────────
# 规则常量
# ──────────────────────────────────────────────────────────────────────

CHAPTER_ZERO_TITLE = "第零章：跨学科全景扫描"
# 单一事实源：从 scripts/config/*.json 加载，避免文档/代码/配置三处漂移
CONCLUSION_OPTIONS = get_conclusion_options()
VALIDITY_STATES = get_validity_states()
INTERNAL_JARGON = get_internal_jargon()
# P0-1：三类黑话匹配策略（短英文词词边界 / 上下文词前后文约束 / 其余子串）
_WORD_BOUNDARY_JARGON = set(get_internal_jargon_word_boundary())
_CONTEXTUAL_JARGON = get_internal_jargon_contextual()
LABELS = ("【确证】", "【推断】", "【无法判断】")
LABEL_SYMBOL_MAP = {"✅": "【确证】", "🔶": "【推断】", "❓": "【无法判断】"}

_disclaimer = get_disclaimer_phrases()
DISCLAIMER_PREFIX = _disclaimer["full_prefix"]
DISCLAIMER_KEY_PHRASES = tuple(_disclaimer["full_key_phrases"])

# L0 精简版免责声明（30 秒卡片专用，完整版在 L1/L2/L3）
L0_DISCLAIMER_PREFIX = _disclaimer["l0_prefix"]
L0_DISCLAIMER_KEY_PHRASES = tuple(_disclaimer["l0_key_phrases"])

# §14 矩阵强校验
LEVEL_GREEN = "green"
LEVEL_YELLOW = "yellow"
LEVEL_RED = "red"


# ──────────────────────────────────────────────────────────────────────
# 档位感知
# ──────────────────────────────────────────────────────────────────────

LEVEL_L0 = "L0"
LEVEL_L1 = "L1"
LEVEL_L2 = "L2"
LEVEL_L3 = "L3"

# 各档位适用的校验项编号（1-based）
# v4.4.1：--level 必填，不再读取交付物内嵌档位标记
# L0 卡片不校验第零章（第 1 项仅 L2/L3）；9（DOI 去重）/10（DOI 格式）对 L0/L1 也跑
# 11（计分明细）/12（检索审计）仅 L2/L3；16（证据分数）仅 L0
# 13（年份/卷期一致性）为警告级：在 L2/L3 执行但不计硬失败
# 20（指令性文字泄漏）全档位执行（P1-2）
# 21（计分签名）全档位执行（P1-1）：有 score_json 或 L3 JSON 审计日志时生效，否则放行
APPLICABLE_CHECKS = {
    LEVEL_L0: {5, 6, 7, 8, 9, 10, 16, 18, 19, 20, 21},
    LEVEL_L1: {5, 6, 7, 8, 9, 10, 18, 19, 20, 21},
    LEVEL_L2: {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 19, 20, 21},
    LEVEL_L3: {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 19, 20, 21},
}

# 警告级校验项：执行但不阻断交付（不计入 hard_failures）
WARNING_ONLY_CHECKS = {13}


# ──────────────────────────────────────────────────────────────────────
# 校验项实现
# ──────────────────────────────────────────────────────────────────────

def parse_markdown_table(section, table_index=0):
    """解析 Markdown 表格，返回行×列二维列表。跳过表头分隔行。

    P1-3：替代脆弱的 `row.strip("|").split("|")`，统一表格解析逻辑。
    table_index 指定第几个表格（0-based），默认第一个。
    """
    tables = []
    current_rows = []
    in_table = False
    for line in section.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            if in_table and current_rows:
                tables.append(current_rows)
                current_rows = []
                in_table = False
            continue
        # 分隔行（|---|---| 或 |:--:|---| 等）
        if re.match(r'^\|[\s\-:|]+\|$', s):
            in_table = True
            continue
        # 数据行
        in_table = True
        cells = [c.strip() for c in s.strip("|").split("|")]
        current_rows.append(cells)
    if in_table and current_rows:
        tables.append(current_rows)
    if table_index >= len(tables):
        return []
    return tables[table_index]


def check_chapter_zero_first(text, level=None):
    """1. 首行第零章标题。返回 (ok, detail)。

    允许 front-matter（H1 标题、引用块元信息、`---` 分隔线），
    第一个 `## ` 二级标题必须是「第零章：跨学科全景扫描」。

    第五点评⑤：is_composite 特例分支已废除——三档复合演示移入 composite_demo.md（不参与 CI），
    full/card/brief 三份黄金样本各为单档，--level 语义纯正：L2 文本必须以第零章开篇。
    """
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        # 跳过文档级 H1 标题（# 开头但非 ##）
        if s.startswith("# ") and not s.startswith("## "):
            continue
        # 跳过 front-matter 引用块（> 开头的元信息）
        if s.startswith(">"):
            continue
        # 跳过分隔线
        if s == "---":
            continue
        # 第一个 `## ` 二级标题
        if s.startswith("## "):
            if CHAPTER_ZERO_TITLE in s[:60]:
                return True, "首个 ## 二级标题为第零章"
            return False, f"首个二级标题不是第零章，实际: {s[:60]!r}"
        # 任意其他非空行：可能是元信息或正文，跳过 front-matter 内的列表/说明
        # （如 `> - **输入**：` 已被前述 > 跳过）
        # 但若遇到非 front-matter 内容行（既不是 ##、>、---、空行），且不是第零章，则失败
        return False, f"首行前40字无「{CHAPTER_ZERO_TITLE}」，实际首行: {s[:60]!r}"
    return False, "文件为空"


def check_three_choice_conclusion(text: str) -> tuple[bool, str]:
    """2. 第九章三选一结论存在。

    条件分支容错：L0 模板允许"主结论 + 条件分支说明"格式，
    条件分支须放在引用块（> 开头的行）中。主结论行只允许一个结论。

    P0-2 修复：L2 模板第九章主结论习惯用引用块渲染（`> **结论：…**`），
    此类行视为主结论行；引用块内的「结论依据」「条件分支」等仍排除，
    避免把条件分支当主结论或漏判引用块主结论。
    """
    # 定位第九章区域
    m = re.search(r'##\s*第九章[:：]?', text)
    if not m:
        return False, "未找到第九章标题"
    # 第九章到第十章或文末
    start = m.end()
    m10 = re.search(r'##\s*第十章[:：]?', text[start:])
    end = start + m10.start() if m10 else len(text)
    chapter9 = text[start:end]
    # 主结论候选行：全部非引用块行 + 引用块内「> **结论：」格式的主结论行
    main_lines = []
    for line in chapter9.splitlines():
        s = line.strip()
        if s.startswith(">"):
            if re.match(r'^>\s*\*\*结论\s*[：:]', s):
                main_lines.append(s)
            continue
        main_lines.append(line)
    main_text = "\n".join(main_lines)
    found = [c for c in CONCLUSION_OPTIONS if c in main_text]
    if not found:
        # 检查是否有结论仅在引用块条件分支中
        found_in_quotes = [c for c in CONCLUSION_OPTIONS if c in chapter9]
        if found_in_quotes:
            return False, "第九章结论仅出现在条件分支中，缺少主结论行"
        return False, "第九章未找到结论（优先整合/持续追踪/暂时搁置/证据不足）"
    if len(found) > 1:
        return False, f"第九章出现多个主结论选项: {found}，应唯一（条件分支请用引用块格式）"
    return True, f"第九章结论: {found[0]}"


def extract_conclusion(text: str) -> Optional[str]:
    """从文本中提取三选一结论。返回规范化的结论字符串或 None。

    L0 卡片可能含条件分支（如"若选A→持续追踪，若选B→暂时搁置"），
    此时取**首次出现**的结论作为主结论（与 L0 模板"结论第一行"规则一致）。
    """
    m = re.search(r'##\s*第九章[:：]?(.*?)(?=##\s*第十章[:：]?|\Z)', text, re.DOTALL)
    search_text = m.group(1) if m else text
    # 收集所有匹配及其位置，取最先出现者
    matches = []
    for c in CONCLUSION_OPTIONS:
        idx = search_text.find(c)
        if idx != -1:
            matches.append((idx, c))
    if not matches:
        return None
    matches.sort()
    return matches[0][1]


def check_validity_table(text):
    """3. 第十章证据表有效性状态非空。

    空表场景放行：若第十章只有表头无数据行，但存在兜底声明
    （"无可用文献证据"/"无可用文献"等），则放行；否则硬失败。
    """
    m = re.search(r'##\s*第十章[:：]?(.*?)(?=##\s|\Z)', text, re.DOTALL)
    if not m:
        return False, "未找到第十章"
    ch10 = m.group(1)
    # 只解析证据索引表（第一个表），计分明细子表（第二个表）跳过
    # 遇到"计分明细"关键词后停止，避免把计分明细子表当证据行
    evidence_section = ch10.split("**计分明细**")[0] if "**计分明细**" in ch10 else ch10
    # 找表格行（以 | 开头，非表头分隔行）
    rows = [r.strip() for r in evidence_section.splitlines() if r.strip().startswith("|") and "---" not in r]
    if not rows:
        return False, "第十章无证据表"
    # 第一行是表头，跳过
    data_rows = rows[1:]
    if not data_rows:
        # 空表场景：检查是否有兜底声明
        fallback_patterns = (
            "无可用文献证据", "无可用文献", "本简报完全基于 LLM 训练数据",
            "检索结果为空", "空检索兜底",
        )
        has_fallback = any(p in ch10 for p in fallback_patterns)
        if has_fallback:
            return True, "空证据表 + 兜底声明，放行"
        return False, "第十章证据表无数据行且无兜底声明（空检索场景必须声明「无可用文献证据」）"
    issues = []
    for i, row in enumerate(data_rows, 1):
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) < 6:
            issues.append(f"第{i}行列数<6: {row[:50]!r}")
            continue
        validity = cells[4]
        if not validity:
            issues.append(f"第{i}行有效性状态为空")
        elif validity not in VALIDITY_STATES:
            issues.append(f"第{i}行有效性状态非枚举值: {validity!r}")
    if issues:
        return False, "; ".join(issues)
    return True, f"证据表 {len(data_rows)} 行，有效性状态全部合法"


def check_label_density(text):
    """4. 连续 3 处判断句无标签 → 失败。"""
    # 简化策略：按段落扫描，判断句=含"是/可/将/会/应/可能"等动词的陈述句
    # 连续 3 段无任何标签则失败
    # 更稳健：扫所有非引用、非表格、非标题的正文段落
    body = re.sub(r'```.*?```', '', text, flags=re.DOTALL)  # 去代码块
    body = re.sub(r'^>.*$', '', body, flags=re.MULTILINE)  # 去引用块
    body = re.sub(r'^\|.*$', '', body, flags=re.MULTILINE)  # 去表格行
    body = re.sub(r'^#{1,6}\s.*$', '', body, flags=re.MULTILINE)  # 去标题

    paragraphs = [p.strip() for p in body.split('\n\n') if p.strip()]
    # 标签计数（含符号双轨）
    def has_label(p):
        for lab in LABELS:
            if lab in p:
                return True
        for sym in LABEL_SYMBOL_MAP:
            if sym in p:
                return True
        return False

    consecutive_no_label = 0
    max_streak = 0
    first_violation = None
    for p in paragraphs:
        # 跳过纯短句（<15 字，可能是列表项的延续）
        if len(p) < 15:
            continue
        if has_label(p):
            consecutive_no_label = 0
        else:
            consecutive_no_label += 1
            if consecutive_no_label >= 3 and first_violation is None:
                first_violation = p[:60]
            if consecutive_no_label > max_streak:
                max_streak = consecutive_no_label
    if max_streak >= 3:
        return False, f"连续 {max_streak} 段判断无标签，首次违反: {first_violation!r}"
    return True, f"标签密度正常，最长无标签连续段={max_streak}"


def check_disclaimer(text, level=None):
    """5. 免责声明原文存在。

    免责声明必须出现在文末区域（后 1/3）。
    L0 使用精简版（一句话），L1/L2/L3 使用完整版。
    """
    last_third = text[len(text) * 2 // 3:]
    if level == LEVEL_L0:
        # L0 精简版：只需前缀 + 1 个关键短语
        if L0_DISCLAIMER_PREFIX not in last_third:
            return False, f"L0 文末免责声明缺少开头「{L0_DISCLAIMER_PREFIX}」"
        missing = [p for p in L0_DISCLAIMER_KEY_PHRASES if p not in last_third]
        if missing:
            return False, f"L0 文末免责声明缺少关键短语: {missing}"
        return True, "L0 精简版免责声明完整（位于文末区域）"
    # L1/L2/L3 完整版：前缀 + 4 个关键短语
    missing = [p for p in DISCLAIMER_KEY_PHRASES if p not in last_third]
    if missing:
        return False, f"文末区域免责声明缺少关键短语: {missing}"
    if DISCLAIMER_PREFIX not in last_third:
        return False, f"文末区域免责声明开头「{DISCLAIMER_PREFIX}」缺失"
    return True, "免责声明原文完整（位于文末区域）"


def _chapter7_has_unresolved_conflict(text):
    """检测第七章是否存在未消解的核心冲突（结论判定矩阵 green+冲突分支判定依据）。

    (a) 完整报告（含 ## 第七章 区域）：在第七章范围内检测
        "冲突"关键词 + 未消解标记（"未消解"/"未解决"/"尚未消解"/"悬而未决"等）。
        注意："搁置"是第七章"搁置条件"的标准要素，不是未消解标记，不得纳入。
    (b) L0/L1 精炼视图（无第七章区域）：按行检测"冲突"与未消解标记同现
        （如"强证据 + 第七章未消解冲突"），用于推导与 L2 同源的持续追踪结论。

    仅在第七章范围内搜索完整报告，避免误判其他章节的"冲突"提及。
    """
    m = re.search(r'##\s*第七章[:：]?(.*?)(?=##\s*第八章[:：]?|\Z)', text, re.DOTALL)
    if m:
        ch7 = m.group(1)
        if "冲突" not in ch7:
            return False
        # P1-16：扩展未消解冲突关键词覆盖"存在分歧"、"结论相左"、"证据冲突"、"未能调和"
        return any(kw in ch7 for kw in (
            "未消解", "未解决", "尚未消解", "悬而未决",
            "存在分歧", "结论相左", "证据冲突", "未能调和",
        ))
    # (b) 精炼视图回退：L0 卡片/L1 五块不含章节结构，按行检测同现信号
    unresolved_markers = (
        "未消解", "未解决", "尚未消解", "悬而未决",
        "存在分歧", "结论相左", "未能调和",
    )
    for line in text.splitlines():
        if "冲突" in line and any(kw in line for kw in unresolved_markers):
            return True
    return False


def check_l0_audit_consistency(text, score_json):
    """6. L0 卡片结论与审计层 JSON 结论一致。

    两种模式：
    A. 间接推导（默认）：从 score_json 的 level/valid_count 推导期望结论，与文本结论比较。
    B. 直接比较（显式 --l0-file/--l3-file）：从 L3 JSON 的 conclusion 字段直接取结论，
       与 L0 卡片文本结论比较。模式 B 优先，若 score_json 含 conclusion 字段则用之。
    """
    if score_json is None:
        return True, "未提供 score JSON，跳过 L0-审计层一致性检查"
    # 从文本提取结论
    text_conclusion = extract_conclusion(text)
    if text_conclusion is None:
        return False, "文本中未找到三选一结论，无法与 JSON 比较"

    # 模式 B：直接比较（score_json 含 conclusion 字段）
    json_conclusion = score_json.get("conclusion")
    if json_conclusion is not None:
        # 规范化：JSON 可能用简短形式，补全"建议"前缀
        if not json_conclusion.startswith("建议"):
            json_conclusion = "建议" + json_conclusion
        if text_conclusion == json_conclusion:
            return True, f"L0-L3 直接比较一致: {text_conclusion}"
        return False, f"L0-L3 直接比较不一致: L0 文本={text_conclusion!r}, L3 JSON.conclusion={json_conclusion!r}"

    # 模式 A：间接推导
    level = score_json.get("level", "")
    valid_count = score_json.get("valid_evidence_count", score_json.get("source_count", 0))
    rule2 = score_json.get("rule2_triggered", False)
    ch7_conflict = _chapter7_has_unresolved_conflict(text)

    # 判定顺序必须与 score_evidence.py 一致：insufficient 最优先（门槛未达直接定论），
    # 其次才是 rule2/valid_count、red/yellow/green。
    # 否则空检索场景会同时命中 level=="insufficient" 与 valid_count==0，
    # 被误判为"建议暂时搁置"，与计分器的"证据不足"冲突。
    if level == "insufficient":
        # 证据不足：不能给出方向性结论（无论 valid_count 是否为 0）
        expected = "证据不足，无法给出方向性结论"
    elif rule2 or valid_count == 0:
        expected = "建议暂时搁置"
    elif level == LEVEL_RED:
        # 红区+valid≥3 允许持续追踪；红区+valid<3 搁置
        expected = "建议持续追踪" if valid_count >= 3 else "建议暂时搁置"
    elif level == LEVEL_YELLOW:
        expected = "建议持续追踪"  # yellow 默认持续追踪
    elif level == LEVEL_GREEN:
        # green + 第七章未消解冲突 → 持续追踪（判定矩阵 green+冲突分支）
        # 否则 green + valid>=3 → 优先整合；valid<3 → 持续追踪
        if ch7_conflict:
            expected = "建议持续追踪"
        else:
            expected = "建议优先整合" if valid_count >= 3 else "建议持续追踪"
    else:
        return True, f"JSON level={level!r} 未知，跳过矩阵校验"

    if text_conclusion != expected:
        return False, f"结论不一致: 文本={text_conclusion!r}, 判定矩阵期望={expected!r} (level={level}, valid={valid_count}, rule2={rule2}, ch7_conflict={ch7_conflict})"
    return True, f"结论一致: {text_conclusion} (level={level}, valid={valid_count}, ch7_conflict={ch7_conflict})"


def check_matrix_strong_validation(text, score_json):
    """7. §14 矩阵强校验：黄区不得写优先整合等。"""
    if score_json is None:
        return True, "未提供 score JSON，跳过矩阵强校验"
    level = score_json.get("level", "")
    valid_count = score_json.get("valid_evidence_count", score_json.get("source_count", 0))
    rule2 = score_json.get("rule2_triggered", False)

    text_conclusion = extract_conclusion(text)
    if text_conclusion is None:
        return True, "文本无结论，跳过矩阵强校验"

    # 黄区不得写优先整合（insufficient 已在校验6专属分支处理；
    # threshold_note 自 v4.4.1 起只承载 insufficient 说明，不再作为降级信号）
    if level == LEVEL_YELLOW and text_conclusion == "建议优先整合":
        return False, f"§14.1 违反: level=yellow 但结论=优先整合；黄区严禁优先整合"
    # 红区 + 有效论文 <3 不得写优先整合或持续追踪；红区 + valid≥3 允许持续追踪
    if level == LEVEL_RED and valid_count < 3 and text_conclusion in ("建议优先整合", "建议持续追踪"):
        return False, f"§14.1 违反: level=red 且 valid={valid_count}<3 但结论={text_conclusion}；红区+有效论文<3 只能写暂时搁置"
    if level == LEVEL_RED and text_conclusion == "建议优先整合":
        return False, f"§14.1 违反: level=red 但结论=优先整合；红区严禁优先整合"
    # 有效论文为0不得写优先整合
    if (rule2 or valid_count == 0) and text_conclusion == "建议优先整合":
        return False, f"§14.1 违反: valid_evidence_count=0/rule2 但结论=优先整合；无有效证据严禁优先整合"
    return True, "§14 矩阵强校验通过"


def check_validity_doi_consistency(text):
    """8. 有效性状态一致性：有 DOI 不得标"无法验证"（除非注明解析失败）。"""
    m = re.search(r'##\s*第十章[:：]?(.*?)(?=##\s|\Z)', text, re.DOTALL)
    if not m:
        return True, "无第十章，跳过 DOI 一致性"
    ch10 = m.group(1)
    rows = [r.strip() for r in ch10.splitlines() if r.strip().startswith("|") and "---" not in r]
    if len(rows) < 2:
        return True, "证据表无数据，跳过"
    issues = []
    for i, row in enumerate(rows[1:], 1):
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) < 6:
            continue
        source = cells[3]  # 来源列
        validity = cells[4]
        # 检测 DOI/PMID
        has_doi = bool(re.search(
            r'(?:doi[:\s]*|https?://doi\.org/)?10\.\d{4,}/|PMID:?\s*\d',
            source, re.IGNORECASE
        ))
        if has_doi and validity == "无法验证":
            # 检查是否注明解析失败
            note = cells[5] if len(cells) > 5 else ""
            if "解析失败" not in note and "解析失败" not in row:
                issues.append(f"第{i}行有 DOI/PMID 但标「无法验证」且未注明解析失败")
    if issues:
        return False, "; ".join(issues)
    return True, "DOI/有效性一致性通过"


def _extract_dois_from_row(row: str) -> list:
    """从表格行提取 DOI 列表（归一化，同一 DOI 只计一次）。

    P0-2 修复：`[10.xxx](https://doi.org/10.xxx)` 链接形式中，
    链接文字与 URL 是同一 DOI 的两种写法，旧逻辑双计导致误报"重复 DOI"。

    提取顺序（先到先得，重复跳过）：
    1. markdown 链接 URL：`...(.../10.xxx/yyy...)`
    2. markdown 链接文字：`[10.xxx/yyy](...)`
    3. 裸文本 DOI：`10.xxx/yyy`
    """
    dois = []
    # 1. markdown 链接的 URL 部分（https://doi.org/10.xxx/...）
    for m in re.finditer(r'\]\(https?://doi\.org/(10\.[^\s\)]+)', row):
        d = m.group(1)
        if d not in dois:
            dois.append(d)
    # 2. markdown 链接文字部分（[10.xxx/yyy](...)）
    for m in re.finditer(r'\[(10\.\d{4,}/[^\]]+)\]\(', row):
        d = m.group(1)
        if d not in dois:
            dois.append(d)
    # 3. 裸文本 DOI（含尚未提取的）
    for m in re.finditer(r'10\.\d{4,}/[^\s\)\]]+', row):
        d = m.group(0)
        if d not in dois:
            dois.append(d)
    return dois


def check_doi_dedup(text):
    """9. 第十章证据索引表 DOI 去重。

    从第十章表格中提取所有 DOI（匹配 10.x/xxx 模式），
    若有重复 DOI 返回失败；空表或无 DOI 放行。

    P0-2 修复：同一 DOI 的链接文字与 URL 双形式不再双计。
    归一化提取逻辑见 _extract_dois_from_row。
    """
    m = re.search(r'##\s*第十章[:：]?(.*?)(?=##\s|\Z)', text, re.DOTALL)
    if not m:
        return True, "无第十章，跳过"
    ch10 = m.group(1)
    rows = [r.strip() for r in ch10.splitlines() if r.strip().startswith("|") and "---" not in r]
    if len(rows) < 2:
        return True, "跳过（无 DOI）"
    all_dois = []
    for row in rows[1:]:
        all_dois.extend(_extract_dois_from_row(row))
    if not all_dois:
        return True, "跳过（无 DOI）"
    # 检查重复（保持首次出现顺序）
    seen = set()
    dups = []
    for doi in all_dois:
        if doi in seen and doi not in dups:
            dups.append(doi)
        seen.add(doi)
    if dups:
        return False, f"第十章 DOI 重复：{', '.join(dups)}"
    return True, "DOI 无重复"


def check_doi_format(text):
    """10. DOI 格式校验：检测 10.x/10.x/ 双层前缀错误。

    正常 DOI 形如 10.xxx/yyy；双层前缀 10.xxx/10.xxx/ 属格式错误。
    """
    # 匹配双层前缀 10.xxx/10.xxx/
    m = re.search(r'10\.\d+/10\.\d+/', text)
    if m:
        # 提取完整错误 DOI 用于报错信息
        full = re.search(r'10\.\d+/10\.\d+/[^\s\)]+', text)
        doi_str = full.group(0) if full else m.group(0)
        return False, f"DOI 格式错误（双层前缀）：{doi_str}"
    return True, "DOI 格式正常"


def check_scoring_details(text, level):
    """11. 计分明细子表校验（仅 L2/L3）。

    L0/L1 跳过；L2/L3 第十章必须含"计分明细"子表，
    判定关键词："计分明细" 或 "基础权重"+"加权分"。
    """
    if level in (LEVEL_L0, LEVEL_L1):
        return True, f"档位={level} 跳过计分明细检查"
    m = re.search(r'##\s*第十章[:：]?(.*?)(?=##\s|\Z)', text, re.DOTALL)
    if not m:
        return False, f"{level} 缺少计分明细子表"
    ch10 = m.group(1)
    # 判定子表存在：含"计分明细" 或 同时含"基础权重"和"加权分"
    has_scoring = ("计分明细" in ch10) or ("基础权重" in ch10 and "加权分" in ch10)
    if not has_scoring:
        return False, f"{level} 缺少计分明细子表"
    return True, "计分明细子表存在"


def check_search_audit(text, level):
    """12. 检索审计段校验（仅 L2/L3）。

    L0/L1 跳过；L2/L3 必须含"检索审计"段，
    判定关键词："检索审计" 或 "检索式"+"数据库"+"去重策略"。
    """
    if level in (LEVEL_L0, LEVEL_L1):
        return True, f"档位={level} 跳过检索审计检查"
    # 判定检索审计段存在：含"检索审计" 或 同时含三个关键词
    has_audit = ("检索审计" in text) or (
        "检索式" in text and "数据库" in text and "去重策略" in text
    )
    if not has_audit:
        return False, f"{level} 缺少检索审计段"
    return True, "检索审计段存在"


# ──────────────────────────────────────────────────────────────────────
# 校验项 13-18（v2 后置硬门禁，覆盖用户反馈的 7 类硬伤）
# ──────────────────────────────────────────────────────────────────────

def check_year_volume_consistency(text, level):
    """13. 年份/卷期一致性校验（仅 L2/L3）。

    扫描第十章证据表，对每条论文：
    - 从标题列提取 4 位年份（如 (2025) 中的 2025）
    - 从来源列（DOI）提取卷期字段中嵌入的 4 位年份（如 10.xxx/2024.xxx 或 journal.2024.01）
    - 若标题年份与 DOI 中的年份矛盾（差≥1 年），报硬失败

    若 DOI 不含可识别年份，跳过该论文（不报失败）。
    """
    if level in (LEVEL_L0, LEVEL_L1):
        return True, f"档位={level} 跳过 year_volume 校验"
    m = re.search(r'##\s*第十章[:：]?(.*?)(?=##\s|\Z)', text, re.DOTALL)
    if not m:
        return True, "无第十章，跳过"
    ch10 = m.group(1)
    # 只解析证据索引表（"计分明细"前的第一个表）
    evidence_section = ch10.split("**计分明细**")[0] if "**计分明细**" in ch10 else ch10
    rows = [r.strip() for r in evidence_section.splitlines() if r.strip().startswith("|") and "---" not in r]
    if len(rows) < 2:
        return True, "证据表无数据，跳过"
    issues = []
    for i, row in enumerate(rows[1:], 1):
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) < 6:
            continue
        title = cells[1]
        source = cells[3]
        # 从标题提取 4 位年份（取最后一个，如 "Title (2024) ..." 取 2024）
        title_years = re.findall(r'\b(20\d{2})\b', title)
        if not title_years:
            continue
        title_year = int(title_years[-1])
        # 从 DOI/来源提取所有 4 位年份（如 10.xxx/2024.xxx 或 .2024.）
        source_years = re.findall(r'(20\d{2})', source)
        if not source_years:
            continue
        # 标题年份是否在 DOI 所有年份集合中——不在才算矛盾
        # 这能正确处理多年份 DOI（如 10.1007/2023.2024.xxx 含两个年份）
        source_year_set = {int(y) for y in source_years}
        if title_year not in source_year_set:
            issues.append(f"第{i}行标题年份 {title_year} 与 DOI 年份 {sorted(source_year_set)} 矛盾：{title[:40]!r}")
    if issues:
        return False, "; ".join(issues)
    return True, "year_volume 一致性通过"


def check_scoring_details_sum(text, level):
    """14. 计分明细加和一致性校验（仅 L2/L3）。

    在第十章"计分明细"子表中：
    - 解析每行的"加权分"列（最后一列）
    - 求和
    - 比对"合计"行的数值
    - 若和不等于合计值，报硬失败
    """
    if level in (LEVEL_L0, LEVEL_L1):
        return True, f"档位={level} 跳过计分明细加和校验"
    m = re.search(r'##\s*第十章[:：]?(.*?)(?=##\s|\Z)', text, re.DOTALL)
    if not m:
        return True, "无第十章，跳过"
    ch10 = m.group(1)
    if "**计分明细**" not in ch10:
        return True, "无计分明细子表，跳过（由校验 11 覆盖）"
    # 截取计分明细段
    scoring_section = ch10.split("**计分明细**")[1]
    # 解析表格行
    rows = [r.strip() for r in scoring_section.splitlines() if r.strip().startswith("|") and "---" not in r]
    if not rows:
        return True, "计分明细无表格，跳过"
    # 第一行是表头
    header_cells = [c.strip() for c in rows[0].strip("|").split("|")]
    # 按表头定位"加权分"列索引（兼容"加权分"、"score"、"weighted_score"等）
    score_col_idx = None
    for i, h in enumerate(header_cells):
        if "加权分" in h or h.lower() in ("score", "weighted_score", "weighted score"):
            score_col_idx = i
            break
    if score_col_idx is None:
        # 兜底：取倒数第二列（最后一列通常是"有效性状态"等文字）
        score_col_idx = len(header_cells) - 2 if len(header_cells) >= 2 else 0
    data_rows = rows[1:]
    if not data_rows:
        return True, "计分明细表无数据行，跳过"
    sum_value = 0.0
    sum_value_valid = True
    total_value = None
    for row in data_rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        if not cells:
            continue
        first_cell = cells[0].strip()
        # 取加权分列（按表头定位）
        if score_col_idx >= len(cells):
            continue
        score_cell = cells[score_col_idx].strip()
        # 合计行：第一列含"合计"
        if "合计" in first_cell:
            # 提取合计值（去掉 ** 和空格）
            total_str = score_cell.replace("*", "").strip()
            try:
                total_value = float(total_str)
            except ValueError:
                pass
            continue
        # 普通数据行：累加加权分列
        try:
            v = float(score_cell)
            sum_value += v
        except ValueError:
            sum_value_valid = False
    if total_value is None:
        return True, "计分明细无合计行，跳过加和校验"
    if not sum_value_valid:
        return True, "计分明细含非数值加权分，跳过加和校验"
    # 允许 0.01 误差（浮点）
    if abs(sum_value - total_value) > 0.01:
        return False, f"计分明细加和不一致：sum={sum_value}, 合计={total_value}"
    return True, f"计分明细加和一致：{sum_value} = 合计 {total_value}"


def check_search_audit_completeness(text, level):
    """15. 检索审计完整性校验（仅 L2/L3）。

    检索审计段必须含 5 个字段：检索式、数据库、时间范围、去重策略、筛选流程。
    缺任一字段报硬失败。
    """
    if level in (LEVEL_L0, LEVEL_L1):
        return True, f"档位={level} 跳过检索审计完整性校验"
    # 定位检索审计段：优先找 "### 检索审计" 标题（避免 front-matter 误命中）
    audit_idx = text.rfind("### 检索审计")
    if audit_idx == -1:
        # 兜底：找任意 "检索审计" 出现位置
        audit_idx = text.find("检索审计")
    if audit_idx == -1:
        # 检查是否同时含三关键词
        if not ("检索式" in text and "数据库" in text and "去重策略" in text):
            return False, "缺少检索审计段（由校验 12 覆盖）"
        audit_section = text
    else:
        # 截取检索审计段后 1500 字符（表格字段可能分散，扩大窗口）
        audit_section = text[audit_idx:audit_idx + 1500]
    required_fields = ("检索式", "数据库", "时间范围", "去重策略", "筛选流程")
    missing = [f for f in required_fields if f not in audit_section]
    if missing:
        return False, f"检索审计段缺少字段：{', '.join(missing)}"
    return True, "检索审计 5 字段完整"


def check_evidence_score_format(text, level):
    """16. 证据分数格式校验（仅 L0）。

    已取消进度条可视化，改为直接展示核心证据分与满分。
    标准格式：`证据：{强/中/弱} 核心证据分 X.X（满分 8.0，≥8.0 为强证据门槛）`

    等级与分数对应关系：
      - 强（green）：X.X ≥ 8.0
      - 中（yellow）：4.0 ≤ X.X < 8.0
      - 弱（red）：X.X < 4.0
      - insufficient：不显示分数，显示「⚪ 证据不足」

    校验逻辑：
      1. 匹配「证据：{强/中/弱} 核心证据分 X.X」格式
      2. 等级标签与分数数值一致
      3. 必须写明满分 8.0
      4. insufficient 不应出现分数
    """
    if level != LEVEL_L0:
        return True, f"档位={level} 跳过证据分数校验"

    # insufficient 检查：不显示核心证据分
    text_conclusion = extract_conclusion(text)
    if text_conclusion == "证据不足，无法给出方向性结论":
        if "核心证据分" in text:
            return False, "insufficient 等级不应显示核心证据分，但检测到「核心证据分」"
        return True, "insufficient 等级：无分数（合规）"

    # 匹配证据行：证据：{强/中/弱} 核心证据分 X.X（兼容 markdown 加粗 **证据**：）
    m = re.search(r'\*{0,2}证据\*{0,2}[：:]\s*([强弱中])\s*核心证据分\s*([\d.]+)', text)
    if not m:
        return False, "L0 卡片缺少「证据：{强/中/弱} 核心证据分 X.X」字段"

    label = m.group(1)
    value = float(m.group(2))

    # 等级标签与分数一致性
    if label == "强" and value < 8.0:
        return False, f"等级标签「强」要求分数≥8.0，实际={value}"
    if label == "中" and not (4.0 <= value < 8.0):
        return False, f"等级标签「中」要求分数在 4.0-7.99，实际={value}"
    if label == "弱" and value >= 4.0:
        return False, f"等级标签「弱」要求分数<4.0，实际={value}"

    # 满分标注检查
    if "满分 8.0" not in text and "满分8.0" not in text:
        return False, "缺少满分标注，应写明「满分 8.0」"

    return True, f"证据分数格式正确：{label} {value}（满分 8.0）"


def check_supporting_conclusion_diversity(text, level):
    """17. 支撑结论去同质化校验（仅 L2/L3）。

    第十章证据索引表的"支撑结论"列（第 6 列）：
    - 检测是否有连续 3 行完全相同
    - 若有，报硬失败
    """
    if level in (LEVEL_L0, LEVEL_L1):
        return True, f"档位={level} 跳过支撑结论去同质化校验"
    m = re.search(r'##\s*第十章[:：]?(.*?)(?=##\s|\Z)', text, re.DOTALL)
    if not m:
        return True, "无第十章，跳过"
    ch10 = m.group(1)
    # 只解析证据索引表（"计分明细"前的第一个表）
    evidence_section = ch10.split("**计分明细**")[0] if "**计分明细**" in ch10 else ch10
    rows = [r.strip() for r in evidence_section.splitlines() if r.strip().startswith("|") and "---" not in r]
    if len(rows) < 4:  # 表头 + 至少 3 数据行
        return True, "证据表数据行不足 3 行，跳过"
    # 跳过表头
    data_rows = rows[1:]
    conclusions = []
    for row in data_rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        if len(cells) < 6:
            continue
        conclusions.append(cells[5])  # 第 6 列（索引 5）= 支撑结论
    if len(conclusions) < 3:
        return True, "支撑结论列数据不足 3 行，跳过"
    # 滑动窗口检测：连续 3 行相同，或编辑距离过近（换几个字绕过同义反复也拦住）。
    # 相似度阈值：长度相近的两串，归一化编辑距离（1 - dist/maxlen）> 0.8 视为同质。
    def _similarity(a: str, b: str) -> float:
        if a == b:
            return 1.0
        la, lb = len(a), len(b)
        if not la or not lb:
            return 0.0
        prev = list(range(lb + 1))
        for ia in range(1, la + 1):
            cur = [ia] + [0] * lb
            for ib in range(1, lb + 1):
                cur[ib] = min(prev[ib] + 1, cur[ib - 1] + 1,
                              prev[ib - 1] + (a[ia - 1] != b[ib - 1]))
            prev = cur
        return 1 - prev[lb] / max(la, lb)

    for i in range(len(conclusions) - 2):
        trio = [x for x in conclusions[i:i + 3] if x]
        if len(trio) < 3:
            continue
        if trio[0] == trio[1] == trio[2]:
            return False, f"支撑结论连续 3 行相同：{trio[0][:50]!r}（第 {i+1}-{i+3} 行）"
        pairs = [_similarity(trio[0], trio[1]), _similarity(trio[1], trio[2]), _similarity(trio[0], trio[2])]
        if all(p > 0.8 for p in pairs):
            return False, (f"支撑结论连续 3 行高度相似（相似度 "
                           f"{pairs[0]:.2f}/{pairs[1]:.2f}/{pairs[2]:.2f} > 0.80，疑似换字式同质）："
                           f"{trio[0][:40]!r}…（第 {i+1}-{i+3} 行）")
    return True, "支撑结论去同质化通过"


# 无依据预测关键词（命中且无引用/无【推断】标注则报硬失败）
# P1-12：扩展关键词覆盖"6 个月内"、"预计 2027 年"、"3-5 年"、"行业领先"、"主流方案"
UNSUPPORTED_PREDICTION_KEYWORDS = [
    r'2026-2029',
    r'\d{4}\s*-\s*\d{4}',       # 年份区间（如 2025-2028）
    r'1-2\s*人',               # 1-2 人 / 1-2人（人力估算无引用）
    r'\d+\s*-\s*\d+\s*[人年月]', # 人力/时间估算（如 3-5 年、2-3 人）
    r'年均\s*50\+',
    r'年均\s*\d+',
    r'金标准',
    r'广泛采用',
    r'监管落地',
    r'行业领先',
    r'主流方案',
    r'\d+\s*个月内',           # 如 6 个月内
    r'预计\s*\d{4}\s*年',      # 如 预计 2027 年
]
# 机械升级路径关键词（必须删除，即使有【推断】也报失败）
MECHANICAL_UPGRADE_KEYWORDS = [
    r'4\s*周.*升级',
    r'4\s*周内.*优先整合',
    r'4\s*周.*优先整合',
    r'4\s*周.*跑通',
]
# 引用模式（[1] 或 (Smith, 2020)）
CITATION_PATTERN = re.compile(r'\[\d+\]|\([^)]*\d{4}\)')
# 【推断】标签
INFER_LABEL = "【推断】"


def check_unsupported_prediction_labels(text, level):
    """18. 无依据预测标注校验（全档位）。

    扫描全文，检测含 UNSUPPORTED_PREDICTION_KEYWORDS 的句子：
    - 若该句含【推断】标签，放行
    - 若该句含引用（如 [1] 或 (Author, 2020)），放行
    - 否则报硬失败

    对 MECHANICAL_UPGRADE_KEYWORDS（4 周升级等），要求必须删除——
    若仍存在报硬失败（即使有【推断】标注）。
    """
    # 按句子分割（句号、问号、感叹号、换行）
    # 保留分隔符以便定位
    sentences = re.split(r'(?<=[。！？\n])', text)
    issues = []
    for sent in sentences:
        s = sent.strip()
        if not s or len(s) < 5:
            continue
        # 跳过表格行、引用块、代码块、标题
        if s.startswith("|") or s.startswith(">") or s.startswith("#") or s.startswith("```"):
            continue
        # 先检查机械升级路径（必须删除）
        for kw in MECHANICAL_UPGRADE_KEYWORDS:
            if re.search(kw, s):
                issues.append(f"机械升级路径未删除：{s[:60]!r}")
                break
        else:
            # 检查无依据预测关键词（黑名单）
            hit = False
            for kw in UNSUPPORTED_PREDICTION_KEYWORDS:
                if re.search(kw, s):
                    # 该句是否含【推断】或引用
                    has_label = INFER_LABEL in s
                    has_citation = bool(CITATION_PATTERN.search(s))
                    if not has_label and not has_citation:
                        issues.append(f"无依据预测未标注：{s[:60]!r}")
                    hit = True
                    break
            if not hit:
                # 模态检测（第六点评 P2）：预测模态词 + 无引用 + 无【推断】→ 报错。
                # 检测"模态"而非具体年份/数字——"未来三到四年"这类换说法同样拦住。
                modal = bool(re.search(r"预计|将会|未来[一两三三五\d]+[年月个]|有望|或将|届时", s))
                if modal and not INFER_LABEL in s and not CITATION_PATTERN.search(s):
                    issues.append(f"预测模态未标注：{s[:60]!r}")
    if issues:
        return False, "; ".join(issues[:3])  # 最多报 3 条
    return True, "无依据预测标注通过"


# 校验 19：内部黑话检测
# 这些术语只应出现在内部文档（SKILL.md / spec / debug），不应出现在交付给用户的简报中
# 内部章节/规则编号：§1、§14 等（用正则精确匹配，避免 §1 漏扫 §14 之外的编号）
INTERNAL_SECTION_REF = re.compile(r'§\s*\d+')


def _strip_quote_and_code_blocks(text):
    """移除引用块（> 开头的行）和代码块（``` 包裹）的内容。

    P1-13：黑话检测时，引用块/代码块中的术语不视为交付物黑话，
    因为这些通常是示例或引用，不是交付给用户的正文。
    """
    lines = text.splitlines()
    result = []
    in_code_block = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if stripped.startswith(">"):
            continue
        result.append(line)
    return "\n".join(result)


def _jargon_hit(text: str, jargon: str) -> bool:
    """P0-1：检测黑话是否命中。

    三类匹配策略（由 internal_jargon.json 的 _word_boundary_jargon /
    _contextual_jargon 分层声明）：
    - 词边界（短英文词如 project_memory）：避免 memory-efficient 等复合词误伤；
    - 上下文（如 front-matter）：仅在后接内部语境词时判定为黑话，
      出版物语境的 front-matter 放行；
    - 其余：子串匹配（原行为）。
    """
    if jargon in _WORD_BOUNDARY_JARGON:
        return re.search(r"\b" + re.escape(jargon) + r"\b", text) is not None
    if jargon in _CONTEXTUAL_JARGON:
        pattern = re.escape(jargon) + r"\s*(标记|元信息|字段|区块|解析)"
        return re.search(pattern, text) is not None
    return jargon in text


def check_no_internal_jargon(text, level):
    """19. 内部黑话检测（全档位）。

    交付给用户的简报中禁止出现内部术语（变量名、脚本名、配置项、档位标记等）。
    这些只应出现在内部文档，不应暴露给用户。
    黑话列表单一事实源：scripts/config/internal_jargon.json（经 config_loader 加载）。

    P1-13：引用块和代码块中的术语不视为黑话（放行），避免误伤正常中文。
    P0-2 修复：内部章节编号（§1、§14）的扫描同样剥离引用块/代码块，
    避免示例文档引用块中的 §14 描述被误判为交付物黑话。
    P0-1：短英文词用词边界匹配（_jargon_hit），memory-efficient 等正常术语不误伤。
    """
    # P1-13：先移除引用块和代码块，只在正文检测黑话
    clean_text = _strip_quote_and_code_blocks(text)
    issues = []
    for jargon in INTERNAL_JARGON:
        if _jargon_hit(clean_text, jargon):
            # 定位出现位置
            idx = clean_text.find(jargon)
            # 取上下文
            start = max(0, idx - 20)
            end = min(len(clean_text), idx + len(jargon) + 20)
            context = clean_text[start:end].replace("\n", " ")
            issues.append(f"内部术语 {jargon!r} 出现在用户输出：...{context}...")
    # 结构检测（第六点评 P2）：文件名模式（如 xxx.py/xxx.md/xxx.json）是内部实现的
    # 强信号——不依赖枚举黑名单，LLM 换任何脚本名都拦得住。
    for m in re.finditer(r"\b\w[-\w]*\.(?:py|md|json)\b", clean_text):
        issues.append(f"疑似内部文件名 {m.group()!r} 出现在用户输出（结构检测）")
    # 内部章节/规则编号（§1、§14 等）正则扫描（同样剥离引用块/代码块）
    m_ref = INTERNAL_SECTION_REF.search(clean_text)
    if m_ref:
        idx = m_ref.start()
        start = max(0, idx - 20)
        end = min(len(clean_text), idx + len(m_ref.group()) + 20)
        context = clean_text[start:end].replace("\n", " ")
        issues.append(f"内部章节编号 {m_ref.group()!r} 出现在用户输出：...{context}...")
    if issues:
        return False, "; ".join(issues[:3])  # 最多报 3 条
    return True, "无内部黑话"


# 校验 20：指令性文字泄漏检测（P1-2，P0-2 拆两层）
# 模板/规则中对 AI 的指令若被 LLM 渲染进用户输出，说明指令收口失败。
# 两层短语：
#   STRICT_LEAK_PHRASES：全档位严格短语——剥离代码块后出现在任何正文位置（含引用块）即硬失败；
#   DISCLAIMER_ZONE_LEAK_PHRASES：免责声明区专属短语——仅在「## 免责声明」到文末范围内检查。
# 拆层原因："不得修改措辞" 等短语可能被正文合法引用（如用户问"为什么这段免责声明不能改"），
# 全文扫描会误伤；而验收样例的泄漏恰好落在免责声明引用块内，免责区检查仍完整覆盖。
STRICT_LEAK_PHRASES = [
    "此行是对 AI 的指令",
    "不渲染给用户",
    "SYSTEM INSTRUCTIONS",
]

DISCLAIMER_ZONE_LEAK_PHRASES = [
    "不得修改措辞",
    "每次蒸馏简报末尾必须原样附加",
    "对 AI 的指令",
]

# 向后兼容旧名（tests/外部引用了 INSTRUCTION_LEAK_PHRASES）
INSTRUCTION_LEAK_PHRASES = STRICT_LEAK_PHRASES + DISCLAIMER_ZONE_LEAK_PHRASES


def check_no_instruction_leak(text, level):
    """20. 指令性文字泄漏检测（全档位，P0-2 拆两层）。

    两层检查：
    - 严格短语（STRICT_LEAK_PHRASES）：全文（剥离代码块后）检查，任何位置命中即硬失败；
    - 免责区短语（DISCLAIMER_ZONE_LEAK_PHRASES）：只在「## 免责声明」到文末检查，
      避免用户合法引用（如"这段为什么不修改措辞"）被误伤。

    与黑话检测（第 19 项）不同：指令短语在引用块中也算泄漏——
    方案验收样例即把泄漏文字放在免责声明引用块中（> 本简报…不得修改措辞），
    免责区包含引用块内容，该样例仍被覆盖。
    """
    lines = text.splitlines()
    result = []
    in_code_block = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        result.append(line)
    clean = "\n".join(result)

    # 第一层：全文严格短语
    strict_hits = [p for p in STRICT_LEAK_PHRASES if p in clean]
    if strict_hits:
        return False, f"指令性文字泄漏（正文）：{strict_hits}"

    # 第二层：免责声明区专属短语
    m = re.search(r"##\s*免责声明(.*)", clean, re.DOTALL)
    if m:
        disclaimer_zone = m.group(1)
        zone_hits = [p for p in DISCLAIMER_ZONE_LEAK_PHRASES if p in disclaimer_zone]
        if zone_hits:
            return False, f"指令性文字泄漏（免责声明区）：{zone_hits}"

    return True, "无指令性文字泄漏"


def check_scoring_signature(text, score_json, level):
    """21. 计分签名校验（全档位，P1-1；有 score_json 或文本含 L3 JSON 审计日志时生效）。

    防止 LLM 手写计分结果绕过 score_evidence.py：
    - 若提供 score_json 参数：检查其 scored_by 字段；
    - 若文本含 L3 JSON 审计日志（```json 块含 detailed_scores 或 conclusion）：
      检查该 JSON 的 scored_by 字段；
    - 两者都没有：视为 L0/L1 无审计日志场景，放行。

    签名字段缺失或值非 "score_evidence.py" → 硬失败。
    """
    # 优先检查 score_json 参数
    if score_json is not None:
        if "scored_by" not in score_json:
            return False, "score JSON 缺少 scored_by 字段，疑似手写而非 score_evidence.py 输出"
        if score_json["scored_by"] != "score_evidence.py":
            return False, f"scored_by 字段非 score_evidence.py：{score_json['scored_by']!r}"
        ver = score_json.get("scored_by_version", "?")
        return True, f"计分签名有效：score_evidence.py@{ver}"

    # 检查文本中的 L3 JSON 审计日志
    json_blocks = re.findall(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    for block in json_blocks:
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if "detailed_scores" not in data and "conclusion" not in data:
            continue
        if "scored_by" not in data:
            return False, "L3 JSON 审计日志缺少 scored_by 字段，疑似手写而非 score_evidence.py 输出"
        if data["scored_by"] != "score_evidence.py":
            return False, f"L3 JSON 的 scored_by 字段非 score_evidence.py：{data['scored_by']!r}"
        return True, f"计分签名有效：score_evidence.py@{data.get('scored_by_version', '?')}"

    return True, "无计分 JSON，跳过签名校验"


# ──────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────

# 编号 1-4 的基础校验（编号 1 需 level 参数，在 run_all 中单独处理）
CHECKS = [
    (2, "2. 第九章三选一结论", check_three_choice_conclusion),
    (3, "3. 第十章有效性状态非空", check_validity_table),
    (4, "4. 连续3处无标签检测", check_label_density),
]


def run_all(text: str, score_json: Optional[dict] = None, level: Optional[str] = None) -> tuple[list[tuple[int, str, bool, str]], int]:
    """运行全部校验。返回 (results_list, hard_fail_count)。

    若 level 指定，仅跑该档位适用的校验项（见 APPLICABLE_CHECKS）。
    不适用的项以 SKIPPED 状态返回。
    """
    if level is None:
        raise ValueError("level is required; pass --level L0/L1/L2/L3")
    applicable = APPLICABLE_CHECKS.get(level, APPLICABLE_CHECKS[LEVEL_L2])

    results = []
    fails = 0

    # 编号 1：首行第零章标题（需 level 参数；修复曾因闭包引用未定义变量 level 的 NameError）
    if 1 not in applicable:
        results.append(("1. 首行第零章标题", None, f"档位={level} 不适用，跳过"))
    else:
        try:
            ok, detail = check_chapter_zero_first(text, level)
        except Exception as e:
            ok, detail = False, f"校验异常: {type(e).__name__}: {e}"
        results.append(("1. 首行第零章标题", ok, detail))
        if not ok:
            fails += 1

    # 编号 2-4 的基础校验
    for num, name, fn in CHECKS:
        if num not in applicable:
            results.append((name, None, f"档位={level} 不适用，跳过"))
            continue
        try:
            ok, detail = fn(text)
        except Exception as e:
            ok, detail = False, f"校验异常: {type(e).__name__}: {e}"
        results.append((name, ok, detail))
        if not ok:
            fails += 1

    # 编号 5：免责声明（需 level 参数）
    if 5 not in applicable:
        results.append(("5. 免责声明原文", None, f"档位={level} 不适用，跳过"))
    else:
        try:
            ok, detail = check_disclaimer(text, level)
        except Exception as e:
            ok, detail = False, f"校验异常: {type(e).__name__}: {e}"
        results.append(("5. 免责声明原文", ok, detail))
        if not ok:
            fails += 1

    # 编号 6、7：需 JSON 的校验
    json_checks = [
        (6, "6. L0-审计层结论一致性", lambda t: check_l0_audit_consistency(t, score_json)),
        (7, "7. §14 矩阵强校验", lambda t: check_matrix_strong_validation(t, score_json)),
    ]
    for num, name, fn in json_checks:
        if num not in applicable:
            results.append((name, None, f"档位={level} 不适用，跳过"))
            continue
        try:
            ok, detail = fn(text)
        except Exception as e:
            ok, detail = False, f"校验异常: {type(e).__name__}: {e}"
        results.append((name, ok, detail))
        if not ok:
            fails += 1

    # 编号 8：DOI 一致性
    if 8 not in applicable:
        results.append(("8. DOI/有效性一致性", None, f"档位={level} 不适用，跳过"))
    else:
        try:
            ok, detail = check_validity_doi_consistency(text)
        except Exception as e:
            ok, detail = False, f"校验异常: {type(e).__name__}: {e}"
        results.append(("8. DOI/有效性一致性", ok, detail))
        if not ok:
            fails += 1

    # 编号 9、10：DOI 去重与格式校验（L0/L1 也跑）
    doi_extra_checks = [
        (9, "9. 第十章 DOI 去重", check_doi_dedup),
        (10, "10. DOI 格式校验", check_doi_format),
    ]
    for num, name, fn in doi_extra_checks:
        if num not in applicable:
            results.append((name, None, f"档位={level} 不适用，跳过"))
            continue
        try:
            ok, detail = fn(text)
        except Exception as e:
            ok, detail = False, f"校验异常: {type(e).__name__}: {e}"
        results.append((name, ok, detail))
        if not ok:
            fails += 1

    # 编号 11、12：计分明细与检索审计（仅 L2/L3）
    level_checks = [
        (11, "11. 计分明细子表", lambda t: check_scoring_details(t, level)),
        (12, "12. 检索审计段", lambda t: check_search_audit(t, level)),
    ]
    for num, name, fn in level_checks:
        if num not in applicable:
            results.append((name, None, f"档位={level} 不适用，跳过"))
            continue
        try:
            ok, detail = fn(text)
        except Exception as e:
            ok, detail = False, f"校验异常: {type(e).__name__}: {e}"
        results.append((name, ok, detail))
        if not ok:
            fails += 1

    # 编号 13-20：v2 后置硬门禁（year_volume/计分加和/检索审计完整性/证据分数/去同质化/无依据预测/黑话/指令泄漏）
    v2_checks = [
        (13, "13. 年份/卷期一致性", lambda t: check_year_volume_consistency(t, level)),
        (14, "14. 计分明细加和一致性", lambda t: check_scoring_details_sum(t, level)),
        (15, "15. 检索审计完整性", lambda t: check_search_audit_completeness(t, level)),
        (16, "16. 证据分数格式", lambda t: check_evidence_score_format(t, level)),
        (17, "17. 支撑结论去同质化", lambda t: check_supporting_conclusion_diversity(t, level)),
        (18, "18. 无依据预测标注", lambda t: check_unsupported_prediction_labels(t, level)),
        (19, "19. 内部黑话检测", lambda t: check_no_internal_jargon(t, level)),
        (20, "20. 指令性文字泄漏检测", lambda t: check_no_instruction_leak(t, level)),
        (21, "21. 计分签名校验", lambda t: check_scoring_signature(t, score_json, level)),
    ]
    for num, name, fn in v2_checks:
        if num not in applicable:
            results.append((name, None, f"档位={level} 不适用，跳过"))
            continue
        try:
            ok, detail = fn(text)
        except Exception as e:
            ok, detail = False, f"校验异常: {type(e).__name__}: {e}"
        # 警告级校验项（如 13 年份/卷期一致性）：执行但不阻断。
        # ok 置为三态中的 "warning"（非 True），保持 hard_failures=0，
        # 同时在 JSON 中可被结构化识别，不与通过项混淆。
        if num in WARNING_ONLY_CHECKS and not ok:
            ok = "warning"
            detail = f"[WARNING，不阻断交付] {detail}"
        results.append((name, ok, detail))
        if ok is False:
            fails += 1

    return results, fails


def main():
    parser = argparse.ArgumentParser(description="InterSci-KD 输出校验器")
    parser.add_argument("--input", required=True, help="简报 Markdown 文件路径")
    parser.add_argument("--json", default=None, help="score_evidence.py 输出的 JSON 文件路径（可选，用于 L0/矩阵校验）")
    parser.add_argument("--level", required=True, choices=["L0", "L1", "L2", "L3"],
                        help="必填：交付物档位。v4.4.1 起不再从交付文本内嵌标记解析档位")
    parser.add_argument("--pretty", action="store_true", help="格式化输出")
    args = parser.parse_args()

    try:
        text = Path(args.input).read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"ERROR: 文件不存在: {args.input}", file=sys.stderr)
        sys.exit(2)

    score_json = None
    if args.json:
        try:
            raw = args.json if args.json.strip().startswith("{") else Path(args.json).read_text(encoding="utf-8-sig")
            score_json = json.loads(raw)
        except Exception as e:
            print(f"WARNING: 无法解析 JSON: {e}", file=sys.stderr)

    level = args.level
    results, fails = run_all(text, score_json, level=level)

    indent = 2 if args.pretty else None
    out = {
        "input": args.input,
        "level": level,
        "total_checks": len(results),
        "hard_failures": fails,
        "warnings": sum(1 for _, ok, _ in results if ok == "warning"),
        "passed": sum(1 for _, ok, _ in results if ok is True),
        "skipped": sum(1 for _, ok, _ in results if ok is None),
        "results": [
            {"check": name, "ok": ("skipped" if ok is None else ok), "detail": detail}
            for name, ok, detail in results
        ],
    }
    print(json.dumps(out, ensure_ascii=False, indent=indent))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
