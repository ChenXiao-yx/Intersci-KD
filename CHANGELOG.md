# InterSci-KD 修订日志（版本历史）

**v3.x 早期版本**：实验性版本，references/与scripts/分离目录设计，主文件松散无统一章节。v4.x向后兼容evidence-rubric.md与output-template.md，旧证据表/简报可复用。

**v4.0.0-skill（2026-08-12）**：8章节+Frontmatter+快速参考卡标准化重构。章节2五种模式优先级；章节3计分校准；章节4闸口3条(估算偏差新增)；章节5协议6步(免责声明新增+异常处理)；章节7约束12条(表格列数+极简提问)；章节8脚本退出码+fail-fast；Frontmatter新增6元字段tags扩至10个。

**v4.1.0-skill（2026-08-12）**：新增4层推理模型总览(L1/L2/L3/L4)。新增10个SCP数据工具集及环境变量。新建scp_tools.py网关客户端(mock降级)；search_papers.py检测Key自动委托。evidence-rubric.md新增§9映射。requirements.txt启用requests。

**v4.2.0-pilot（2026-08-12）：飞行员操作手册大重构（6 大变更）**
1. 🔴 死闸口→活检查点：score<0.5 不再强制终止，输出 A/B/C 三段式诊断单交还用户决策权（章节4规则1）
2. 📦 章节3瘦身：64行静态表格剪切至 references/evidence-rubric.md §10~§16，主文件仅留9行引用协议（瘦身至≤50行）
3. 🛠️ 失败模式速查表：新增3行一线自救+兜底（检索不足扩年限/无DOI降权/脚本报错手算，章节5异常处理前）
4. 🧠 章节1精简：35行哲学叙事外置为 references/philosophy.md，主文件仅留4条核心执行约束
5. 🚦 模式路由：Frontmatter 新增轻量/标准/专家三档，章节5第5步前置检查（轻量仅0/7/9三章）
6. 📏 总行数压缩：从 341 行压缩至 ≤300 行，注意力占用降低 12%+

**v4.3.0-mcp（2026-08-12）：MCP Streamable HTTP 架构迁移**
1. 🔑 单一通用 API Key：10 个独立 API Key 统一为 `SCP_HUB_API_KEY`，所有工具共用同一认证凭证
2. 🌐 MCP 协议支持：scp_tools.py 重写为 MCP Streamable HTTP 客户端，支持 JSON-RPC 2.0 的 initialize/tools/list/tools/call
3. 🔗 独立端点架构：每个工具有独立 MCP 端点 URL（如 `/mcp/43/Sciverse`），替代原统一网关
4. 🛡️ 增强响应解析：为 10 个工具实现专用响应解析器，支持不同格式归一化
5. 🚨 智能错误处理：自动检测后端不可达（如 TCGA）、解析失败、认证错误等场景，分级降级
6. 📊 新增领域映射：domain 参数扩展至 14 个选项（新增 drug/regulatory/oncology/chemistry/material/patent/knowledge）

**v4.4.0-skill（2026-09-14）：双层三档架构 + 审计层硬伤修复（8 大变更）**
1. 🎯 双层三档架构：展示层（L0 卡片→L1 五块→L2 十章）+ 审计层（十章+JSON），同源映射；默认输出改 L0 卡片（30 秒决策）
2. 🏷️ 标签双轨：人读符号（✅🔶❓）↔ 机读文字（【确证】【推断】【无法判断】），100% 可逆映射；渲染时自动转换
3. 📖 人话翻译固定映射：新建 references/plain-language-map.md，禁止 LLM 自由发挥
4. 🔴 domain_map 补全：evidence_weights.json 补 hardware/AI/drug/material 等键；score_evidence.py 未知 domain 显式报错（修复静默 fallback biotech）
5. 🛡️ Mock 强隔离：scp_tools.py 加 is_mock:true；score_evidence.py 加 valid_evidence_count + rule2_triggered；mock 不计有效论文，直接触发规则 2 全文降级
6. ⚖️ 核心证据门槛：总分≥8.0 但无单条 base_weight≥2.5 → cap 到 yellow（threshold_note 字段）【v4.4.1 已废弃：改判 insufficient】
7. 📋 validate_output.py：新建校验器，8 项检查（首行第零章/三选一/有效性状态/标签密度/免责声明/L0-审计层一致/§14矩阵强校验/DOI一致性）；档位感知（L0/L1 跳过十章专属校验）
8. ✏️ 同步硬约束：SKILL.md/output-template.md/EXECUTION_CHECKLIST.md 三处同步改；evidence-rubric.md §14.1 黄区不得写"优先整合"强校验；新增 L0/L1/L2 golden 样本 + 空检索兜底样本

