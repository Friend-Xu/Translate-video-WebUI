# Changelog

本分支 `feature/optimize-multi-speaker` 的语义化开发日志。
记录每次架构级改动的内容与决策理由，不记录琐碎修复。

---

## 2026-08-01 — E2E 复验修复 + xCOMET-lite 质量策略真实集成

### E2E 复验暴露 (3 处)
1. **v2 reload 后 EXTRACT 重跑丢译文**: 续跑场景 (v2 timeline 有事件) 下 asr_to_ir
   无条件重建 state, 丢已加载译文且对空 words 事件切分产生坏段 (evt_005 end=0) →
   CLI policy 检测 v2 有事件时跳过 EXTRACT, 直接走翻译链
2. **策略注册表空**: create_strategy 依赖策略模块 import 时装饰器注册, 调用方只
   import protocol 时注册表为空 → create_strategy 首次调用懒加载全部策略模块
3. **quality_check/refine 未生效**: 质量闭环此前从未真实跑通 —
   refine 无策略时跳过 (契约测试锁定 "None→响亮跳过" 语义), CLI 侧显式注入
   quality_strategy=create_strategy(gate.mode), quality_check 与 refine 共用同策略

### xCOMET-lite 真实集成 (原实现从设计上无法加载)
- **原 bug**: xcomet_strategy 用 AutoModelForSequenceClassification.from_pretrained
  ("Unbabel/xCOMET-lite") — 该仓库无 config.json (纯权重), 从未真实加载成功
- **重写**: 用专用 XCOMETLite 加载器 (models/xCOMET-lite-main 源码) + 本地基座
  models/mdeberta-v3-base + 本地权重 models/XCOMET-lite/pytorch_model.bin,
  零运行时下载、零新 pip 包 (复用现有 torch/transformers/comet 2.2.7)
- **实测**: 33 句真实评分 9.3s (GPU), Gate A=12/B=10/C=11, 好译文 0.86 / 烂译文 0.33
  合理; xcomet 路径 4 次运行 0 次 torch 崩溃 (MiniLM 路径仍偶发, 见遗留)
- **接线**: GlobalConfig translation.gate.mode (logic_gate|xcomet) → quality_check
  策略选择; translation_quality_pass.configure 保存槽位配置读 gate.mode
- **契约测试 +4**: gate.mode 驱动策略 / 默认 logic_gate / 模型缺失诚实降级 B / 注册可用
- logic_gate_strategy 同步修 typed slot 访问 (es.translation 恒为 Translation 对象,
  dict 兼容分支是死分支)

### 决策
- **无策略契约**: refine 的 None → 响亮跳过 (既有测试锁定), 重翻闭环由显式注入
  开启 — "调用方没配置就不重翻" 比隐式默认更诚实
- **本地模型优先**: 模型已手动下载则零下载集成; HF 镜像/在线下载不阻塞本地路径
- **环境观察**: torch 2.6.0 Windows 原生崩溃 (nn.Parameter 分配 access violation)
  为环境级问题, MiniLM 路径偶发 (6 次 2 成功), xcomet 路径实测稳定 — 未归因,
  留作依赖治理专项

---

## 2026-08-01 — 真实 E2E 验证: 修 7 处首跑崩溃, 新引擎全链路跑通

**验证**: `main.py Test_JP.mp4 --lang ja --skip-tts` 真实视频 + GPU + DeepSeek API。
产出: bible (domain/summary/style_guide/hotwords/说话人画像) + 逐句译文 33/33
(177s, deepseek-v4-flash) + persist v2 到 01_extract/timeline.json + machine.srt +
GUI diarization/load 读 CLI 产物 (33 事件/11 lane/译文全可读)。

### 修复 (7 处, 均首跑暴露)
1. **manifest 旧格式崩溃**: 旧工作区 project.json 无 pipeline 键, `_manifest_set_step`
   KeyError → `_manifest_ensure_v2` 显式迁移 (保留旧字段, 补 v2 生命周期键)
2. **VAD 空路径静默通过**: `Path("") == Path(".")` 恒存在, ffmpeg `-i '.'` 谜之失败 →
   显式 `not audio_path` 拒绝 (禁止兜底)
3. **load_state 遇 v1 静默空 state**: v1 提取格式无 events 键, 返回空 state 让调用方
   误判"无事件" → 显式 ValueError; orchestrator 捕获后显式 log + 跳过加载
   (v1 无译文可复用, 由注入 ASR 产物重建)
