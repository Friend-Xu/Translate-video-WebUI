# Checkpoint CP1 — Prompt 体系搭建完成

**阶段**: Phase 1 (Simple 模式) 基础设施就绪后触发
**类型**: 硬节点，不可跳过

## 进入条件

- [ ] `agent-reference/` 下 6 个 Agent 规格文件全部完成
- [ ] `shared/quality-gates.md` MQM 评分标准已定稿
- [ ] `shared/handoff-protocol.md` 交接规范已定稿
- [ ] `pipeline-state.schema.json` 已定义
- [ ] `conductor.md` 编排规则已定稿
- [ ] Simple 模式 Translator + Reviewer 可独立运行并产出符合格式的结果

## 验证清单

### Prompt 自包含性
- [ ] 每个 Agent prompt 含完整角色定义
- [ ] 每个 Agent prompt 含输入文件路径（绝对路径）
- [ ] 每个 Agent prompt 含输出文件路径和格式要求
- [ ] 无内联大段 reference 内容（只传路径）

### 文件系统通信
- [ ] Translator 读 source.srt 写 machine.srt
- [ ] Reviewer 读 source.srt + machine.srt 写 review-report.json
- [ ] Polisher 读 machine.srt + review-report.json 写 machine.srt（覆盖）
- [ ] pipeline-state.json 由 Conductor 独占写入

### 质量门禁
- [ ] MQM 5 维度评分标准清晰，每个维度有 1-5 锚点描述
- [ ] PASS/WARN/FAIL 阈值已确定
- [ ] Reviewer 自检清单覆盖 5 维度

## 用户确认模板

```
Phase 1 基础设施搭建完成。

已就绪：
  - Agent 规格文件：6 个（director / glossary / translator / mapper / reviewer / polisher）
  - 共享规范：handoff-protocol / quality-gates / context-budget
  - 编排器：conductor.md
  - Schema：pipeline-state.schema.json

验证结果：
  - Simple 模式端到端测试：{PASS/FAIL}
  - Translator 格式校验：{通过项/总项}
  - Reviewer MQM 报告：{PASS/FAIL}

请确认以下决策：
1. MQM 综合评分阈值（当前 PASS >= 4.0）是否需要调整？
2. Simple 模式是否满足当前需求，还是直接进入 Split-Brain？
3. 术语表是否已有初始版本？是否需要先跑 Glossary Agent？

确认后进入下一阶段。
```

## 确认后动作

- 更新 `pipeline-state.json.lastCheckpoint = "cp1"`
- 根据用户决策进入 phase1 或 phase2
