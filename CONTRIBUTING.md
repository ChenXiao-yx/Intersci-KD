# CONTRIBUTING

## 如何扩展新领域（零代码，全配置）

**无需修改任何 Python 代码**，所有扩展通过 `config/unified_config.yaml` 完成。

### 步骤 1：添加领域关键字

在 `domain_identification` 段中添加新领域的识别关键字：

```yaml
domain_identification:
  agriculture_keywords:
    - "农业"
    - "crop"
    - "种植"
    - "土壤"
    - "农机"
    - "精准农业"
```

系统通过关键字匹配自动识别领域，支持中英文混合。

### 步骤 2：添加领域映射

在 `domain_map` 中确定该领域复用哪套证据权重体系：

```yaml
domain_map:
  agriculture: "biotech"   # 复用 biotech 的证据权重
```

可选值：`biotech`、`social`、`business`。若不指定，默认使用 `biotech`。

### 步骤 3：添加赛道推荐

在 `direction_pool` 三档（蓝海/中等/红海）中各添加一条推荐赛道：

```yaml
direction_pool:
  蓝海:
    农业: "精准农业+AI遥感监测（政策补贴驱动）"
  中等:
    农业: "智慧农场管理系统"
  红海:
    农业: "普通农产品电商"
```

### 步骤 4（可选）：添加专属证据权重

若新领域有独特的证据类型，可在 `evidence_weights` 中自定义：

```yaml
evidence_weights:
  agriculture:
    field_trial: 3.0
    satellite_data: 4.0
```

### 步骤 5（可选）：添加瓶颈与风险提示

在 `bottleneck_matching` 中添加该领域特有的发展瓶颈：

```yaml
bottleneck_matching:
  农业: "规模化生产工艺难度大，专利壁垒高"
```

在 `warning_map` 中添加领域特有的风险警告：

```yaml
warning_map:
  农业: "注意农药残留限量标准（GB 2763）"
```

### 验证

完成以上步骤后，运行以下命令验证领域识别：

```bash
python -c "
from intersci_kd.domain_identifier import DomainIdentifier
di = DomainIdentifier()
result = di.identify('精准农业土壤监测传感器')
print(f'识别领域: {result}')
"
```

预期输出：`识别领域: agriculture`

---

## 开发环境搭建

```bash
git clone https://github.com/your-repo/intersci-kd-skill.git
cd intersci-kd-skill
pip install -e ".[dev]"
pytest tests/ -v --ignore=tests/test_network.py
```

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