4. **跨 stage depends_on 过严**: segmentation 依赖 speaker_composite、
   preprocess 依赖 segmentation — PassManager 只校验同 stage 注册表, 完整流程
   必然崩 → depends_on 只约束同 stage, 跨 stage 顺序由 stage_order 保证
   (CLI 链 asr_to_ir 已带 speaker 字段, 无需 speaker pass)
5. **SynthesisEngine.render speaker 类型回归** (Phase 3A 引入): 槽位 dict 覆盖基础
   str 字段 → preprocess/llm_translation 的 `{r["speaker"]}` 集合 unhashable 崩溃 →
   speaker 槽位 (派生) 不覆盖 ir.speaker_ref (权威, str)
6. **CLI policy 缺质量闭环**: quick_preset TRANSLATE 只有 preprocess+translate,
   CHANGELOG 宣称的质量闭环实际没跑 → CLI policy TRANSLATE 加 quality_check +
   refine_translation
7. **asr_to_ir 未注入 words**: CLI 产物 GUI 词级编辑不可用 → 从 transcript.json
   segments 补 words + confidence

### 决策
- **完整 orchestrator 流程首次被真实跑通**: 单 pass/单 stage 测试掩盖了跨 stage
  依赖与路径注入的契约缺口, E2E 是唯一能暴露的验证层
- **depends_on 语义收窄**: 同 stage 排序用 depends_on, 跨 stage 顺序用 stage_order —
  双机制各司其职
- 契约测试 +3: load_state v1 raise / render speaker 保持 str / v1 格式显式报错

---

## 2026-08-01 — 绞杀收束: speaker/bind 唯一写路径 + 死代码清除

### 改动
- `POST /api/speaker/bind` 迁移: 不再直接 json.dump timeline.json, 改走 `load_state → 改注册表 → persist_state` (消灭最后一个绕过唯一写路径的端点)
- `SpeakerNodeIR` 补 `engine`/`voice_profile` 字段 (bind 端点 T5.2 契约字段), timeline_io persist/load 往返同步; 新增契约测试锁定
- 删死代码: `timeline/speaker/` (三层模型无消费者)、`timeline/validator/` (空壳)、`core/compat/{importer,fuse_timeline}.py` (零调用)、`timeline/fusion.py` 的 `to_project_ir/from_project_ir` 迁移层 + `tests/test_migration.py` (测试锁定错误预期)

### 决策
- 唯一写路径是硬约束: bind 端点与 5 个 speaker 编辑端点同批迁移 (Phase 4 漏网, 审计发现)
- frozen dataclass 重建而非 setattr: SpeakerNodeIR 不可变契约保持, 用 `{**node.__dict__, ...}` 重建
- 清单外发现: `timeline/io.py` 的 `load_json`/`migrate` 零消费者 (extract_subtitles 仅用 save_json), 未随本轮处理, 待下轮

---

## 2026-08-01 — CLI 翻译切默认: main.py 默认 core 新引擎

### 改动
- main.py 翻译步骤默认走 `step_translate_core` (WorkflowOrchestrator: bible + 逐句 + 质量闭环); 旧 SRT_Translator 路径保留为 `--legacy-translate` 显式回退
- `--use-core` flag 退役 (语义反转后冗余); tvw run 委托路径注释同步 (tvw 的 `--use-core` 完整 orchestrator 分支保留)
- `step_translate_core` 增强: target_lang 从 config/translate.yaml 读 (不再硬编码 zh), policy 同步
- `step_translate_core` 完成后 persist v2 到 `01_extract/timeline.json` (唯一事实源) — CLI 产物译文 GUI 编辑可读; 02_translate/timeline_v2.json (SRT 桥接) 并存
- 契约测试 2 个: CLI persist 路径约定 + GUI 加载读 CLI 输出

### 决策
- **切默认不是删旧路径**: SRT_Translator 保留显式回退入口 (--legacy-translate), 防止新引擎异常时无退路
- **checkpoint 语义**: translate_core 是新 key, 旧工作区 (translate done) 切换后重跑翻译 — 换引擎应重翻, 而非复用旧译文
- **CLI/GUI 产物统一**: 翻译后 timeline.json 必须是 v2 (含译文), 否则 GUI 加载 CLI 工作区只见 v1 提取产物

---

## 2026-08-01 — Phase 4: GUI 编辑路径收敛 + 旧 timeline/ 写路径退役