**v4.4.1-skill（2026-09-14）：运行时对账修复（基于真实对话复盘 + 双子代理交叉验证，16 项）**
1. 🚦 默认档位纠偏：changelog v4.4 声称"默认仅 L0"但正文三处仍为三档全出——统一为「首轮仅 L0 卡片+定位问题并暂停，按用户指令逐档展开」；定位回答成为 L1/L2 结论输入
2. 🔢 进度条口径：L0 模板删除 `/8.0` 分母（与禁令自相矛盾），绿区分值改用 core 层合计 total_core；校验器对 /8.0 旧格式改判硬失败
3. 📅 时间线矛盾清除：L0"4周内具体动作"与第八章"3段6周时间表"改为无时间维度的验证动作
4. 🏷️ 有效性状态统一六枚举（快速卡/约束表原为四枚举，缺待核验/监管批准）
5. 📉 衰减公式对账：文档"≥25年固定0.5"改为与脚本一致的线性衰减地板 0.3
6. 🛡️ 计分器兜底硬化：删除与 evidence_weights.json 漂移的硬编码权重表（缺 9 键、FDA 批准静默落 0.3 分），配置缺失改为 fail-fast；补检高等级类型集合包含 FDA_NMPA_approval（同时保留工具层 source_type 值 FDA_NMPA）
7. 📄 arXiv DataCite DOI（10.48550/arXiv.x）识别为预印本，标"待核验"、不计有效论文、不进 core
8. 🧪 mock 降级指引与规则 2 对齐：全 mock 不得照常出三选一结论
9. 🎚️ validate_output.py 的 --level 改必填，删除从交付物内嵌 `> **档位**：` 标记识别档位的路径（内部标记泄漏 + L0 被误按 L2 严校）；L0 校验集移除第 1 项（9 项）；L2/L3 为 18 项（第 16 项仅 L0）
10. ⚠️ 校验 13（年份/卷期一致性）降为警告，避免在线先发跨年论文误杀
11. 🧹 cap-to-yellow 旧表述全部改为 insufficient 语义
12. 🗂️ 删除 4 个 .tmp_*.json 残留，.gitignore 增加 .tmp_* 规则
13. 📦 部署同步：已安装副本必须与工作区同源（SKILL.md + scripts/ + references/ + examples/），旧版单文件副本作废

**v4.4.1-skill 追加（2026-09-15）：TRAE-code-review 收尾审查（双子代理独立验证，7 项）**
14. 🐛 修复 threshold_note 语义重载：重复 DOI/格式错误计数曾被追加进 threshold_note，校验⑥⑦把任何非空 note 当 yellow 降级，导致 green+1 条重复的合规「优先整合」被双重硬失败——计数只走 duplicate_count/doi_format_error_count 独立字段，校验器改为仅按 level 判定
15. 🛡️ 补检类型集合补 FDA_NMPA_approval 标准键（保留 FDA_NMPA 兼容 scp_tools mock 层）；search_papers 年份基准改 datetime.now().year（消除跨年 confidence 虚高）
16. 🧹 删除零调用的 _supplemental_websearch 死代码；CORE_EVIDENCE_THRESHOLD 改读 config 单一事实源；校验结果三态化（pass/warning/fail/skipped），JSON 新增 warnings 计数，警告不再计入 passed；校验器 docstring 与 --level 必填示例同步

**v4.4.2-skill（2026-09-15）：L0 卡片排版优化 + 免责声明分级感知（5 项）**
17. 📝 L0 免责声明精简版落地：校验器 check_disclaimer 改为 L0/L2 分级感知——L0 只检查精简版前缀「本简报基于公开文献生成」+ 关键短语「不构成研究决策依据」；L1/L2/L3 仍检查完整版 4 个关键短语。消除模板"一句话精简版"规则不可执行的死代码矛盾
18. 📦 L0 模板新增「证据速览」可选段：仅证据不足/混合场景使用，3 条以内每条一行，帮助用户在 30 秒内理解结论原因
19. 📐 L0 模板移除 2 个 `---` 分隔线，改为空行+加粗分隔，减少 30 秒卡片的视觉碎片化
20. 📏 L2 新增段落长度规则：每段不超过 4 行（约 80 字），超过时拆分或改用列表
21. 🔍 L2 章间去重规则细化：明确第零章/第九章结论属豁免范围，第一章到第八章不得重述结论

