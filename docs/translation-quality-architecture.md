# 多维翻译质量评估架构设计

*Generated: 2026-05-13 | 基于项目现有架构，兼容 workspace/WebUI/翻译校验系统*

## 概述

在现有 MiniLM 语义相似度验证基础上，增加 Qwen2-0.5B 自然度（PPL）评估，形成三维正交质量评分体系。新增 `QualityAssessor` 层，独立于 `SRT_Translator`，作为译后编排步骤运行，生成统一的 `quality_report.json`。

---

## 1. 三维正交质量模型

三个维度测量本质不同的东西，**不能平均成一个总分**：

| 维度 | 测什么 | 漏什么 | 工具 |
|------|------|------|------|
| **语义** (Semantic) | 意思丢了没、幻觉、编造内容 | 翻译腔、语法错误 | MiniLM cross-lingual similarity |
| **自然度** (Naturalness) | 翻译腔、不地道表达、逐字直译 | 流畅但翻错的句子 | Qwen2-0.5B PPL ratio |
| **结构** (Structural) | 字幕速度是否可读、是否有重叠 | 所有内容质量问题 | 规则计算 (CPS/时长/重叠) |

### 为什么不能平均

- 低语义 + 高自然度 = 流畅的错译（最危险，必须入审）
- 高语义 + 低自然度 = "直线跳跃进去吧"（直译腔，应入审）
- 低语义 + 低自然度 = 翻译失败（必须重翻/人工修复）
- 高语义 + 高自然度 = 通过

如果三个维度平均，前两种都可能得出中等分数，蒙混过关。

### Tier 分层逻辑

```python
def assign_tier(semantic, naturalness, structural):
    """确定性规则，不用 ML"""

    # CRITICAL：语义灾难性失败 或 结构错误
    if semantic.value < semantic.threshold * 0.5:
        return CRITICAL, "semantic_catastrophic"
    if structural.value < 0.3:
        return CRITICAL, "structural_error"
    if semantic.flagged and naturalness.flagged:
        return CRITICAL, "semantic_and_naturalness"

    # REVIEW：两个维度以上标记
    flagged_count = sum([semantic.flagged, naturalness.flagged, structural.flagged])
    if flagged_count >= 2:
        return REVIEW, f"{flagged_count}_flags"

    # GLANCE：一个维度标记
    if flagged_count == 1:
        return GLANCE, "one_marginal"

    # PASS：全部通过
    return PASS, "all_clear"
```

### 阈值

| 维度 | 默认阈值 | 含义 |
|------|------|------|
| semantic | 0.70 | MiniLM 余弦相似度 |
| naturalness | 3.0 | PPL(译文) / PPL(自然基线) > 3.0 则标记 |
| structural | 0.80 | 综合 CPS + 时长 + 重叠 |

---

## 2. 数据模型

```python
@dataclass
class DimensionScore:
    value: float           # 标准化 0.0-1.0 (越高越好)
    threshold: float       # 可配置阈值
    flagged: bool          # 是否低于阈值
    confidence: float      # 该分数可靠性 0.0-1.0
    label: str             # 人类可读维度名
    detail: Optional[str]  # 额外上下文

@dataclass
class QualityScores:
    index: int
    semantic: DimensionScore
    naturalness: DimensionScore
    structural: DimensionScore
    mqm: Optional[DimensionScore]  # 仅 REVIEW/CRITICAL 才触发
    tier: QualityTier
    tier_reason: str
```

---

## 3. 数据流与管线位置

QualityAssessor 作为 **step 2.5**，翻译完成后独立运行：

```
main.py (编排器)
  │
  ├── extract_subtitles.py          [step 1]
  ├── SRT_Translator.py             [step 2] → machine.srt + log files
  ├── QualityAssessor.run()         [step 2.5, NEW] ← 读 log，算多维分数
  │       ├── SemanticEvaluator     ← 读 translate-log.json
  │       ├── NaturalnessEvaluator  ← Qwen2-0.5B PPL 推理
  │       ├── StructuralEvaluator   ← 读 SRT 算 CPS/时长
  │       └── MQMEvaluator          ← 仅对 REVIEW/CRITICAL 调 LLM
  │
  ├── TTS pipeline                  [step 3] — 可与 step 2.5 并行
  └── Video merge                   [step 4]
```

**放在 `SRT_Translator` 外部而非内部的原因**：
- SRT_Translator 已有 1400+ 行，5 种翻译模式
- QualityAssessor 需要读所有输出文件，不应干扰翻译
- 可与 TTS 并行执行
- 阈值变更后可独立重新运行

---

## 4. Prompt 追踪与可视化

### 4.1 Prompt 指纹

