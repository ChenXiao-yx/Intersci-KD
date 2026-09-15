"""文档-代码-配置一致性检查脚本。

扫描以下单一事实源与文档之间的一致性：
- SKILL.md frontmatter 版本 ↔ pyproject.toml version ↔ CHANGELOG.md 尾行当前版本（P0-1 版本号对账）
- TOOL_REGISTRY 实际数量 ↔ SKILL.md/README.md 声明的工具数（P0-3 工具数对账）
- validity_states.json ↔ validate_output.py 的 VALIDITY_STATES
- internal_jargon.json ↔ validate_output.py 的 INTERNAL_JARGON
- conclusion_options.json ↔ validate_output.py 的 CONCLUSION_OPTIONS
- disclaimer_phrases.json ↔ validate_output.py 的 DISCLAIMER_*
- evidence_weights.json 的 domain_map ↔ search_papers/score_evidence 的 --domain choices

退出码：0=全部一致；1=发现不一致。
"""
import re
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from config_loader import (
    get_valid_domains, get_validity_states, get_internal_jargon,
    get_conclusion_options, get_disclaimer_phrases,
)


def _check_version_consistency(issues):
    """P0-1：校验 SKILL.md frontmatter 版本 == pyproject.toml version == CHANGELOG 尾行当前版本。

    SKILL.md 的 version 带 "-skill" 后缀（如 "4.6.0-skill"），
    CHANGELOG 尾行形如「**当前版本：4.6.0-skill**」；两者提取时只取数字段，
    与 pyproject 的纯版本号三方对齐比较。
    """
    root = Path(__file__).resolve().parent.parent
    skill_md = root / "SKILL.md"
    pyproject = root / "pyproject.toml"
    changelog = root / "CHANGELOG.md"
    if not skill_md.exists() or not pyproject.exists():
        issues.append(f"版本号对账失败: SKILL.md 存在={skill_md.exists()}, pyproject.toml 存在={pyproject.exists()}")
        return
    text = skill_md.read_text(encoding="utf-8")
    m = re.search(r'^version:\s*["\']?([\d.]+)', text, re.MULTILINE)
    skill_ver = m.group(1) if m else None
    py_text = pyproject.read_text(encoding="utf-8")
    m2 = re.search(r'^version\s*=\s*["\']([\d.]+)["\']', py_text, re.MULTILINE)
    py_ver = m2.group(1) if m2 else None
    if skill_ver is None or py_ver is None:
        issues.append(f"版本号解析失败: SKILL.md={skill_ver}, pyproject.toml={py_ver}")
    elif skill_ver != py_ver:
        issues.append(f"版本号不一致: SKILL.md={skill_ver}, pyproject.toml={py_ver}")
    # CHANGELOG 尾行当前版本（第三处对账，评估意见：此前仅人工保持一致）
    if changelog.exists():
        m3 = re.search(r'当前版本[:：]\s*\*{0,2}([\d.]+)', changelog.read_text(encoding="utf-8"))
        cl_ver = m3.group(1) if m3 else None
        if cl_ver is None:
            issues.append("CHANGELOG.md 未找到「当前版本：」尾行，无法对账")
        elif py_ver is not None and cl_ver != py_ver:
            issues.append(f"版本号不一致: CHANGELOG 尾行={cl_ver}, pyproject.toml={py_ver}")
    else:
        issues.append("CHANGELOG.md 缺失，版本号第三处对账无法执行")