### 改动
- `patch/*` 四端点 (apply/undo/log/history) 迁移: 旧 timeline.api 直写 → `load_state → PatchEngine.apply → persist_state` 唯一写路径, patch 链 (timeline_patches.json) 以 core Patch 序列化落盘
- 新增 `GUI/patch_adapter.py`: 旧前端契约 (MERGE/SPLIT/RETAG_SPEAKER/SET_TRANSLATION/RESIZE/ANNOTATE) → core Patch 薄映射; 未迁移操作 (RELINK_WORDS, speaker 编码 rename/lock) 响亮报错
- `speaker/diarization/{rename,merge,split,reassign,resize}` 迁移: 只写 timeline.json, 删除 speaker_timeline.json/transcript.json 双写 (上游提取数据不污染) 与 `except: pass` 吞错
- 新增 `UPDATE_BOUNDS` opcode (旧 RESIZE 对等物): 改事件边界, 重建 IR + 注册表同步; patch_log schema 同步
- Patch 序列化 `to_dict/from_dict` (op 存 value 非枚举 repr — 修 str(OpCode) 输出 'OpCode.X' bug); rollback 显示同修
- 修数据丢失缺口: load_state 合并 speakers 块字段 (事件建节点后 name/voice_id/color 不再丢), persist 从 IR 读回外观字段; 修 persist 侧事件条目覆盖 speaker name
- load 端点 speakerNames 改从 timeline.json 注册表构建 (speaker_names.json 派生物退役)
- `patch_factory` 从 timeline/ui_adapter 迁入 core/runtime (纯 core 依赖)
- 退役: timeline/{patch.apply,conflict,recovery,adapters,safety,abstract,config,schema,dual_write} + api 写路径 + MigrationRouter; 保留 fusion/io/ir (CLI 提取路径) + rules/scorer/planner (AI 建议) + UIMapper
- 修复旧系统 undo 静默 no-op (bak 缺失时用工作副本当源): 现在显式 409 报错

### 决策
- **唯一写路径**: 所有 timeline.json 修改 (GUI 编辑) 必须经 PatchEngine, 重放/回滚统一走类型化写入
- **上游数据不污染**: speaker_timeline.json (pyannote) / transcript.json (ASR) 是提取产物, 说话人编辑只改 timeline.json; split 切分点参考它们时只读
- **前端零改动**: 旧契约在适配层消化, log 显示回映射旧词表 (pass_trace 兼容)
- **不假装支持**: speaker 外观编码操作 (颜色) 现状本就不持久, 适配层显式 unsupported 而非静默失效
- **遗留**: CLI 翻译双轨 (main.py SRTTranslator), AI 建议逻辑未迁 core, speaker 级 config 覆盖空转 (config/resolve Layer 2), Test_JP 旧数据 `[TR]` fallback 展示

---

## 2026-08-01 — Event 转正 Phase 3B: 关闭自由后门 + 桥接层收尾

**Commit:** `c6002c1`

### 改动
- 删 `derivatives` 别名（28 处自由写后门关闭）；`_data` 收窄为槽位容器 + meta
- `REPLACE` 收窄为槽位路由：value key 必须合法槽位，未知 key 响亮报错
- `UPDATE_EMOTION` 独立 handler 写 emotion 槽；`REFINE_ALIGNMENT` 写 asr 槽（words/confidence 精修）
- 删 `PROPAGATE` 操作码（无生产调用方，死 op）
- 血缘元数据（merged_from/split_at/split_from）迁入 `es.meta` 明确键集
- snapshot/rollback/reducer 适配类型化：rollback 重放走 PatchEngine，快照序列化 to_dict
- timeline_io 桥接层注释清理（薄映射确认）

### 决策
- 自由写不是"方便"，是类型契约失效的后门 — 未知槽位响亮报错而非静默塞 dict
- rollback 重放统一走 PatchEngine（类型化写入单一路径），不再 deep_merge 直塞
- 血缘是持久化元数据，独立 meta 槽位与运行时状态分离

---

## 2026-08-01 — Event 转正 Phase 3A: 槽位类型化 + 访问模式替换

**Commit:** `ca8d106`

### 改动
- `event_model.py` 槽位类型转正：Translation 加 ppl_ratio、TTSAudio 对齐实测（audio_ref/speed_decision/emotion_hint）、Review 对齐实测（review_status/needs_human_review）、新增 ASRData/SpeakerAssignment/EmotionData，全部带 config 子块 + to_dict/from_dict
- `event_state.py` 10 个 lazy dict 槽位 → 类型化对象（缺失创建空对象、旧 dict 形态经 from_dict 迁移）；audio 死槽删除
- 访问模式替换 ~40 文件：`es.translation["text"]` → `es.translation.text`；三态 isinstance 死分支清理；自由 key runtime 写入迁入 engine_scores；sub_scores 并入 provenance.translation_quality
- `patch_engine`：_annotate 类型化写入（已知字段 setattr）、config ops 统一 `_slot_config`/`_set_slot_config` 辅助
- `SynthesisEngine.render`：类型化槽位 to_dict 后输出（渲染保持纯 dict）
- v3 schema 对齐实测字段

