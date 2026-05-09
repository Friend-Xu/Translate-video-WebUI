# Workflow: Mode Multi-Agent — 六 Agent 翻译 DAG

**适用**: Phase 3（完整流水线）
**模式**: `mode: "multi-agent"`
**Agent 数量**: 6（Director → Glossary → Translator → Mapper → Reviewer → Polisher）

## DAG 总览

```
                          Director
                         （分析+策略）
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
          Glossary        Translator      (策略广播)
         （术语表）       （核心翻译）
              │               │
              │               ▼
              │       Structural Mapper
              │       （句子对齐）
              │               │
              └───────┬───────┘
                      ▼
                  Reviewer
                 （MQM 审查）
                      │
                      ▼
                  Polisher
                 （润色修复）
```

## 步骤

### Step 1: Director Agent
```
输入:
  - {workdir}/01_extract/source.srt
  - {workdir}/02_translate/glossary.json（如已存在）

输出:
  - {workdir}/02_translate/task-analysis.json
  - {workdir}/02_translate/strategy.json

策略决策项:
  - content_type: 内容类型（教程/访谈/演讲/娱乐）
  - formality: 语域（正式/半正式/口语）
  - special_requirements: 特殊要求（术语/文化适配/长度限制）
  - recommended_approach: 推荐翻译策略

启动方式: foreground, 1 轮
Quality Gate: strategy.json 格式有效，content_type 正确识别
```

### Step 2: Glossary Agent
```
输入:
  - {workdir}/01_extract/source.srt
  - {workdir}/02_translate/strategy.json

输出:
  - {workdir}/02_translate/glossary.json

术语表格式:
  [
    {
      "source": "原文术语",
      "target": "目标译法",
      "context": "出现的句子编号",
      "notes": "翻译说明"
    }
  ]

启动方式: foreground, 1 轮
Quality Gate: 每条术语含 source/target/context，无循环引用
```

### Step 3: Translator Agent
```
输入:
  - {workdir}/01_extract/source.srt
  - {workdir}/02_translate/glossary.json
  - {workdir}/02_translate/strategy.json

输出:
  - {workdir}/02_translate/machine.srt
  - {workdir}/02_translate/translate-log.json

启动方式: foreground, 最多 2 轮（含修复）
Quality Gate: 格式校验通过，术语一致性检查通过
```

### Step 4: Structural Mapper Agent
```
输入:
  - {workdir}/01_extract/source.srt
  - {workdir}/02_translate/machine.srt
  - {workdir}/02_translate/strategy.json

输出:
  - {workdir}/02_translate/alignment.json
  - {workdir}/02_translate/structure-report.json

alignment.json 格式:
  [
    {
      "source_index": 1,
      "target_index": 1,
      "type": "1:1" | "1:N" | "N:1" | "N:M",
      "confidence": 0.0-1.0
    }
  ]

启动方式: foreground, 1 轮
Quality Gate: 覆盖所有源句子，无交叉映射
```

### Step 5: Reviewer Agent (MQM)
```
输入:
  - {workdir}/01_extract/source.srt
  - {workdir}/02_translate/machine.srt
  - {workdir}/02_translate/glossary.json
  - {workdir}/02_translate/alignment.json（如有）
  - {workdir}/02_translate/structure-report.json（如有）

输出:
  - {workdir}/02_translate/review-report.json

启动方式: foreground, 1 轮
判定: PASS / WARN / FAIL → 决定是否进入修复循环
```

### Step 6: Polisher Agent
```
输入:
  - {workdir}/02_translate/machine.srt
  - {workdir}/02_translate/review-report.json
  - {workdir}/01_extract/source.srt

输出:
  - {workdir}/02_translate/machine.srt（覆盖写入最终版）
  - {workdir}/02_translate/polish-log.json

启动方式: foreground, 1 轮
```

## 修复循环

```
Reviewer FAIL → Conductor 判断 FAIL 维度:
  - Accuracy/Terminology fail → 回退到 Translator (Step 3)
  - Fluency/Style fail → 回退到 Polisher (Step 6)
  - 结构失配 → 回退到 Structural Mapper (Step 4)
  - 多维度 fail → 回退到 Translator

最多 2 次修复循环。2 次后人工介入。
```

## 并行优化

- Director 完成后，Glossary 和 Translator 在理论上可并行
- 实际上 Translator 依赖 Glossary 的术语表以保证术语一致
- 推荐: Glossary 先跑（~1 min），Translator 在其后启动
- Structural Mapper 依赖 Translator 产出，必须串行
- Phase 2 Split-Brain 的两个 Translator 可以完全并行
