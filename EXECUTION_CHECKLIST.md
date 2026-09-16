# InterSci-KD 执行导航清单（AI 快速索引）

> **用途**：执行时遇到任何不确定，先查本表定位到 SKILL.md 对应章节。不包含规则细节。

## 1b. 我该输出哪个档位？（快速通道，P1-4）

| 用户输入特征 | 档位 | 输出 |
| :--- | :--- | :--- |
| 无关键词（默认） | **仅 L0，暂停等待** | 30 秒卡片 + 定位问题（A/B/C）+ 展开选项（"继续"推荐置前） |
| 含"分析/研究/详细/帮我看看"等实质内容词 | L0 + L1 连续 | 30 秒卡片 + 3 分钟速览（不暂停，直接给；L2 前仍暂停） |
| "快速/结论/30 秒" | 只给 L0 | 30 秒决策卡片 |
| "完整/报告/审计" | L0→L1→L2 一次给 | 三档分别校验 |
| "JSON/专家" | L3 | L2 + JSON 审计日志 |
| "精简/3分钟"/"继续"（首轮后） | L1 | 五块结构 |

## 1. 我该用哪个模式？

| 用户输入特征 | 模式 | 查阅章节 |
| :--- | :--- | :--- |
| 包含“更新/修改/补充” | 局部更新 | SKILL.md §2 |
| 包含“对标/竞品/基准”+具体数值 | 外部对标 | SKILL.md §2 |
| 提供 ≥2 篇独立论文/课题 | 批量对比 | SKILL.md §2 |
| 提供 ≥1 篇具体论文 | 锚定蒸馏 | SKILL.md §2 |
| 仅有方向描述 | 图谱生成（默认） | SKILL.md §2 |

## 1c. 黑话检查清单（输出前必查）

**用户输出中禁止出现以下术语**（违反则输出无效）：

- 内部规则编号：§1、§14、规则1、规则2、规则3
- 脚本/文件名：score_evidence.py、validate_output.py、search_papers.py、scp_tools.py、SKILL.md、output-template.md、plain-language-map.md、evidence-rubric.md
- 配置键名：threshold_note、CORE_EVIDENCE_THRESHOLD、mode_router、rule2_triggered、mock_fallback、valid_evidence_count、detailed_scores、base_weight、decay_factor、confidence_multiplier
- 内部架构术语：L1/L2/L3/L4 推理层、双层三档、审计层、展示层

**必须翻译成人话**：见 output-template.md 术语对照表。每写完一段检查是否有泄漏。

## 2. 计分时怎么查表？

| 要查什么 | 去哪里查 |
| :--- | :--- |
| 证据类型权重 | `evidence-rubric.md` §1 或 `scripts/config/evidence_weights.json` |
| 置信度乘数 | `evidence-rubric.md` §2 |
| 年份衰减系数 | `evidence-rubric.md` §3 |
| 三选一结论矩阵 | `evidence-rubric.md` §14 |

## 3. 闸口检查顺序（强制顺序，不可跳跃）

1. 规则1（score<0.5）→ 活检查点，暂停输出 A/B/C
2. 规则2（有效论文=0）→ 全文降级为【推断】
3. 规则3（外部对标偏差>1.5×）→ 硬终止
**详细定义**：SKILL.md §4

## 4. 输出档位速查

见本文档顶部「1b. 我该输出哪个档位？（快速通道）」——档位判定以该表为单一事实源。**关键规则（v4.4.1）**：默认**仅输出 L0 并暂停**，用户指令逐档展开；校验器必须显式传 `--level L0/L1/L2/L3`，禁止省略。

## 5. 脚本故障自救

| 故障 | 动作 | 声明位置 |
| :--- | :--- | :--- |
| search_papers.py 报错 | WebSearch 手动抽 10 条 | 第九章 |
| score_evidence.py 报错 | AI 手算（逐条按 evidence-rubric.md 查表） | 第九章 |
| scp_tools.py 不可用 | 自动 Mock，继续执行 | 第九章（标注模拟数据） |

## 6. 输出校验（交付前必跑）

| 校验项 | 命令 | 失败处理 |
| :--- | :--- | :--- |
| 全量校验 | `python scripts/validate_output.py --input <简报.md> --level <L0/L1/L2/L3> --json <score.json>` | 修复后重跑，硬失败=0 才交付（21 项编号检查，含指令泄漏与计分签名检测） |
| 单独计分校验 | `python scripts/score_evidence.py --input-json <papers.json> --domain <域>` | 确认 level/valid_evidence_count/rule2_triggered |
| §14 矩阵强校验 | validate_output.py 自动执行 | 中等等级不得写优先整合；弱等级且有效论文<3不得写持续追踪 |
