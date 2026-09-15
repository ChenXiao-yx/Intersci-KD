# CONTRIBUTING

## 如何扩展新领域（零代码，全配置）

**无需修改任何 Python 代码**，所有扩展通过 `scripts/config/evidence_weights.json` 完成。领域识别流程见 `references/evidence-rubric.md` §4。

### 步骤 1：添加领域映射

在 `scripts/config/evidence_weights.json` 的 `domain_map` 中添加新领域，确定复用哪套证据权重体系：

```json
{
  "domain_map": {
    "agriculture": "biotech"
  }
}
```

可选值：`biotech`、`social`、`business`、`hardware`、`AI`、`drug`、`material` 等。未在 `domain_map` 中的 domain 会导致 `score_evidence.py` 的 `resolve_domain` 显式报错（不再静默回退 `biotech`）。

### 步骤 2（可选）：添加专属证据类型权重

`evidence_weights.json` 的 `evidence_weights` 段是**扁平结构**（按证据类型，非按 domain 分组）。若新领域有独特的证据类型，可在该段中新增全局证据类型权重：

```json
{
  "evidence_weights": {
    "FDA_NMPA": 5.0,
    "RCT": 5.0,
    "field_trial": 3.0,
    "satellite_data": 4.0
  }
}
```

> **注意**：当前实现不支持按 domain 分组自定义权重。所有 domain 共用同一套 `evidence_weights` 权重表，`domain_map` 只决定领域键到权重域的映射（用于 resolve_domain 解析）。若新领域需要独立的权重体系，需在 `domain_map` 中注册新键，并在 `score_evidence.py` 的 `resolve_domain` 中补充对应逻辑。

### 验证

完成以上步骤后，运行以下命令验证领域识别与计分：

```bash
# 验证 domain_map 解析（未知 domain 会显式报错）
python scripts/score_evidence.py --input-json examples/intersci_input.json --domain agriculture --pretty
```

预期：输出含 `"domain": "agriculture"`、`"level"`、`"valid_evidence_count"` 等字段。若 domain 未在 `domain_map` 中，会报 `ValueError: Unknown domain: 'agriculture'`。

---

## 开发环境搭建

```bash
# 替换 <your-github-username> 为你的 GitHub 用户名
git clone https://github.com/<your-github-username>/intersci-kd-skill.git
cd intersci-kd-skill
pip install -r scripts/requirements.txt
```

### 运行测试

```bash
pip install -r scripts/requirements.txt && pip install pytest && pytest tests/
```

测试覆盖计分器边界、类型归一化、SCP 工具解析器、校验器检查项、检索逻辑等。新增功能时请同步补充测试用例。

## 代码规范

- 遵循 PEP 8 代码风格
- 所有新增方法必须添加类型注解（`-> ReturnType`）
- 私有方法以 `_` 开头
- 测试覆盖率不低于现有水平

## 提交 Pull Request

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'feat: add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 开启 Pull Request