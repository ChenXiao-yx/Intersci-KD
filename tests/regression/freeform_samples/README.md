# freeform_samples — 真实 LLM 自由生成样本（P1-2）

这里是 `llm_freeform` 回归任务的样本目录，与 examples/ 下的**黄金样本自证基线**不同：
放入的应是 **LLM 对任务提示自由生成的原始输出**（未经人工修饰），用于测出各校验项的
**真实**遵守率——这才是驱动"低于 80% 即裁剪规则"减法的信号源。

## 如何提供样本

1. 让 LLM 按 SKILL.md 流程对 tasks.json 中对应 `prompt` 自由生成（如 dr-freeform-l0 → L0 卡片）
2. 将输出原样保存为 `<task-id>.md`（如 `dr-freeform-l0.md`）
3. 运行 `python tests/regression/run_regression.py --baseline tests/regression/baseline.json`
   ——任务状态从 pending 变为 measured，`freeform_check_pass_rate` 出现真实数据
4. 确认数据有效后 `--update-baseline` 写入 freeform_baseline

## 纪律

- 样本必须是 LLM 原始输出，不得手工修复后再放入（否则又是自证）
- 每个样本保留生成时的模型/日期记录（文件头注释行即可）