**v4.5.0-skill（2026-09-15）：取消进度条，改为「核心证据分 + 满分」简洁展示（4 项）**
22. 🚫 移除 L0 卡片的进度条可视化（`[██████░░░░]`），改为直接展示「核心证据分 X.X（满分 8.0，≥8.0 为强证据门槛）」，用户一眼看清分数与满分
23. 🔢 校验器第 16 项由 `check_progress_bar_consistency` 重命名为 `check_evidence_score_format`，校验等级标签（强/中/弱）与分数数值的一致性 + 满分 8.0 标注
24. 📋 等级标签统一为「强/中/弱」（对应 green/yellow/red），分数阈值：强≥8.0 / 中 4.0-7.99 / 弱<4.0；insufficient 不显示分数
25. ✏️ 同步更新 output-template.md、evidence-rubric.md、examples 黄金样本与 EXECUTION_CHECKLIST.md

**v4.4.3-skill（2026-09-15）：SCP 网关降级链路语义化重构（基于指尖心理疲劳检索复盘，4 项）**
26. 🚦 拆分 `parse_error` 误导性标签：原分支把「后端返回空结果（count=0/data=[]）」与「JSON 解析失败」混到同一警告，日志有误导性。scp_tools.py 新增 `is_empty_result` 判定（json.loads 成功 + count==0 或 data 列表为空），空结果改走 `empty_result` 分支，返回空 papers + `status="empty_result"`；真正的 JSON 解析失败才保留 `parse_error` 标签
27. 🔄 领域 fallback 自动切换：`hardware`/`material` 域命中 `empty_result` 时，search_papers.py 与 _try_scp_delegate 自动 fallback 到 `sciverse`（学术文献，覆盖传感器/可穿戴/嵌入式等更广概念），避免 SciGraph-Material 材料图谱查生物医学关键词必然返回空的问题。fallback 成功用 `sciverse (fallback from scigraph-material)` 标注 source；fallback 也失败才走原 mock 路径
28. 🛡️ empty_result 不再走 mock 兜底：原逻辑把「后端正常返回空」误降级为 3 条 mock 数据，虽带 is_mock 不计分，但 source_count 会虚高、误导用户以为检索到文献。新逻辑返回真实空 papers，让 score_evidence 的 valid_evidence_count=0 准确反映「确实没查到」
29. 📋 日志措辞三态化：`INFO [empty_result]`（后端空，正常）/`WARNING [parse_error]`（JSON 解析失败，需排查）/`WARNING [network_error/auth_error]`（网关层故障）各自清晰，AI 与用户能从 stderr 直接判断故障层级

