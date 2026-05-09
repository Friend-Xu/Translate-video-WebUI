# Workflow: Mode Simple — 单次翻译流水线

**适用**: Phase 1 / Phase 2（兼容当前态）
**模式**: `mode: "simple"`
**Agent 数量**: 2-3（Translator + Reviewer + 可选 Polisher）

## 数据流

```
source.srt → Translator Agent → machine.srt → Reviewer Agent → review-report.json
                                                                    │
                                                    ┌─ PASS ───────┤
                                                    ▼               ▼
                                               Polisher Agent   修复循环
                                                    │          (max 2 retry)
                                                    ▼
                                               machine.srt (final)
```

## 步骤

### Step 1: Conductor 准备
1. 读 `pipeline-state.json`，确认 `phase = "phase1"`，`mode = "simple"`
2. 验证 `source.srt` 存在（`{workdir}/01_extract/source.srt`）
3. 验证工作目录结构完整

### Step 2: Translator Agent
```
输入:
  - {workdir}/01_extract/source.srt

输出:
  - {workdir}/02_translate/machine.srt
  - {workdir}/02_translate/translate-log.json

启动方式: foreground
最大轮次: 1（初译），最多 2 次修复
```

### Step 3: Reviewer Agent（MQM 审查）
```
输入:
  - {workdir}/01_extract/source.srt
  - {workdir}/02_translate/machine.srt

输出:
  - {workdir}/02_translate/review-report.json

启动方式: foreground
最大轮次: 1

判定逻辑:
  - PASS (composite >= 4.0) → Step 4
  - WARN (composite >= 3.5) → Step 4（Polisher 重点修复低分维度）
  - FAIL (composite < 3.5) → 回 Step 2（修复循环）
```

### Step 4: Polisher Agent（仅在 PASS 或 WARN 后）
```
输入:
  - {workdir}/02_translate/machine.srt
  - {workdir}/02_translate/review-report.json（仅 fail/warn 项）
  - {workdir}/01_extract/source.srt

输出:
  - {workdir}/02_translate/machine.srt（覆盖）
  - {workdir}/02_translate/polish-log.json

启动方式: foreground
最大轮次: 1
```

### Step 5: Conductor 收尾
1. 读 `review-report.json` 确认最终 MQM 评分
2. 更新 `pipeline-state.json`：
   - `completedSteps` 追加 translator / reviewer / polisher
   - `phase` → `integration`
3. 触发 integration（写回 SRT）

## 修复循环细则

```
FAIL → Conductor 提取 fail 项 + MQM 分维度评分 → Translator Agent 重译
  → Reviewer 重审 → 仍 FAIL？→ 再重试 1 次
  → 2 次后仍 FAIL → Conductor 记录到 failedSteps → 人工介入
```

## 格式校验清单
- [ ] SRT 索引连续（1, 2, 3, ...）
- [ ] 时间轴格式 `00:00:00,000 --> 00:00:00,000`
- [ ] 时间轴无倒退（t_end > t_start）
- [ ] 字幕序号无跳号
- [ ] 无空字幕条目
- [ ] 译文行数与原文行数匹配（误差 < 5%）