def _check_tool_count_consistency(issues):
    """P0-3：校验文档声明的 SCP 工具数与 TOOL_REGISTRY 实际数量一致。

    文档中 "N 个 SCP…" / "N 个数据工具…" / "N 个 MCP 端点…" / "N 个工具…"
    的 N 必须是 TOOL_COUNT（工具数）或 ENDPOINT_COUNT（端点数）；
    其它数字（如历史修订日志里的旧口径）会被判为不一致。
    评估意见修复：原正则只匹配「N 个 SCP」，漏掉「N 个数据工具共用」等第三种措辞，
    现按名词短语白名单放宽。
    """
    from scp_tools import TOOL_COUNT, ENDPOINT_COUNT
    root = Path(__file__).resolve().parent.parent
    # 名词短语白名单：这些位置出现的数字必须是工具数或端点数。
    # 注意不含裸「工具/端点」——「Sciverse 端点提供 2 个工具」属合法逐端点描述，不能误报。
    pattern = re.compile(r'(\d+)\s*个\s*(?:SCP|数据工具|MCP\s*端点)')
    for fname in ("SKILL.md", "README.md"):
        fpath = root / fname
        if not fpath.exists():
            issues.append(f"{fname} 缺失，无法校验工具数声明")
            continue
        text = fpath.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            declared = int(m.group(1))
            if declared not in (TOOL_COUNT, ENDPOINT_COUNT):
                issues.append(
                    f"{fname} 声明 {declared} 个 SCP 工具/端点，"
                    f"实际 TOOL_COUNT={TOOL_COUNT}, ENDPOINT_COUNT={ENDPOINT_COUNT}"
                )


def main():
    issues = []

    # 0. P0-1/P0-3：版本号与工具数对账（不依赖 config，先跑）
    _check_version_consistency(issues)
    _check_tool_count_consistency(issues)

    # 1. 检查 config JSON 文件存在且可加载
    try:
        validity = get_validity_states()
        jargon = get_internal_jargon()
        conclusions = get_conclusion_options()
        disclaimer = get_disclaimer_phrases()
        domains = get_valid_domains()
    except Exception as e:
        print(f"FAIL: 配置加载失败: {e}", file=sys.stderr)
        return 1

    # 2. 检查 validate_output.py 使用的常量与配置一致
    import validate_output as vo
    if vo.VALIDITY_STATES != validity:
        issues.append(f"VALIDITY_STATES 不一致: config={validity}, code={vo.VALIDITY_STATES}")
    if vo.CONCLUSION_OPTIONS != conclusions:
        issues.append(f"CONCLUSION_OPTIONS 不一致: config={conclusions}, code={vo.CONCLUSION_OPTIONS}")
    if vo.INTERNAL_JARGON != jargon:
        issues.append(f"INTERNAL_JARGON 不一致: config={jargon}, code={vo.INTERNAL_JARGON}")
    if vo.DISCLAIMER_PREFIX != disclaimer["full_prefix"]:
        issues.append(f"DISCLAIMER_PREFIX 不一致: config={disclaimer['full_prefix']}, code={vo.DISCLAIMER_PREFIX}")
    if tuple(vo.DISCLAIMER_KEY_PHRASES) != tuple(disclaimer["full_key_phrases"]):
        issues.append("DISCLAIMER_KEY_PHRASES 不一致")
    if vo.L0_DISCLAIMER_PREFIX != disclaimer["l0_prefix"]:
        issues.append(f"L0_DISCLAIMER_PREFIX 不一致: config={disclaimer['l0_prefix']}, code={vo.L0_DISCLAIMER_PREFIX}")
    if tuple(vo.L0_DISCLAIMER_KEY_PHRASES) != tuple(disclaimer["l0_key_phrases"]):
        issues.append("L0_DISCLAIMER_KEY_PHRASES 不一致")

    # 3. 检查 score_evidence.py 的 DOMAIN_MAP 键集与 get_valid_domains 一致
    import score_evidence as se
    se_domains = sorted(se.DOMAIN_MAP.keys())
    if se_domains != domains:
        issues.append(f"score_evidence DOMAIN_MAP 不一致: config={domains}, code={se_domains}")

    # 4. 检查 evidence_weights.json 的 evidence_weights 键与 normalize_type 标准键对齐
    from normalize_type import SOURCE_TYPE_VENUE_MAP, STUDY_DESIGN_PATTERNS
    # normalize_type 的映射目标值应全部是 evidence_weights 的键
    ew_keys = set(se.EVIDENCE_WEIGHTS.keys())
    for src, target in SOURCE_TYPE_VENUE_MAP.items():
        if target not in ew_keys:
            issues.append(f"SOURCE_TYPE_VENUE_MAP['{src}'] -> '{target}' 不在 evidence_weights 键集中")

    if issues:
        for i in issues:
            print(f"FAIL: {i}", file=sys.stderr)
        return 1

    print("OK: 文档-代码-配置一致性检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