**v4.5.2-skill（2026-09-15）：Windows/PowerShell 调用兼容性修复（基于毫米波雷达睡眠监测蒸馏复盘，3 项）**
30. 🔑 SKILL.md 第 5 步「确定性证据计分」章节补 Windows 提示：`--single` 命令行内联 JSON 在 PowerShell 下易因引号转义损坏（双引号串中 `\` 非转义符、单引号串被参数绑定器拆解），明确「Windows/PowerShell 必须用 `--input-json` 文件方式」，Unix 可继续用 `--single` 多拼
31. 📋 SKILL.md §8.2 脚本速查表调整 `score_evidence.py` 调用要点：「--input-json 文件批量优先；--single 仅 Unix 可用；Windows/PowerShell 禁用 --single」
32. 🛠️ score_evidence.py 的 argparse 新增 epilog 帮助文本：显示 Windows/PowerShell 提示与 `--input-json` 示例，`--help` 输出时直接可见，避免用户踩坑

**v4.6.0-skill（2026-09-15）：P0 严重缺陷修复 + 测试套件建立（基于系统审阅修改清单，8 项）**

33. 🔧 P0-1 SCP 工具证据类型归一化三层防御：TOOL_REGISTRY evidence_type 全部对齐 evidence_weights.json 标准键（origene-fdadrug: FDA_NMPA→FDA_NMPA_approval, origene-ncbi: NCBI_database→External_validation, origene-search/chembl/pubchem: →Journal_article, origene-tcga: →External_validation）；call_gateway 新增 _inject_standard_type 注入 type 字段；normalize_type SOURCE_TYPE_VENUE_MAP 扩展 14 个数据库类型映射（fda_drug/ncbi_gene/chembl_activity/scholar_kg/knowledge_graph 等），确保 SCP 数据库证据不再静默落 default_weight(0.3)
34. 🔧 P0-4 SCP 解析器年份硬编码修复：新增 _extract_year/_extract_year_from_text 辅助函数，11 个解析器+mock+fallback 全部改用动态年份提取（优先 publication_published_year/year/pub_year/published_year），无年份返回 None 而非硬编码 2024，score_evidence.calc_decay 走"未提供年份→不衰减"分支
35. 🔧 P0-6 domain 参数统一：新建 config_loader.py 提供 get_valid_domains()（从 evidence_weights.json domain_map 动态读取），search_papers.py 与 score_evidence.py 的 --domain choices 统一为 15 个域（含 default）
36. 🧹 P0-7 删除 validate_output.py 的 detect_level 死代码，run_all 改为 level=None 时 raise ValueError
37. 🔧 P0-3 L0 条件化双结论修复：output-template.md L0 模板改为"唯一主结论+引用块条件分支"格式；extract_conclusion 按位置取最先出现的结论；check_three_choice_conclusion 容错引用块中的条件分支
38. 🔧 P0-5 补检自动执行：search_papers.py 新增 _run_supplemental_search 函数，main() 检测 supplemental_needed 且 Key 可用时自动追加一轮检索（系统综述/Meta/RCT/FDA/临床指南），DOI 去重+重排+审计重建
39. 🧪 P0-2 测试套件建立：新建 tests/ 目录（conftest.py + 6 个 fixture + 5 个测试文件共 77 个用例），覆盖计分器边界、类型归一化、SCP 工具解析器、校验器检查项、检索逻辑；pytest tests/ 全绿
40. 🔧 P1-7 提取 _load_dotenv：config_loader.py 提供 load_dotenv()，scp_tools.py/search_papers.py 的 _load_dotenv 委托调用，消除三处重复代码

**v4.6.0-skill 追加（2026-09-15）：系统优化方案落地（P0/P1/P2，7 项）**

41. 🔖 P0-1 版本号三处统一 + CI 对账：SKILL.md frontmatter 4.4.1→4.6.0-skill，与 pyproject.toml(4.6.0) 对齐；check_consistency.py 新增 _check_version_consistency（frontmatter↔pyproject↔CHANGELOG 当前版本行）；修订日志外移 CHANGELOG.md
42. 📊 P0-2 黄金样本重做：card/brief 黄金样本从 CGM 模拟主题重写为 DR 主题（与 full_output_golden.md 真正同源，核心证据分 10.65/有效 7/10 与完整审计一致）；新增 examples/dr_papers.json 与三档 .score.json（由 score_evidence.py --domain AI 对同源 10 条证据实跑生成，非手写，三份内容一致）；同步修复校验器三处潜在缺陷（第 1 项 level 变量 NameError、第 2 项引用块主结论「> **结论：**」误判、第 9 项 DOI 链接+URL 双计误报）；新增三档黄金样本参数化测试 + 修复回归测试
43. 🔢 P0-3 SCP 工具数单一事实源：scp_tools.py 新增 TOOL_COUNT/ENDPOINT_COUNT 常量（11 工具/10 端点，Sciverse 端点提供 2 工具）；SKILL.md/README.md 统一口径；check_consistency.py 新增 _check_tool_count_consistency（扫描 "N 个 SCP" 声明，非 {TOOL_COUNT, ENDPOINT_COUNT} 即报错）
44. 🎚️ P1-1 core 证据门槛域级适配（方案 A）：evidence_weights.json 新增 core_evidence_threshold_by_domain（AI=1.5、hardware=2.0、material=2.0，域级优先回退全局 2.5）；score_evidence.py 新增 _resolve_core_threshold 并在输出暴露 core_evidence_threshold；AI/hardware/material 域以会议论文与原型实现为主，不再永远 insufficient；新增 papers_ai_conference fixture + TestAIDomain 测试（含 biotech 对照）；原 TestCoreEvidenceThreshold 改用 biotech 域验证全局门槛仍生效
45. 🛡️ P1-2 指令性文字收口：output-template.md 指令统一收口到文件头部 SYSTEM INSTRUCTIONS 区块，删除分散的「此行是对 AI 的指令」注释；validate_output.py 新增第 20 项「指令性文字泄漏检测」（全档位硬门禁，含引用块）；四个黄金样本清除内嵌指令注释；SKILL.md/README/EXECUTION_CHECKLIST 同步 19→20 项
46. ✂️ P1-3 SKILL.md 瘦身：317→200 行（-37%）；可脚本化规则移出（19 项校验清单详述/黑话术语对照表/无依据预测关键词表/标签密度/DOI 格式/去同质化，均由 validate_output.py 兜底）；保留判断逻辑（五种模式/闸口 3 规则/矩阵判定顺序/档位默认规则/自校验一行）；工具端点表移交 README.md；章节 6/7 合并压缩
47. 🧪 P2-1 端到端回归 + 遵守率度量：新建 tests/regression/（tasks.json 9 任务 + run_regression.py + baseline.json + 4 个领域 fixture）；9 任务全 PASS，20 项校验遵守率基线全 1.0；低于 80% 的规则自动列入"优先删除或改脚本兑底"清单；测试套件 77→92 用例全绿

---

**当前版本：4.6.0-skill**（与 SKILL.md frontmatter、pyproject.toml 三处一致，由 scripts/check_consistency.py 对账；变更历史只追加不改写）
