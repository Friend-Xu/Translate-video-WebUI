# Context Budget — 上下文管理规则

## 核心原则

每个 Agent 只加载它**完成任务所需的最小文件集合**。不传全量，不预加载。

## 上下文预算表

| Agent | 必读文件 | 预估 Token | 最大轮次 |
|---|---|---|---|
| Director | source.srt (完整) + glossary.json (如有) | ~8K | 1 |
| Glossary | source.srt (完整) + strategy.json | ~6K | 1 |
| Translator | source.srt (完整) + glossary.json + strategy.json | ~12K | 2 |
| Structural Mapper | source.srt + machine.srt + strategy.json | ~10K | 1 |
| Reviewer | source.srt + machine.srt + glossary.json | ~10K | 1 |
| Polisher | machine.srt + review-report.json + source.srt | ~10K | 1 |

## 上下文传递规则

1. **用路径，不用内容**：Agent prompt 中写文件路径（如 `D:\Workspace\Translate_video\{workdir}\02_translate\source.srt`），让 Agent 自己去 Read，不要把文件内容内联到 prompt 里。

2. **自包含 prompt**：每个 Agent 的 prompt 必须包含：
   - 角色定义（一句话，引用 agent-reference 路径）
   - 输入文件路径列表（绝对路径）
   - 必读 reference 文件路径列表
   - 输出文件路径和格式要求
   - 自检清单
   - 禁止做的事情

3. **零共享假设**：并行 Agent 之间不共享任何上下文。Phase 2 中 Translator A 和 Translator B 独立读取 source.srt，独立产出。不共享 memory。

4. **状态外置**：Agent 之间通过文件系统传递状态。pipeline-state.json 是唯一的内存状态，由 Conductor 维护。Agent 不读取 pipeline-state.json。

## 主会话上下文保护

Conductor（主会话）自身也需要保护上下文：

- 不把 Agent 的完整产出物贴回主会话，只读摘要
- Agent 产出物直接写文件，Conductor 通过 Read 工具抽查
- 并行 Agent 时，Agent 运行在 background，完成通知后再处理
- 翻译长视频（>5000 字字幕）时：Conductor 先将 SRT 分段，逐个派发 Translator

## 大文件策略

- `source.srt` 总字符数 > 5000：按 50 条字幕一组分段，每段独立翻译
- Glossary 全量加载（通常 < 2K token）
- `review-report.json` 只传 fail 项给 Polisher（非全量报告）
- Agent reference 文件：每个 Agent 只读自己的 reference 文件，不读其他 Agent 的
