# Architecture — 翻译子系统架构

## 当前态（Current State）

单次翻译 + 格式校验 fallback 链。SRT_Translator 对字幕文件执行一次 LLM 翻译，随后通过语义验证 + 术语替换完成质量检查。问题：无结构化质量评分，无对比择优机制，无 Agent 分工。

```
SRT 文件 → SRT_Translator (DeepSeek API) → 语义验证 → 术语替换 → 输出 SRT
              ↑ 3-tier fallback (DeepSeek → DeepSeek retry → 本地回退)
```

## 目标态（Target State）

三种运行模式，共享 pipeline-state.json 与 Conductor 编排层：

### Mode: Simple（Phase 1/2）

```
SRT 文件 → Translator Agent → Reviewer Agent (MQM) → Polisher Agent → 输出 SRT
```

### Mode: Split-Brain（Phase 2）

借鉴 Vimeo 翻译流水线的双通道对比模式：

```
SRT 文件 ─┬─ Translator A (直译优先) ─┐
           │                            ├─ Reviewer (MQM 评分) → 选优 → Polisher → 输出 SRT
           └─ Translator B (意译优先) ─┘
```

### Mode: Multi-Agent（Phase 3）

完整 DAG 流水线，6 个专职 Agent：

```
Director (分析任务, 选策略)
  │
  ├─ Glossary Agent (术语提取 + 一致性规则)
  │
  ├─ Translator Agent (核心翻译)
  │     │
  │     └─ Structural Mapper Agent (句子对齐 + 结构保留)
  │
  ├─ Reviewer Agent (MQM 多维评分)
  │
  └─ Polisher Agent (润色 + 格式修复)
```

## ADR (Architecture Decision Records)

### ADR-1: 采用 Split-Brain 模式提升翻译质量

**状态**: Accepted  
**日期**: 2026-05  
**背景**: 单次翻译无对比参照，质量天花板明显。Vimeo 翻译团队使用双人独立翻译 + 第三人评审的模式，显著降低漏译和误译。  
**决策**: Phase 2 引入 Split-Brain 模式，两份翻译独立产出后由 Reviewer 对比评分选优。  
**代价**: 翻译成本翻倍（2x API 调用），延迟增加约 1.5x（并行执行缓解）。  
**替代方案**:  
- BLEU/COMET 自动评分选优 → 拒绝，自动指标与人工感知相关性弱  
- 单翻译 + 多轮迭代 → 拒绝，缺乏多样性，易陷入局部最优

### ADR-2: 采用 MQM 框架进行质量评分

**状态**: Accepted  
**日期**: 2026-05  
**背景**: BLEU/COMET 等自动指标与人类质量感知相关性低（BLEU ~0.3, COMET ~0.5），不适合作为发布级质量门禁。  
**决策**: 采用 MQM (Multidimensional Quality Metrics) 框架，从 Accuracy / Fluency / Terminology / Style / Locale Convention 五个维度进行 1-5 评分。  
**代价**: 需要 LLM 执行 MQM 评分（额外 API 调用），人工校准初期评分基准。  
**替代方案**:  
- BLEU + COMET 组合 → 拒绝，可解释性差，无法定位具体问题维度  
- 纯人工评审 → 拒绝，不可规模化

### ADR-3: Agent 通信采用文件系统（非内存）

**状态**: Accepted  
**日期**: 2026-05  
**背景**: Agent 间需要传递翻译产物、术语表、评审报告等结构化数据。内存传递会导致上下文膨胀和耦合。  
**决策**: 所有 Agent 间通信通过文件系统（JSON 文件）完成。pipeline-state.json 由 Conductor 独占写入。各 Agent 只读取约定的输入文件，产出到约定的输出路径。  
**代价**: 需要严格的路径约定和输入验证，文件 I/O 增加少量延迟。  
**替代方案**:  
- 内存直传 → 拒绝，上下文膨胀，并行 Agent 无法隔离  
- 数据库 → 拒绝，过度工程化，文件系统已满足需求