每个翻译调用记录 `prompt_hash` 和 `prompt_step`：

```python
# 在 SRT_Translator._io_log 条目中新增字段：
{
    # ... 现有字段 ...
    "prompt_step": "batch",       # batch | retry | single | semantic_retry
    "prompt_hash": "a1b2c3d4e5f6",
}
```

### 4.2 Prompt Manifest

`02_translate/prompt_manifest.json` — 所有使用的 prompt 模板的完整快照：

```json
{
  "version": 1,
  "generated_at": "2026-05-13T10:23:00",
  "templates": {
    "batch_system": {
      "prompt_hash": "a1b2c3d4e5f6",
      "template": "你是专业日语字幕翻译...",
      "is_custom": true
    }
  },
  "config_snapshot": {
    "semantic_threshold": 0.70,
    "temperature": 0.1,
    "custom_prompt_enabled": true
  }
}
```

### 4.3 前端 Prompt 链可视化

审核详情卡片中展示翻译链路：

```
Prompt chain for #42 "那我们直接开始吧":
  ┌─ Batch attempt    (prompt_hash: a1b2c3) → "...直线跳跃进去吧"  [sem: 0.61] DISCARDED
  │   system: "你是专业日语字幕翻译..." (custom ✓)
  │   user:   "待翻译：\n<42> じゃあ早速始めよう\n\n翻译："
  │
  └─ Semantic retry   (prompt_hash: e5f6a1) → "那我们直接开始吧"  [sem: 0.89] KEPT
      system: "你是专业翻译。请将以下日语字幕翻译成简体中文..."
      user:   "前文：... \n原文：じゃあ早速始めよう\n译文："
```

---

## 5. WebUI 演进

### 5.1 SubtitleEntry 扩展 (types.ts)

```typescript
export interface SubtitleEntry {
  // ... 现有字段 ...

  quality?: {
    semantic: DimensionScore
    naturalness: DimensionScore
    structural: DimensionScore
    mqm?: DimensionScore
    tier: 'pass' | 'glance' | 'review' | 'critical'
    tierReason: string
  }

  promptChain?: PromptAttempt[]
}

export interface DimensionScore {
  value: number
  threshold: number
  flagged: boolean
  confidence: number
  label: string
  detail?: string
}

export interface PromptAttempt {
  step: 'batch' | 'retry' | 'single' | 'semantic_retry'
  promptHash: string
  systemPrompt: string
  userPrompt: string
  rawOutput: string
  kept: boolean
  timestamp: string
}
```

### 5.2 审核面板变更 (SubtitleReview.tsx)

| 变更 | 目的 |
|------|------|
| Tier 筛选切换 (pass/glance/review/critical) | 快速分流——从 CRITICAL 开始 |
| 行内质量迷你条 | 三个维度一目了然（三色小条形图） |
| 按 Tier 着色行 | PASS=浅绿, REVIEW=浅橙, CRITICAL=浅红 |
| 详情卡片：维度分解 | 四个维度的分数 + 阈值线 |
| 详情卡片：Prompt 链可折叠区 | 展示每次翻译尝试 + 对应的 prompt |
| 质量概览摘要栏 | Tier 分布统计 |
| 键盘快捷键 | `\`` 跳到下一个 REVIEW/CRITICAL |
| **默认筛选 REVIEW+CRITICAL** | 最小化审核时间 |

---

## 6. 新增文件一览

| 文件 | 位置 | 作用 |
|------|------|------|
| `quality_assessor.py` | `pipeline/` | QualityScores 数据模型、Tier 分层、报告生成 |
| `ppl_evaluator.py` | `pipeline/` | Qwen2-0.5B 加载 + 批量 PPL 推理 |
| `quality_report.json` | `02_translate/` | 多维质量的单一真相源 |
| `prompt_manifest.json` | `02_translate/` | Prompt 版本快照 |

现有文件（`translate-log.json` 等）保持不变，QualityAssessor 读它们作为输入。

### project.json 扩展

```json
{
  "files": {
    "quality_report": "02_translate/quality_report.json",
    "prompt_manifest": "02_translate/prompt_manifest.json"
  }
}
```

---

## 7. 配置

```yaml
# config/translate.yaml 新增
translate:
  quality_assessment:
    enabled: true
    auto_run: true

    dimensions:
      semantic:
        enabled: true
        threshold: 0.70

      naturalness:
        enabled: true
        threshold: 3.0           # PPL ratio (translation/baseline)
        model: Qwen/Qwen2-0.5B
        device: auto
        min_chars: 3
        baseline_mode: adaptive   # "adaptive" | "static"

      structural:
        enabled: true
        cps_limit:
          zh: 12
          default: 20

      mqm:
        enabled: true
        threshold: 0.60
        mode: selective           # "selective" (仅 REVIEW+) | "all" | "off"
```