### 决策
- 空槽位语义选「空类型化对象」而非 None（读端改动最小化，persist 按对象判空）
- 动态自由 key（引擎诊断/子评分）迁入已设计好的容器（engine_scores / provenance.translation_quality），不膨胀类型定义
- 三态兼容代码（dict/str/缺位）在类型化后是死分支，一律删除而非保留

---

## 2026-08-01 — 契约对齐 + 死代码清理 (Phase 2)

**Commit:** `a78efc3`

### 改动
- `field_contract.py` 按实测补全 10 槽位合法字段：新增 asr/speaker/emotion/provenance，修正 tts（audio_ref 替代 audio_path）、review（review_status 替代 status），translation 加 ppl_ratio
- `_annotate` slot_map 从硬编码 9 项改为 field_contract 生成（消灭双份清单漂移）；audio 死槽不再接受 per-event ANNOTATE
- 删 `core/ir/timeline.py`（TimelineIR 纯规划产物，生产零消费者）+ `ProjectIR.timelines` 恒空字段 + 相关测试
- 删 `patch_engine` 3 处乐观锁空壳（base_version 计算后 pass）

### 决策
- 契约以实测读写为准，不猜设计意图（audio_path 与 status 是设计稿字段，运行时从未用过）
- 有测试锁定但无消费者的规划产物（TimelineIR）一并删除 — 测试锁定的是错误预期

---

## 2026-08-01 — IR/State 止血 (Phase 1)

**Commit:** `f6cc0b6`

### 改动
- 修 `workflow_orchestrator._handle_retry` 无限重试：重试计数移入 orchestrator 实例（run/resume 重置），C 级 gate 真正重跑当前阶段、超限暂停
- 修 `_evaluate_gate` 跨域冲突：emotion 判定只写 `emotion` 槽，text_gate 读 `review` 槽；E1/E2/E3 路由此前永远匹配不到
- 删 `core/pipeline.persist_timeline` 第三实现（写 02_translate、无 bible），统一走 `timeline_io.persist_state`
- 修 IR 注册表漂移：新增 `_sync_ir_events`，6 个结构性 patch handler 统一同步 `state.ir.events`
- 修 `SemanticMergePass` 空壳：legacy `MERGE`（只写标注）→ `SEGMENT_MERGE`（结构性合并）
- 修假绿测试：gate mock 原写错槽位（provenance vs review）、空 state 不触发 gate

### 决策
- 重试计数是执行期状态，放 orchestrator 实例而非配置对象（不污染 GlobalConfig、run 重启归零）
- emotion gate 是独立域，判定与文本门控分槽存储（review 槽保留 A/B/C 语义）
- 结构性 handler 统一走 `_sync_ir_events` 重建注册表，删除 `_seg_merge` 的手工双写

---

## 2026-07-27 — 翻译引擎重构

**Commit:** `1a8feea`

### 改动
- 新建 `pipeline/translation_llm.py`（DeepSeek V4 Flash 客户端，json_object 模式，缓存命中计量）
- 新建 `pipeline/translation_bible.py`（翻译圣经 schema + 规则手册 + 证据校验门 + L0 词典合并 + 说话人画像）
- 新建 `core/passes/preprocess_translation_pass.py`（预处理生产者，每片一次产出 bible，幂等）
- 重写 `core/passes/llm_translation_pass.py`（批量标签调用 → 逐句并发，邻居窗口 + 完整性校验）
- 新建 `core/passes/refine_translation_pass.py`（低分重翻闭环，改善采纳/退化回退）
- 删除 `tvw.py`/`main.py`/`core/pipeline.py` 三处重复内联 API 客户端
- 删除 `GUI/server.py` 死函数 `_build_core_pass_factory`
- 36 行旧 `_mock_translate` 退役（无 key 时不再静默 mock，改 flag + 响亮日志）
- `core/ir/project.py` 加 `translation_bible` 字段；`timeline_io` persist/load 往返

### 决策
- **逐句替代整批**：单次调用 max_tokens 截断 + 正则半解析是静默数据丢失的根因，逐句从设计上消灭
- **预处理 bible**：用户定调"智能前置不事后弥补"，每片一次 LLM 产出术语译法/纠错/领域/风格，证据门机械校验（src 不在原文→丢弃），count 按原文重算
- **术语写译法不写"保留"**：旧 prompt 让 LLM 自判"术语不翻译"是中英混的根源
- **说话人画像自动推断**：按 speaker 聚合台词→LLM 推断 role/register/notes，逐句注入尾部保缓存前缀共享
- **质量闭环**：XComet 未加载从假满分 A → 诚实全 B+人工；B/C 句带对比提示重翻一轮

