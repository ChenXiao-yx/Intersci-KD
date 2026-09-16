# InterSci-KD 跨学科知识蒸馏 Skill

> 面向生物医药/智能硬件/新材料领域的 AI 操作手册，基于证据锚定输出结构化知识简报。

## 快速指引

| 文件 | 说明 |
| :--- | :--- |
| **SKILL.md** | 核心规则：蒸馏流程、证据权重、闸口阈值、输出模板 |
| **references/** | 评分规则（evidence-rubric.md）、输出模板（output-template.md）、人话翻译映射（plain-language-map.md）、哲学背景（philosophy.md） |
| **scripts/** | 辅助脚本：论文检索、证据计分、SCP MCP 数据工具 |
| **examples/** | 输入示例与黄金输出样本 |

## 安装

```bash
# Python >= 3.8
pip install -r scripts/requirements.txt
```

核心依赖仅需 `requests`（用于 SCP MCP API 调用）。`score_evidence.py` 和 `search_papers.py`（mock 模式）使用纯标准库，无第三方依赖。

## 环境配置

### 方式一：首次运行自动引导（推荐）

直接运行任意脚本，首次检测到 Key 缺失时会自动提示输入：

```bash
python scripts/search_papers.py --query "test" --top_k 3
```

运行后会看到：
```
检测到 SCP_HUB_API_KEY 未配置
用途：SCP 平台通用 API Key（所有 11 个数据工具共用，10 个 MCP 端点）
申请地址：https://scp.intern-ai.org.cn
请粘贴你的 SCP_HUB_API_KEY（直接回车跳过，稍后手动配置 .env）：
> 
```

粘贴 Key 后回车，自动保存到 `.env`，后续运行无需再次配置。

### 方式二：手动配置

```bash
# 复制环境变量模板
cp .env.example .env
# 编辑 .env，填入你的 API Key
```

### 方式三：诊断当前配置状态

```bash
python scripts/key_setup.py --status
```

输出示例：
```
.env 文件：/path/to/intersci-kd-skill/.env
.env.example 模板：/path/to/intersci-kd-skill/.env.example

必填 Key：
  ✅ SCP_HUB_API_KEY: sk-xxxx...xxxx
```

### 必填与可选配置

| 变量名 | 必填 | 用途 | 申请地址 |
| :--- | :--- | :--- | :--- |
| \SCP_HUB_API_KEY\ | ✅ | SCP 平台通用 API Key（11 个数据工具共用，10 个 MCP 端点） | https://scp.intern-ai.org.cn |
| `INTERNLM_API_KEY` | ⚪ | 书生大模型 API（仅 LLM_BACKEND=internlm 时需要） | https://intern-ai.org.cn |
| `COMPETITION_API_KEY` | ⚪ | 竞赛 API（仅赛事参与者需要） | 由赛事方提供 |

> **安全说明**：`.env` 文件包含真实凭证，已被 `.gitignore` 排除，不会进入 git 仓库。`.env.example` 是无 Key 的模板文件，会随仓库分发。请勿将真实 Key 提交到 git 或贴到公开渠道。

## 脚本用法

```bash
# 论文检索（自动选择最相关 SCP 工具）
python scripts/search_papers.py --query "CRISPR gene editing" --top_k 10 --domain AI --pretty

# 检索结果输出到文件
python scripts/search_papers.py --query "CRISPR" --top_k 10 --domain AI --output papers.json

# 强制真实 API（失败即退出，不降级 mock）
python scripts/search_papers.py --query "CRISPR" --force-real

# 证据计分与评级
python scripts/score_evidence.py --input-json papers.json --domain biotech

# 计分输出到文件（自动 pretty 格式化）
python scripts/score_evidence.py --input-json papers.json --domain biotech --output score.json --pretty

# 输出校验（共 21 项编号检查，第 13 项为警告级不阻断；--level 必填，按档位执行 11/10/20 项：首行第零章/三选一结论/第十章有效性状态/连续无标签检测/免责声明原文/L0-审计层结论一致/§14矩阵强校验/DOI有效性一致性/第十章DOI去重/DOI格式校验/计分明细子表/检索审计段/年份卷期一致性[警告]/计分明细加和一致性/检索审计完整性/证据分数格式[仅L0]/支撑结论去同质化/无依据预测标注/内部黑话检测/指令性文字泄漏检测/计分签名校验）
python scripts/validate_output.py --input examples/full_output_golden.md --json examples/full_output_golden.score.json --level L2 --pretty

# 直接调用指定 SCP 数据工具
python scripts/scp_tools.py --tool origene-chembl --query "aspirin" --top_k 5 --pretty
```

## SCP MCP 数据工具集

采用 MCP Streamable HTTP 协议，单一通用 API Key + 10 个独立端点（11 个工具）：

| 工具 | 领域 | MCP 端点 |
| :--- | :--- | :--- |
| Sciverse | 通用学术/专利 | `/mcp/43/Sciverse` |
| Semantic Search | 语义检索 | `/mcp/43/Sciverse` |
| Origene-Search | PubMed 文献 | `/mcp/7/Origene-Search` |
| Scholar-KG | 学术知识图谱 | `/mcp/42/Scholar-KG` |
| Origene-NCBI | 基因/蛋白 | `/mcp/9/Origene-NCBI` |
| Origene-ChEMBL | 药物化学 | `/mcp/4/Origene-ChEMBL` |
| Origene-PubChem | 化学信息 | `/mcp/8/Origene-PubChem` |
| Origene-FDADrug | FDA 药品 | `/mcp/14/Origene-FDADrug` |
| Origene-OpenTargets | 药物靶点 | `/mcp/15/Origene-OpenTargets` |
| Origene-TCGA | 癌症基因组 | `/mcp/11/Origene-TCGA` |
| SciGraph-Material | 材料科学 | `/mcp/40/SciGraph-Material` |

> **端点说明**：Sciverse 端点（`/mcp/43/Sciverse`）提供 2 个工具（`search_papers` + `semantic_search`），因此 10 个端点对应 11 个工具。工具数量单一事实源：`scripts/scp_tools.py` 的 `TOOL_COUNT` / `ENDPOINT_COUNT`，由 `scripts/check_consistency.py` 对账，文档禁止硬编码其它数字。

## 项目结构

```
intersci-kd-skill/
├── SKILL.md                  # Skill 核心规则与蒸馏流程（含 L0/L1/L2/L3 分档）
├── CHANGELOG.md              # 完整修订日志（版本历史）
├── README.md                 # 使用说明
├── EXECUTION_CHECKLIST.md    # AI 执行导航清单
├── CONTRIBUTING.md           # 贡献指南
├── .env.example              # 环境变量模板
├── .gitignore
├── scripts/
│   ├── scp_tools.py          # SCP MCP 网关客户端（11 个数据工具/10 个端点，TOOL_COUNT 单一事实源）
│   ├── citation_lookup.py    # Semantic Scholar 被引数据查询（激活【低影响力】状态）
│   ├── search_papers.py      # 论文检索 CLI（自动委托 SCP 工具）
│   ├── score_evidence.py     # 证据计分引擎（mock 强隔离 + 域级核心证据门槛）
│   ├── validate_output.py    # 输出校验器（21 项编号检查，--level 必填按档位执行）
│   ├── check_consistency.py  # 文档-代码-配置一致性检查（版本号/工具数/配置对账）
│   ├── requirements.txt      # Python 依赖
│   └── config/
│       └── evidence_weights.json  # 证据权重配置（domain_map + 域级核心证据门槛）
├── references/
│   ├── evidence-rubric.md    # 证据评分规则（含 §14.1 矩阵强校验、§14.2 域级门槛）
│   ├── output-template.md    # 输出模板（L0 卡片 + L1 五块 + L2 十章，头部 SYSTEM INSTRUCTIONS 区块）
│   ├── plain-language-map.md # 人话翻译固定映射表
│   └── philosophy.md         # 跨学科哲学背景
├── tests/
│   ├── fixtures/             # 计分器/校验器测试样本（含 papers_ai_conference）
│   └── regression/           # 端到端回归 + 遵守率度量（tasks.json / run_regression.py / baseline.json）
└── examples/
    ├── example_input.json
    ├── intersci_input.json
    ├── dr_papers.json             # DR 文献锚点证据集（黄金样本计分数据源）
    ├── full_output_golden.md      # L2 完整档位黄金样本
    ├── full_output_golden.score.json
    ├── card_output_golden.md      # L0 卡片档位黄金样本（DR 主题，与 L2 同源）
    ├── card_output_golden.score.json
    ├── brief_output_golden.md     # L1 精简档位黄金样本（DR 主题，与 L2 同源）
    ├── brief_output_golden.score.json
    └── empty_retrieval_golden.md  # 空检索兜底场景黄金样本
```

## 回归与遵守率度量

```bash
# 全量回归（10 任务 + 21 项校验遵守率），对照基线检查回退
python tests/regression/run_regression.py --baseline tests/regression/baseline.json

# 真实 LLM 回归循环（第三轮评估①，最重要）：现场调用 LLM 生成 → 立即校验 → 统计真实遵守率。
# 需在 .env 配置可用的 LLM 后端（INTERNLM_API_KEY 或 COMPETITION_API_KEY）。
# 原始生成按轮次落盘 tests/regression/live_runs/ 供复查；低于 80% 的项自动列入真实裁剪清单。
python tests/regression/run_regression.py --live --baseline tests/regression/baseline.json
python tests/regression/run_regression.py --live --live-only      # 只跑 live 任务
python tests/regression/run_regression.py --live --live-rounds 3  # 每任务采样 3 轮（更稳）

# 交付物/证据变更后重写基线（跨年重跑计分会因年份衰减微降，也可借此重新锚定；
# --live 后重写会把 live_baseline 一起更新）
python tests/regression/run_regression.py --update-baseline
```

**三层基线，不要混读**：
- `check_pass_rate`（黄金样本自证）：输入=理想输出，全 1.0 是必然结果，价值在回归守护，不是 LLM 遵守率；
- `freeform_baseline`（已归档样本）：把 LLM 原始输出放入 `tests/regression/freeform_samples/` 后测出（见该目录 README 的供样纪律）；
- `live_baseline`（`--live` 现场生成）：真实 LLM 回归循环的直接产物，**这是"低于 80% 即裁剪规则"减法机制的最可信数据源**——它会告诉你哪些规则 LLM 真的天天违反、哪些规则写了但从不被违反（后者可删）。

**空检索样本的校验强度说明**：`empty_retrieval_golden.md` 仅含第零/九/十章（空检索兜底场景不需要完整十章）。在 L2 档位下第 16 项证据分数格式（无计分子表可校验）直接跳过；第 4 项标签密度、第 17 项去同质化虽会执行，但因样本内容量小/无证据表数据行，检测逻辑实质不触发——该任务验证的是"空检索场景不误报"，而非 L2 全量校验路径的完整覆盖（后者由 dr-l2 任务承担）。

低于 min_pass_rate（默认 80%）的校验项会列入"优先考虑删除该规则或改为脚本兜底"清单——按方案先做减法，不继续加提示词；live/freeform 数据接入后，该清单才有实际裁剪依据。

## 免责声明

输出仅供科研探索与决策辅助参考，不构成医疗/投资/法律建议，完整条款见 SKILL.md 或 references/output-template.md。

## License

MIT
