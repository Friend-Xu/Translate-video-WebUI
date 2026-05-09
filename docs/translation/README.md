# Translation Subsystem — 文档索引

本项目对视频翻译流水线的翻译环节进行全面升级，从单次翻译 + 格式校验链重构为三种运行模式（simple / split-brain / multi-agent），采用 MQM 框架进行质量评分，Agent 间通过文件系统通信。

## 项目目标

- 翻译质量从"可读"提升至"发布级"（MQM 综合评分 >= 4.0）
- 支持三种模式按需切换，兼顾速度与质量
- Conductor 编排全流程，支持断点续跑
- 所有中间产物可审计

## 文档地图

| 文件 | 描述 |
|---|---|
| `README.md` | 本文件 — 索引与快速参考 |
| `architecture.md` | 翻译子系统架构总览，含当前态/目标态对比与 3 条 ADR |
| `conductor.md` | Conductor 编排器行为规范 — 核心循环、阶段映射、Agent 启动、修复循环 |
| `pipeline-state.schema.json` | pipeline-state.json 的 JSON Schema 定义 |
| `shared/handoff-protocol.md` | Agent 间文件系统交接规范 |
| `shared/quality-gates.md` | MQM 质量门禁标准与评分规则 |
| `shared/context-budget.md` | 各 Agent 上下文预算与输入文件约定 |
| `checkpoints/cp1-prompt-system.md` | Checkpoint 1 — Prompt 体系搭建完成确认 |
| `checkpoints/cp2-split-brain.md` | Checkpoint 2 — Split-Brain 模式验证完成确认 |
| `checkpoints/cp3-multi-agent.md` | Checkpoint 3 — Multi-Agent 流水线验证完成确认 |
| `workflows/mode-simple.md` | 简单模式 — 单次翻译 + Reviewer 审查 |
| `workflows/mode-multi-agent.md` | 多 Agent 模式 — DAG 工作流详细步骤 |
| `agent-reference/director.md` | Director Agent — 任务分析 + 策略选择 + Agent 派发 |
| `agent-reference/glossary.md` | Glossary Agent — 术语提取与一致性管理 |
| `agent-reference/translator.md` | Translator Agent — 核心翻译执行 |
| `agent-reference/structural-mapper.md` | Structural Mapper Agent — 句子对齐 + 结构保留 |
| `agent-reference/reviewer.md` | Reviewer Agent — MQM 质量审查 |
| `agent-reference/polisher.md` | Polisher Agent — 最终润色与格式修复 |

## Conductor 快速启动

```bash
# 1. 初始化 pipeline-state.json
.venv/Scripts/python -m translation.init --mode simple --source source_file/video.mp4

# 2. 启动 Conductor（在 Claude Code 中）
# 读 docs/translation/conductor.md 作为行为规范
# 读 pipeline-state.json 确定当前阶段
# 按阶段映射表派发 Agent

# 3. 指定模式
# --mode simple:      单次翻译 + 格式校验（当前态，稳定）
# --mode split-brain: 两份翻译 + MQM 评审选优（Vimeo 模式）
# --mode multi-agent: 完整 6-Agent 流水线（Director → Glossary → Translator → Mapper → Reviewer → Polisher）
```