---

## 8. 你可能未考虑到的点

### 8.1 PPL 测量的是流利度，不是准确性

PPL 低代表句子自然流畅，但不代表翻译正确。"The weather is nice" 错译成 "今天股市大涨" 时，PPL 很低（是自然中文），但内容完全错误。

**缓解**：Tier 分层已覆盖。PPL 和语义相似度是独立维度，低 PPL + 低语义 → REVIEW。PPL 不能遮盖语义维度的标记。

### 8.2 自然度基线问题

同一个"开始吧"，游戏主播 vs 新闻主播的 PPL 不同。固定基线不适用所有场景。

**缓解**：`baseline_mode: adaptive` 从同项目内语义相似度最高的 N 个条目计算 PPL 基线——这些是统计上最好的翻译，设定了项目特定的自然度基准。N<5 时回退到语言特定的静态基线。

### 8.3 Qwen2 推理延迟

129 字幕 × 50ms = 6.5s，可接受。但 2000 字幕 × 50ms = 100s。

**缓解**：批量 PPL 计算。多个文本一次前向传播，batch=32 时每个文本摊销到 ~2ms。

### 8.4 MQM 自评偏差

LLM 对自己翻的文本打分普遍虚高。

**缓解**：
- MQM 仅对 REVIEW/CRITICAL 条目运行（选择性，不逐条）
- 尽可能用不同 LLM 做 MQM（翻译用 DeepSeek，MQM 用 Qwen）
- MQM 分数标记 `confidence: 0.6` 反映自评偏差
- MQM 永远不能覆盖语义或结构维度的标记

### 8.5 术语表破坏 PPL

"附魔金苹果"对 Qwen2 是稀有 token，PPL 虚高 → 翻译腔误报。

**缓解**：PPL 计算前用占位符替换已知术语（`<TERM_1>`）。术语表已由 `GlossaryInjector` 加载，可复用。

### 8.6 质量报告过期

用户手动编辑译文后，旧质量评分与实际文本不匹配。

**缓解**：存储 `translated_text_hash`（SHA256），前端比较当前文本哈希，过期则显示警告："Quality scores may be stale — translation has been modified."

### 8.7 Temperature 效应

`temperature: 0.1` 产生确定性输出 → 所有翻译可能有相同风格的翻译腔 → PPL 分布整体偏高 → 区分度降低。

**缓解**：自适应基线（见 8.2）部分缓解。如果全项目都有翻译腔，基线 PPL 也高，但仍能找出相对最差的条目。审核者比较的是同一视频内的条目。

### 8.8 短字幕 PPL 不可靠

"坚持住！" PPL=88102 远超"挂在那里！" PPL=9659（误判）。短促口号对因果 LM 天然困惑度高。

**缓解**：`min_chars: 3`，少于 3 字符跳过 PPL。短字幕依赖语义+结构维度。

### 8.9 审核面板信息过载

140 条字幕 × 4 个维度 + Prompt 链 = 数据爆炸。

**缓解**：渐进式披露。表格行只显示 Tier 色点，hover 显示迷你维度条，点击展开完整详情。默认筛选 REVIEW+CRITICAL。

---

## 9. 实施计划

| Phase | 文件 | 说明 | 估量 |
|------|------|------|------|
| 1 | NEW: `pipeline/quality_assessor.py` | 数据模型 + Tier 逻辑 | ~200行 |
| 2 | NEW: `pipeline/ppl_evaluator.py` | Qwen2-0.5B 加载 + 批量推理 | ~300行 |
| 3 | REFACTOR: `GUI/server.py` | 将 `_run_qa_checks` 移入 assessor | ~50行 |
| 4 | NEW: quality_report 生成 | 读 log 文件，写 `quality_report.json` | ~200行 |
| 5 | MODIFY: `SRT/SRT_Translator.py` | `io_log` 加 `prompt_hash` + `prompt_step`，写 `prompt_manifest.json` | ~60行 |
| 6 | MODIFY: `main.py` | 翻译后调用 QualityAssessor，更新 project.json | ~40行 |
| 7 | MODIFY: `GUI/server.py` | `review_load` 读 `quality_report.json` | ~50行 |
| 8 | MODIFY: `GUI/types.ts` | `SubtitleEntry` 加 `quality` + `promptChain` | ~30行 |
| 9 | MODIFY: `SubtitleReview.tsx` | Tier 筛选、维度显示、Prompt 链 | ~300行 |
| 10 | MODIFY: `config/translate.yaml` | `quality_assessment` 配置节 | ~30行 |
