# Handoff Protocol — Agent 间交接规范

## 交接方式

Agent 之间**不直接通信**。所有交接通过文件系统 + Conductor 完成：

```
Agent A 产出 → 写文件 → Conductor 读状态 → 启动 Agent B → Agent B 读文件 → 继续
```

## 产出物规范

每个 Agent 的产出物必须放在约定的路径，使用约定的格式：

### Director Agent 产出
- `{workdir}/02_translate/strategy.json` — 翻译策略决策
- `{workdir}/02_translate/task-analysis.json` — 任务分析结果

### Glossary Agent 产出
- `{workdir}/02_translate/glossary.json` — 术语表

### Translator Agent 产出
- `{workdir}/02_translate/machine.srt` — 翻译后 SRT（主输出）
- `{workdir}/02_translate/translate-log.json` — 翻译日志
- Split-Brain 模式下：`{workdir}/02_translate/machine-a.srt` 和 `machine-b.srt`

### Structural Mapper Agent 产出
- `{workdir}/02_translate/alignment.json` — 句子对齐映射
- `{workdir}/02_translate/structure-report.json` — 结构保留报告

### Reviewer Agent 产出
- `{workdir}/02_translate/review-report.json` — MQM 审查报告
- 报告格式见 `shared/quality-gates.md`

### Polisher Agent 产出
- `{workdir}/02_translate/machine.srt` — 润色后最终 SRT（覆盖写入）
- `{workdir}/02_translate/polish-log.json` — 润色变更记录

## 状态更新协议

`pipeline-state.json` 是流水线唯一的状态源。**只有 Conductor 可以读写此文件**。Agent 不感知 pipeline-state.json。

Conductor 在以下时机更新状态：
1. Agent 启动前：更新 `updatedAt`
2. Agent 完成后：追加 `completedSteps`，更新 `phase`（如需要）
3. Agent 失败后：追加 `failedSteps`
4. Checkpoint 确认后：更新 `lastCheckpoint`

## 错误恢复

如果某个 Agent 失败：
1. Conductor 记录失败到 `failedSteps`
2. 检查输入文件完整性（是否因上游产出损坏导致）
3. 修复根因后重试（最多 2 次）
4. Phase 3 中单个 Agent 失败：仅回退到该 Agent 的上游，不影响已完成的其他 Agent
5. 2 次重试后仍未通过 → 人工介入

## 文件编码与格式

- 所有 JSON 文件：UTF-8, 2-space indent
- 所有 SRT 文件：UTF-8 with BOM（兼容播放器）
- 换行符：LF
