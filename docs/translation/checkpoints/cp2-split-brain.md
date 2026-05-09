# Checkpoint CP2 — Split-Brain 模式验证完成

**阶段**: Phase 2 (Split-Brain 模式) 完成首次双通道翻译 + 选优后触发
**类型**: 硬节点，不可跳过

## 进入条件

- [ ] CP1 已通过
- [ ] Split-Brain 模式至少完成 1 次完整运行
- [ ] Translator A 和 Translator B 产出均存在（`machine-a.srt`, `machine-b.srt`）
- [ ] Reviewer 已完成双份对比评审，产出 `review-report.json`
- [ ] 选优结果已记录

## 验证清单

### 双通道独立性
- [ ] Translator A 和 Translator B 使用不同的翻译策略（直译优先 vs 意译优先）
- [ ] 两份翻译内容有实质性差异（非逐字相同）
- [ ] 两份翻译均通过格式校验（SRT 索引连续、时间轴正确）

### 选优合理性
- [ ] Reviewer MQM 评分覆盖 5 个维度
- [ ] 两个版本的各维度得分有区分度
- [ ] 选优依据充分（不只是总体分高，有具体优势项说明）
- [ ] 合并策略合理（是否从两个版本中各取优势段落）

### 质量对比
- [ ] Split-Brain 最终 composite >= Simple 模式 composite + 0.3
- [ ] 至少 Accuracy 和 Fluency 两个维度有明显提升
- [ ] 翻译成本和时间在可接受范围（2x API 成本，< 1.5x 时间）

## 用户确认模板

```
Split-Brain 模式验证完成。

翻译对比：
  Translator A (直译优先): MQM composite = {X}, 优势维度 = {...}
  Translator B (意译优先): MQM composite = {Y}, 优势维度 = {...}
  选优结果: {A/B/混合}

对比 Simple 模式：
  Simple composite = {Z}
  Split-Brain composite = {max(X,Y)} (+{delta})

成本分析：
  API 调用次数：{N}（Simple = {M}）
  总耗时：{T}（Simple = {S}）

请确认以下决策：
1. Split-Brain 质量提升是否值得 2x 成本？
2. Translator A/B 的策略差异是否需要调整？
3. 是否接受当前选优/合并策略？还是需要人工选优？
4. 进入 Phase 3 (Multi-Agent) 还是停在 Split-Brain？

确认后进入下一阶段。
```

## 确认后动作

- 更新 `pipeline-state.json.lastCheckpoint = "cp2"`
- 根据用户决策进入 phase3 或保持在 phase2
