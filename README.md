# InterSci-KD 跨学科知识蒸馏 Skill

> 面向生物医药/智能硬件/新材料领域的 AI 操作手册，基于证据锚定输出结构化知识简报。

## 快速指引

| 文件 | 说明 |
| :--- | :--- |
| **SKILL.md** | 核心规则：蒸馏流程、证据权重、闸口阈值、输出模板 |
| **references/** | 评分规则（evidence-rubric.md）、输出模板（output-template.md）、哲学背景（philosophy.md） |
| **scripts/** | 辅助脚本：论文检索、证据计分、SCP MCP 数据工具 |
| **examples/** | 输入示例与黄金输出样本 |

## 安装

```bash
# Python >= 3.8
pip install -r scripts/requirements.txt
```

核心依赖仅需 `requests`（用于 SCP MCP API 调用）。`score_evidence.py` 和 `search_papers.py`（mock 模式）使用纯标准库，无第三方依赖。

## 环境配置

```bash
# 复制环境变量模板并填入 API Key
cp .env.example .env
```

必填配置：
- `SCP_HUB_API_KEY` — SCP 平台通用 API Key（所有 10 个 MCP 数据工具共用）

## 脚本用法

```bash
# 论文检索（自动选择最相关 SCP 工具）
python scripts/search_papers.py --query "CRISPR gene editing" --top_k 10 --domain AI --pretty

# 证据计分与评级
python scripts/score_evidence.py --input-json papers.json --domain biotech

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

## 项目结构

```
intersci-kd-skill/
├── SKILL.md                  # Skill 核心规则与蒸馏流程
├── README.md                 # 使用说明
├── EXECUTION_CHECKLIST.md    # AI 执行导航清单
├── CONTRIBUTING.md           # 贡献指南
├── .env.example              # 环境变量模板
├── .gitignore
├── scripts/
│   ├── scp_tools.py          # SCP MCP 网关客户端（10 个数据工具）
│   ├── search_papers.py      # 论文检索 CLI（自动委托 SCP 工具）
│   ├── score_evidence.py     # 证据计分引擎
│   ├── requirements.txt      # Python 依赖
│   └── config/
│       └── evidence_weights.json
├── references/
│   ├── evidence-rubric.md    # 证据评分规则
│   ├── output-template.md    # 十章输出模板
│   └── philosophy.md         # 跨学科哲学背景
└── examples/
    ├── example_input.json
    ├── intersci_input.json
    └── full_output_golden.md
```

## 免责声明

输出仅供科研探索与决策辅助参考，不构成医疗/投资/法律建议，完整条款见 SKILL.md 或 references/output-template.md。

## License

MIT
