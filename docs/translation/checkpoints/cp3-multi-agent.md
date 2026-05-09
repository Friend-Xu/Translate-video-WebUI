# Checkpoint CP3 — Multi-Agent 流水线验证完成

**阶段**: Phase 3 (Multi-Agent 模式) 完整 DAG 运行后触发
**类型**: 硬节点，不可跳过

## 进入条件

- [ ] CP2 已通过
- [ ] Multi-Agent 模式至少完成 1 次完整 6-Agent 运行
- [ ] 所有 Agent 产出物存在且格式正确
- [ ] Reviewer MQM 综合评分 >= 4.0

## 验证清单

### Agent 产出完整性
- [ ] Director: `task-analysis.json` + `strategy.json` 存在且合理
- [ ] Glossary: `glossary.json` 存在，术语覆盖全文
- [ ] Translator: `machine.srt` 存在，使用了 glossary 中的术语
- [ ] Structural Mapper: `alignment.json` + `structure-report.json` 存在
- [ ] Reviewer: `review-report.json` 存在，5 维度完整
- [ ] Polisher: 润色后 `machine.srt` 存在，`polish-log.json` 记录所有变更

### 质量指标
- [ ] MQM composite >= 4.0
- [ ] Accuracy >= 4
- [ ] Fluency >= 4
- [ ] Terminology >= 4
- [ ] Style >= 3
- [ ] Locale Convention >= 3

### 流水线健康度
- [ ] 无 Agent 失败超过 1 次（0-1 retry）
- [ ] 无跳过任何 Agent
- [ ] 总耗时在可接受范围
- [ ] API 调用总成本在预算内

### 对比 Split-Brain
- [ ] Multi-Agent composite >= Split-Brain composite
- [ ] Terminology 维度有显著提升（Glossary Agent 效果）
- [ ] Style 维度有显著提升（Polisher 效果）

## 用户确认模板

```
Multi-Agent 流水线验证完成。

翻译质量：
  MQM composite = {X}
  Accuracy={A} Fluency={F} Terminology={T} Style={S} Locale={L}

各 Agent 执行情况：
  Director:    {PASS/FAIL}  {耗时}
  Glossary:    {PASS/FAIL}  术语数={N}
  Translator:  {PASS/FAIL}  retry={R}次
  Mapper:      {PASS/FAIL}  对齐率={P}%
  Reviewer:    {PASS/FAIL}
  Polisher:    {PASS/FAIL}  修复项={M}

对比 Split-Brain：
  Split-Brain composite = {Y}
  Multi-Agent composite = {X} (+{delta})

成本汇总：
  API 总调用：{N}次
  总耗时：{T}
  预估成本：${C}

请确认以下决策：
1. Multi-Agent 模式是否达到"发布级"质量标准？
2. 是否将 Multi-Agent 设为默认模式？
3. 哪些 Agent 可以优化/合并以减少成本？
4. 是否有需要人工干预的翻译段落？

确认后进入 integration 阶段。
```

## 确认后动作

- 如果通过：更新 `pipeline-state.json.lastCheckpoint = "cp3"`，进入 integration
- 如果未通过：记录 fail 维度，针对性优化对应 Agent prompt，重新运行
