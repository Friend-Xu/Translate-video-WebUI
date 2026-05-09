# Quality Gates — MQM 质量门禁

## MQM 评分维度

| 维度 | 英文名 | 评分范围 | 权重 |
|---|---|---|---|
| 准确性 | Accuracy | 1-5 | 35% |
| 流畅度 | Fluency | 1-5 | 25% |
| 术语一致性 | Terminology | 1-5 | 20% |
| 风格匹配 | Style | 1-5 | 10% |
| 本地化规范 | Locale Convention | 1-5 | 10% |

## 评分标准

### Accuracy（准确性）
- 5: 无增译、漏译、错译，语义完全等价
- 4: 偶有 1-2 处轻微偏差，不影响理解
- 3: 多处小偏差或 1 处关键误译
- 2: 多处关键误译，严重影响理解
- 1: 翻译与原文基本无关

### Fluency（流畅度）
- 5: 自然流畅，符合目标语言表达习惯
- 4: 基本流畅，偶有生硬表达
- 3: 多处不自然表达，但可理解
- 2: 大量机器翻译痕迹，阅读困难
- 1: 不可读

### Terminology（术语一致性）
- 5: 全文术语一致，专有名词翻译正确
- 4: 1-2 处术语不一致或专名翻译有偏差
- 3: 多处术语不一致
- 2: 术语严重混乱
- 1: 无术语管理

### Style（风格匹配）
- 5: 语域/正式度与原片完全匹配
- 4: 偶有语域偏差
- 3: 风格不完全匹配，但可接受
- 2: 风格明显不匹配（如正式演讲译成口语）
- 1: 风格错误

### Locale Convention（本地化规范）
- 5: 数字/日期/单位/敬语完全符合目标 locale
- 4: 1-2 处 locale convention 偏差
- 3: 多处 convention 不一致
- 2: 大量 convention 错误
- 1: 未做本地化处理

## 综合评分

```
composite = Accuracy x 0.35 + Fluency x 0.25 + Terminology x 0.20 + Style x 0.10 + Locale Convention x 0.10
```

## 门禁通过标准

| 结果 | 条件 | 动作 |
|---|---|---|
| **PASS** | composite >= 4.0 且所有维度 >= 3 | 进入下一阶段 |
| **WARN** | composite >= 3.5 且所有维度 >= 2 | 记录 warning，Polisher 重点修复低分维度 |
| **FAIL** | composite < 3.5 或任一维度 = 1 | 回退给 Translator 重译，最多 2 次 |

## 各 Agent 专属门禁

### Translator
- [ ] 产出 `machine.srt` 存在且非空
- [ ] SRT 索引连续（1, 2, 3, ...）
- [ ] 时间轴无负值或倒退
- [ ] 译文行数与原文行数匹配（误差 < 5%）
- [ ] 无原文残留（如日文假名出现在中文译文中）

### Glossary
- [ ] 术语表 `glossary.json` 格式有效
- [ ] 每条术语含 `source` / `target` / `context` 字段
- [ ] 无循环引用或自指

### Structural Mapper
- [ ] `alignment.json` 覆盖所有源句子
- [ ] 对齐映射无交叉（A→B 和 A→C 同时存在）
- [ ] 结构保留报告指出所有失配点

### Reviewer
- [ ] 报告覆盖全部 5 个 MQM 维度
- [ ] 每个 fail 项有具体句子编号和改写建议
- [ ] 综合评分计算正确

### Polisher
- [ ] 修复所有 Reviewer FAIL 项
- [ ] 修复后 composite >= 4.0
- [ ] SRT 格式校验通过（索引/时间轴/空行）
- [ ] 润色变更记录完整（每处变更含 before/after）

## 重审次数上限

- 同一产出物最多重审 2 次
- 2 次后仍未达到 PASS → Conductor 介入，人工判断是否降级接受（WARN）或放弃本段