---

## 2026-07-27 — 标点感知分段 (Phase 4)

**Commit:** `51cf3bf`

### 改动
- 新建 `pipeline/segmentation.py`（共享分段引擎，移植旧 SRT 处理器算法，零 core 依赖）
- 新建 `core/passes/segmentation_pass.py`（生产者 pass，ASR/speaker 之后 translation 之前）
- 修 `core/runtime/patch_engine.py` `_seg_merge`（词级合并：并 words 排序、删被合并 event、旧译文置 needs_retranslate）
- EXTRACT 阶段 passes 加 `segmentation`

### 决策
- **旧算法被孤儿化**：grep 证实 `convert_json_to_srt` 全项目仅旧 NODE4 路径调用，core/ 零调用——41s 长段的根因
- **绞杀者复用不重写**：共享引擎同时服务新 IR 路径和未来旧 SRT 路径迁移
- **句末立即提交**：忠实于旧处理器逻辑，句末标点→立即切分与长度无关；长 run-on 到 max 才在停顿>从句>连词候选处切
- **缺词/不可靠时间戳→flag 不虚构**：禁止兜底原则

---

## 2026-07-27 — 前端类型统一 + canonical event builder (Phase 3c)

**Commit:** `38cfdd2`

### 改动
- `SubtitleEntry` 在 `types.ts` 和 `modes.ts` 双定义合并（以 types.ts 为准加 flagged + eventId）
- `server.py` 新增 `_norm_translation_text`/`_canonical_segment`/`_segment_to_inspector`，收敛两处内联构建

### 决策
- 前端"4 套 event 类型"实为 4 个合法 view-DTO，非重复；唯一真重复是 SubtitleEntry
- v3 磁盘写入推迟到事件结构定型后（Phase 4 之后），避免后端迁移后写回 v2 自相矛盾

---

## 2026-07-27 — provenance 语义归位 + 后门封闭 (Phase 3a+3b)

**Commit:** `dbfe56a`

### 改动
- provenance 槽解散：gate_decision→review.gate_decision，translation_engine→translation.engine，TTS 胜出评分修复
- patch_engine 新增 `_update_translation`/`_update_tts_audio`（消灭 translation 三态：string/dict/缺位）
- `speaker_composite` 的 `object.__setattr__`→dataclasses.replace
- emotion 删错误 derivatives 兜底
- tts 首次持久化进 timeline.json（v2 格式原无 tts 字段）

### 决策
- 绞杀者模式风险排序：3a 语义归位→3b 后门封闭+audio→3c 前端→3d 全合并（可选），替代大爆炸合并
- audio 确认本就项目级（global_patches），per-event slot 是死槽

---

## 2026-07-27 — 数据契约重设计 (Phase 1+2)

**Commit:** `f35a317`

### 改动
- 新建 `core/runtime/event_model.py`（合并 Event 模型 + EventRuntime + Project）
- 新建 `schemas/timeline_v3.schema.json`、`core/runtime/field_contract.py`
- 新建 `core/runtime/timeline_io.py`（canonical persist/load，7 往返测试）
- 毁译文 bug 修复：workflow_orchestrator reload 改调 load_state 全字段回填，删 except:pass

### 决策
- translation 统一为 dict `{text, engine, quality_score}`，禁 string/dict 双态
- words 提升为 Event 一等字段，持久化进 timeline.json
- events 平铺按时间交错，不按说话人分组；speakers 是注册表
- 字段分两层：持久化字段 + EventRuntime（内存 only, TTS 状态机不持久化）
- persist 仍写 v2.0（前端十几个裸读取端只认 2.0），v3 原生格式+前端迁移留后

---

## 2026-07-27 前 — 基础修复与收敛

**Commits:** `3589ef3`..`494a623` (11 commits)

### 改动
- 入口收敛：删除 `main_core.py`，`tvw.py` 成为唯一 CLI 入口
- 三条不可协商开发原则写入 CLAUDE.md
- 说话人操作收敛到单端点+patch 路径
- 评分器从虚假满分改为诚实无数据
- GUI mock 外壳替换为真实数据接线
- tvw CLI 翻译配置、manifest 生命周期、pass-factory 空壳修复

### 决策
- **三个原则不是风格建议是硬约束**：此后所有代码决策以之为最高准则
- **禁止兜底**尤其针对静默默认值、except:pass、无数据满分——这些让原则性 bug 变成"成功的错误输出"
