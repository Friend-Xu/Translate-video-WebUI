# Changelog

本分支 `feature/optimize-multi-speaker` 的语义化开发日志。
记录每次架构级改动的内容与决策理由，不记录琐碎修复。

---

## 2026-08-01 — P5-A/B: 翻译引擎卡片对齐 core 质量体系 + 日志按钮修复

### 背景 (用户指出: 卡片与翻译引擎脱节 + 日志按钮形同虚设)
- 翻译卡片 13 处脱节: joint_formula 选项 core 无此策略 (触发即崩); xcomet 无前端入口;
  verification_mode 只进 pass_factory 死参数 (质量策略实际由 quality_strategy 键决定);
  semantic_threshold 映射错位 (写 threshold_accept, 策略读 semantic_threshold);
  gate_beta/gamma/quality_gate/enable_glossary 无消费端; 术语表控制面 (glossary_files)
  与真实链路 (yaml terms_dict) 脱节; api_type/max_tokens/top_p/concurrency 无消费端
- 日志按钮 action 是 toggleDockCollapsed (切换 dock 折叠) 而非打开日志; 无 job 时面板空白

### P5-A: 翻译引擎卡片对齐 (单一事实源)
- **策略选项动态化**: GET /api/config 返回 quality_strategies (core list_strategies);
  前端 Select 动态渲染 (logic_gate + xcomet), 删除 joint_formula
- **双键统一**: verification_mode 改映射 translation.quality_strategy (tvw.py 真实消费键),
  删除死的 --verification-mode CLI 特判
- **键错位修复**: semantic_threshold → gate.semantic_threshold (策略真读的键)
- **参数打通**: SentenceTranslator 加 max_tokens/top_p (请求体 + LLM_MAX_TOKENS/LLM_TOP_P env);
  _concurrency_from_config 优先 LLM_CONCURRENCY env
- **术语表打通**: load_manual_glossary 读 GLOSSARY_FILES/GLOSSARY_ENABLED env 覆盖 yaml —
  GlossaryManager 选词典真正生效; enable_glossary 开关不再死链
- **诚实化**: 删除 gate_beta/gate_gamma 滑块 + joint_verification 开关 + quality_gate 开关
  (core 无消费端); custom_prompt 键名统一 snake_case (camelCase 曾致"已启用"文案永不显示)
- **懒加载 bug 修复**: 策略注册表幂等 import (只查空表时部分加载不补全, xcomet 缺失)

### P5-B: 日志按钮
- NavRail 日志 → mode='logs' 全屏日志视图 (LogsView: 自动刷新/错误高亮)
- GET /api/logs/recent: 优先 workspace/pipeline.log, 否则 GUI/logs/ server 日志尾部 —
  无 job 时也有内容

### 验证
- pytest 1077 + 10 xfailed (新增 10 契约: 映射/策略注册表/LLM 参数/术语 env/日志端点)
- vitest 55/55, tsc 0; 冒烟 logs_smoke (策略菜单 = 三门逻辑+XCOMET, 日志页有内容)

### 遗留
- custom_prompt 模板真正接入 render_system_prompt (本期只统一键名+透传)
- api_type (openai/anthropic) 协议未实现 — 前端选项保留但注明兼容 OpenAI 格式

---

## 2026-08-01 — P4-F: 前端设置体系接入 core 配置架构 — 消除"保存成功但无效"

### 背景调研结论
- 前端 SettingsView 70+ 参数 → settings.json (GUI/settings.json), 但 pipeline 子进程从不读它 — **只有 2 个键生效** (tts_engine/target_lang), 违反"禁止兜底"原则的静默假成功
- 新架构 (core/) 已有完整配置体系: 四层域 (ProjectPolicy/WorkflowPolicy/EnginePolicy/Runtime) + ConfigResolver 三级解析 (Global > Speaker > Event) + deep_merge null 语义 + 差异序列化 — 前端设置游离在体系外

### P1: settings.json 差异层 (数据丢失修复)
- **根因**: POST /api/config 全量替换 `settings["pipeline"]` — GlossaryManager 单键 POST 清掉用户全部其它设置; useConfig GET 未解包 `{config}` 嵌套
- **改动**: POST 改 deep_merge 增量语义 (null=删除键=恢复默认, 与 core ConfigResolver 一致); GET 返回 `{config: 默认+差异合并, defaults, overridden}`; useConfig 解包修复 + 差异提交; SettingsView 只发 dirty 键 (改回默认自动发 null)
- **验证**: pytest 7 契约 + vitest 3 + 冒烟 (填 4 → overridden 含键; 填 0 → null 恢复)

### P2: 全局设置桥 (settings → GlobalConfig → pipeline)
- **改动**: tvw.py 新增 `--config-overrides <json>` → `GlobalConfig.apply_slot_overrides()` (槽位级 deep_merge, 新架构正门); server 桥 36 键映射 (snake_case → 槽位点路径, source_lang=auto/max_speakers=0 跳过); caption_* 全套 + verification_mode 走 CLI (pass_factory 消费端已存在); LLM 参数 (api_key/model/temperature/base_url) 环境变量注入 (DEEPSEEK_API_KEY 优先, 凭据不落日志)
- **验证**: pytest 10 契约; `tvw run --help` 参数注册; API 冒烟 POST/GET/null 全通

### P3: ConfigResolver 生产接线 (断点修复)
- **根因**: ConfigResolver 三级解析只有测试调用; pass_manager 喂全槽位 dict 但 audio/speaker/tts 三个 pass 按平铺读取 → **配置注入静默失效** (skip_demucs/clustering_threshold/chattts_* 从未生效)
- **改动**: 契约统一 = `configure({slot: {...}})`; 修 3 个 pass 读取; pass 注入 `_resolver`, TTS pass 逐事件 `resolve_event_config` (事件级覆盖生效)
- **验证**: pytest 6 契约; 全量 1067 passed + 10 xfailed 无回归

### P4: 界面联动
- **改动**: ExportView 删除 3 个假选项 (format/resolution/preserveAudio — core 无消费端, 诚实化); font_size_mode 与 caption_font_size 单源 (不再独立存键); 设置页新增"恢复默认"按钮 (POST null 清差异层)
- **验证**: tsc 0 错误; 冒烟全通

### 遗留 (记录不掩盖)
- 现有 settings.json 是全量旧快照 (差异层下显示"全部被覆盖", 无害; 可写一次性 normalize 收敛)
- 导出参数 (output_format/codec/bitrate) core 无配置面 — VideoExportPass 走 VideoSegmenter 硬编码, 属后续工作
- useConfig camelCase 键残留 settings.json (无消费者, 无害)

---

## 2026-08-01 — P3-E3: 说话人轨道固定 — 编辑操作只动色块不重排轨道

### 根因
- 说话人界面 `sortedSpeakers` 默认按 total_duration 排序轨道 (sortBy='duration')
- 拖拽 resize 段改变时长 → lane 总时长变 → 轨道重排 → SPEAKER_05 等标签换位置 — 用户: "符合人类操作的逻辑是轨道固定, speaker色块进行移动"

### 改动
- **默认排序改为 'fixed' (轨道固定)**: `sortedSpeakers` 按 store 顺序 (fetchSpeakerLanes 后端顺序 / sync 保留顺序) 渲染, 编辑操作不再触发轨道重排
- 排序 Select 保留但加 "轨道固定" 选项置顶 (主动排序仍可用 — 那是用户显式选择)
- lane 行加 `data-lane-id` 测试锚点; 冒烟 STEP6b 断言: 拖拽前后轨道顺序逐位一致

### 验证
- 冒烟: 拖拽 +60px 后 `[SPEAKER_03, UNKNOWN, SPEAKER_04, ...]` 顺序不变, 段宽 440.8 → 500.8
- tsc 0, vitest 52/52

---

## 2026-08-01 — P3-F: 前端可视化编辑操作量化 — ui_ops 审计日志 (调试可追溯)

### 形态 (用户确认: localStorage + action 级 + 无面板)
- 三层量化: **ui_ops (操作意图+耗时) → server.log (请求级) → patch 链 (结果级)** — 前两层此前缺失, 现在补全

### 改动
- 新 action `_logOp` (useAppStore.ts): 内存环形 300 条 + localStorage 'ui_ops' 持久化, **零请求** (不破坏 P3-D 的 2 请求模式)
- 条目: `{ts, ms(耗时), op, ok, opcode, eventId, extra, error}` — 覆盖失败路径 (error 记录后端 detail)
- 埋点 5 个 action: applyDraft (6 出口含失败/本地状态), applyAllDrafts (成功/失败数), undoLastPatch, discardAllDrafts (丢弃数), loadWorkspace (事件数/部分失败原因)
- 调试读取: `localStorage.getItem('ui_ops')` (Playwright evaluate 或 devtools) — 用户报 bug 时直接看操作序列+耗时+成败

### 决策
- **localStorage 而非后端落盘**: 每次操作 +1 请求违背性能方向; localStorage 对 Playwright/开发者工具都可达
- **action 级而非手势级**: 语义清晰噪音小; 手势轨迹 (mousemove 帧) 调试价值低
- 失败路径同样埋点 (error 原文) — 用户报"操作没生效"时能区分: 后端拒绝 vs 前端没发请求

### 验证
- vitest 52/52 (+6: apply/undo/discard/loadWorkspace 记录 + localStorage 持久化 + 环形上限), tsc 0
- 冒烟 STEP7: 真实拖拽后 `ui_ops` 含 `applyDraft RESIZE_SEGMENT ok=true ms=176 31 events` — 量化数据可直接读取

---

## 2026-08-01 — P3-E2: 说话人界面拖拽"只有 patch 不渲染" — P3-D 副作用的修复

### 根因
- P3-D 局部刷新把 apply 路径从"全量 loadWorkspace (含 fetchSpeakerLanes)"精简为"events 快照 + review flags" — 但 **speakerLanes 不是静态数据**: 拖拽/resize/assign 改变事件边界与归属, 说话人界面以 speakerLanes 渲染 → 拖拽后 patch 落库 (后端正确) 而 UI 纹丝不动
- 同文件对照: SpeakerReviewView 的 merge/rename 操作 apply 后**手动 fetchSpeakerLanes** (全量刷新, 3 请求), 而段 resize 拖拽 (onUp) 没有 → 症状只在拖拽路径出现
- 冒烟实测复现: patch 链 +1 落库, 段块宽度 981.8 → 981.8 不变

### 改动
- **新 action `syncSpeakerLanesFromEvents`** (useAppStore.ts): apply 响应 events 快照 (编辑后全量事件) 本地重建 lanes — 保留原 lane 顺序与元数据 (display_name/color/voice_id), segments 以快照为准重建: 事件边界更新 / speaker 归属变化的段移入目标 lane / 快照缺失的段 (merge 删除) 移除 / 统计重算。**零请求**, 保持 P3-D 的 2 请求模式
- applyDraft / applyAllDrafts 成功路径接入; undoLastPatch 保持原有 fetchSpeakerLanes 全量刷新 (它还要回退 lane 元数据 — 快照不含 lane 级数据)
- SpeakerReviewView 段块加 `data-segment-id` / 右 handle 加 `data-resize-right` (测试定位锚点, 不改行为)
- 契约测试 +4 (边界更新/归属迁移/merge 删除/applyDraft 集成且无 diarization 请求); vitest 46/46, tsc 0
- 新冒烟 `test_trail/drag_lane_smoke.cjs`: 说话人界面拖拽段右边缘 → 断言 patch 落库 + 段块宽度 +60px (UI 即时渲染)

### 决策
- **lanes 是编辑派生数据不是静态数据**: P3-D 的"静态数据不随编辑重刷"清单 (manifest/waveform/AI 建议) 正确, 但 speakerLanes 应归入"随编辑变化"类 — 事件边界/归属就是它的全部内容
- **本地重建优于再请求**: 响应快照已含全量事件, 零请求重建 lanes (与 events 同一数据源), 不引入第三个数据源

### 验证
- Playwright 拖拽冒烟: 段宽 320.8 → 380.8 (+60px 与拖拽量吻合), patch 链 8→9, 后端快照 end 同步更新
- 第一次冒烟失败是脚本断言了错误的段 (UI first 段 ≠ 拖拽目标), 按 data-segment-id 定位后 PASS — 非产品 bug

---

## 2026-08-01 — launcher 进程健康化: 关终端窗口不再留孤儿进程

### 根因
- launcher.py 的 Ctrl+C 路径有 cleanup (正常), 但**直接关终端窗口** (git-bash mintty 场景) 时 launcher 被杀, `subprocess.Popen` 的 uvicorn/npm→vite 子进程树成为孤儿继续挂载 — 用户反复观察到"终端关了服务还在"

### 改动
- launcher.py 挂 **Windows Job Object (JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)**: launcher 入 job, 子进程自动继承 (Win8+), launcher 无论以何种方式死亡 (Ctrl+C/关窗/被杀), OS 杀整棵子进程树
- ctypes 实现零新依赖; **显式声明 argtypes/restype 是坑** — 缺失时句柄按 32 位截断, AssignProcessToJobObject 报 ERROR_INVALID_HANDLE (实测踩到, job 形同虚设)
- 非 Windows / launcher 已在别的 job 中 (Assign 失败) 时静默降级 — 清理是辅助能力, 失败只影响"关窗不留孤儿", 不影响启动

### 验证
- 强杀 launcher → netstat 确认 8000/5199 整树瞬间释放 (修复前: uvicorn/vite 孤儿存活)

---

## 2026-08-01 — P3-E: 编辑秒级延迟根因修复 — manual 词条不再撑大 timeline.json (30MB → 31KB)

### 根因 (profile 实测)
- 每次编辑 apply 的 HTTP 往返 **1418ms** — 不是拖拽渲染, 是后端 `_persist_edited` 占 1158ms + `load_state` 259ms
- timeline.json 只有 32 事件却 **30.5MB**: `translation_bible.hotwords` 独占 17MB (207,319 条, 全为 origin="manual")
- 链路: `PreprocessTranslationPass` 把 config/terms 全量词典 (minecraft_mod.json 10.6MB / 20 万条, 用户有意维护的资产) 经 `merge_manual_glossary` 全量合并进 bible → 随 `state.ir.translation_bible` 落盘 → 每次编辑 load ×2 + persist ×1 各 30MB IO

### 改动
- **manual 词条不落盘** (`preprocess_translation_pass.py`): 删除 merge_manual_glossary/load_manual_glossary 调用与 manual_terms 参数 — bible 只持久化 LLM 自动词条; 渲染实际只用 hotwords 前 50 条 (MAX_HOTWORDS), 20 万条中 99.98% 从未被消费
- **消费点实时合并** (`translation_bible.py` 新增 `with_manual_glossary`): LLMTranslationPass/RefineTranslationPass 的 `_bible_from_state` 渲染前从 config 合并 manual (人工永远赢语义不变); 词典是配置级输入, 改动即时生效无需重跑预处理
- **一次性迁移** (`tools/normalize_bible_manual.py`): 剥掉旧 timeline.json 的 manual 词条; **必须同时迁移 timeline.json.bak** — undo 从 bak 重放链后全量 persist, 只迁主文件会让下一次 undo 把旧 bible 写回 (30MB 复发)
- 契约测试: preprocess 产物不含 manual 词条 / 消费点合并人工赢置前 / 空词典原样返回

### 决策
- **词典是配置级输入不是项目数据**: 20 万条术语是用户资产 (config/terms/), 不该复制进每个项目的 timeline.json; 事实源归位后项目文件与词典解耦
- **渲染时合并而非运行时兜底**: 与"禁止兜底"不冲突 — 合并是翻译渲染的固定语义 (L0 人工永远赢), 不是失败降级

### 验证
- profile 实测: HTTP apply 1418ms → **36ms** (39×), undo 1467ms → **35ms** (42×); load_state 259ms → 0.9ms, persist 1158ms → 13ms
- pytest 1044 passed + 10 xfailed (新增 3 契约测试), Playwright p3a_smoke 全链路 PASS

---

## 2026-08-01 — P3-D: 局部刷新 — 编辑不再全量 loadWorkspace (借鉴时间轴编辑器本地状态模式)

### 改动
- **apply/undo 响应携带事件快照** (server.py): `_inspector_from_state(state)` 从内存 state 构建 inspector (零 IO, 不重读盘/不重算波形/AI); `_apply_edit_patch` 与 undo 端点返回 `events`; timeline_patch_apply 响应 `{status, patch_id, diff, events}`
- **前端局部刷新** (useAppStore.ts): applyDraft 成功用响应 events 快照本地更新 + appliedPatches 本地 append + **只刷 review flags** (唯一随编辑变化的派生数据); applyAllDrafts 收集最后响应快照一次更新; undoLastPatch 用响应快照 — **不再调 loadWorkspace (5 请求) + fetchSpeakerLanes (1-2 请求), 每次编辑从 ~7 请求降到 2 请求** (1 apply + 1 flags)
- **新增 fetchReviewFlags action** (从 loadWorkspace Step5 提取, P3-B 响亮语义)
- 契约测试 +2 (apply 后 events 来自响应且无 /timeline/load 请求 / undo 快照)

### 决策
- **借鉴类似项目 (Kimu Video Editor/Aegisub/mcut)**: 时间轴/字幕编辑器都是本地状态主导 — 编辑改内存, 保存才碰服务器; 我们的 patch 链架构 (apply 即持久化) 不能完全照搬按需保存, 但采纳 mcut 的形态 — **dispatch 返回应用结果, UI 订阅本地状态不回源**
- **静态数据不随编辑重刷**: manifest/waveform/AI 建议不随编辑变化 — 只在加载时取一次 (waveform 每请求重读 wav 是最大浪费源)
- **review flags 是例外**: 规则检查依赖编辑后文本, 单独轻量刷新 (1 请求)
- 后端 events 快照是 apply 响应契约的一部分 (非可选) — 前端无 fallback 到 loadWorkspace

### 验证
- apply 响应实测: 32 事件快照 + evt_001 译文更新 ✓
- vitest 42/42, tsc 0, Playwright p3a_smoke 全链路 PASS

---

## 2026-08-01 — P3-C: _annotate 响亮化 + 主数据源挂靠 timeline 端点

### 改动
- **_annotate 两阶段校验** (`core/runtime/patch_engine.py`): 先全量校验再写入 — 未知槽位 (此前静默跳过) / 类型化槽位未知字段 (此前 `if hasattr` 静默跳过) / 非 dict 值 → 响亮 error; 先校验杜绝部分写入残留内存 state + 假 applied
- **删 adapter 死字段写入**: minilm 的 `translation.flagged` / ppl 的 `translation.ppl`+`naturalness_flagged` 是无字段静默丢失 (flagged 无任何读取端), 只落 provenance (dict 自由 key, 本就有对等值)
- **新端点 `POST /api/timeline/load`**: 从 timeline.json 构建事件视图 (唯一事实源); timeline.json 缺失/空 → 响亮 400 "需先运行 CLI 提取/翻译" (不降级 transcript — 那是 diarization 的兼容路径)
- **提取 `_build_timeline_views` helper**: speaker_load 与 timeline/load 共享 lanes/inspector_data/pass_trace/speakerNames/AI patches/patch_log 构建; diarization/load 主路径改用 helper (保留 transcript fallback); **顺带修复原顺序 bug**: AI patches 在 inspector 构建之后计算 → hasAiSuggestion 从未标记, helper 里修正
- **前端 loadWorkspace Step2 / reloadEvents 迁移**: `/api/speaker/diarization/load` → `/api/timeline/load`; fetchSpeakerLanes 保留 diarization/load (lane 视图语义匹配)
- 测试: _annotate 未知槽位/字段响亮 + 迁移契约 (vitest 40/40, pytest 1041 passed + 10 xfailed)

### 决策
- **timeline 读路径不假装**: 旧工作区只有 transcript 无 timeline.json → timeline/load 显式 400, 前端报错提示跑 CLI — 诚实失败优于 transcript 兼容 (兼容留在 diarization/load)
- **先校验后写入是响亮化的前提**: _annotate 中途 error 会残留已写字段 (内存 state 污染, 无 add_patch 但 slot 已改) — 两阶段消灭
- **死字段写入即静默假数据**: minilm/ppl 写类型化槽位不存在的字段, 数据从未落盘也未读取 — 删掉并归位 provenance

### 验证
- uvicorn: timeline/load 32 事件 ✓ / diarization/load 11 lanes 回归一致 ✓ / 无效工作区 400 ✓
- vitest 40/40, tsc 0, Playwright p3a_smoke 全链路 PASS (loadWorkspace 迁移后)

---

## 2026-08-01 — P3-B: 残留静默失败响亮化 (useAppStore 全量审计)

### 改动
- **fetchPatchLog**: `if (!res.ok) return` + `catch {}` 静默 → 响亮 (补丁历史显示为空会误导"无编辑记录")
- **loadWorkspace Step3-5** (waveform/patch log/review flags): 三个 `catch { /* non-fatal */ }` → 收集 loadErrors, 成功态之后统一 set error "部分数据加载失败: 波形/补丁历史/校验标记" (先 set 成功再设错误, 避免被 error:null 吞掉 — applyAllDrafts 同款模式)
- **reloadEvents**: `catch { /* non-fatal */ }` → 响亮 — 编辑后刷新失败静默 = 用户看到旧数据误以为编辑已生效 (P1 同款最危险形态)
- **undoLastPatch 刷新**: 删 `fetchPatchLog().catch(() => {})` / `fetchSpeakerLanes(ws).catch(() => {})` 静默吞 — 两个 action 内部已响亮, 不再防御性吞 rejection
- **loadReviewEntries**: 删 events→entries 本地合成兜底 (静默假数据 — 后端含 SRT 关联/审核状态, 本地合成语义不同) → 响亮报错
- **fetchWorkflowPresets/fetchWorkspaceList**: `catch { /* non-critical */ }` → 响亮 (列表显示为空误导用户)
- 保留的合理静默: localStorage quota (导出预设本地缓存, 非核心数据)
- 契约测试 +6 (fetchPatchLog 网络失败 / loadWorkspace 波形 500 + 补丁历史 404 / reloadEvents 500 / loadReviewEntries 404 不合成 / fetchWorkspaceList 失败)

### 决策
- **刷新失败 = 数据可见性问题**: 静默刷新失败让用户基于旧数据决策 (编辑白做/历史缺失), 与 P1 编辑失败同权
- **先成功态后错误态**: 部分数据失败不 block 工作区加载, 但必须在成功 set 之后设 error, 否则被 error:null 吞掉 (applyAllDrafts 已验证的模式)
- **本地合成不是兜底是假数据**: events→entries 合成丢失审核状态/关联, 是静默数据降级 — 一律删

### 验证
- vitest 39/39 (+6), tsc 0, Playwright p3a_smoke 回归 PASS (成功路径无误报)

---

## 2026-08-01 — P3-A: timeline 编辑假 draft 补映射 (RETRIGGER/SPLIT/MERGE/MOVE/TRIM/AI 建议)

### 改动
- **adapter 补 8 个 opcode 映射** (`GUI/patch_adapter.py`): MOVE_EVENT/TRIM_START/TRIM_END→UPDATE_BOUNDS (部分边界更新), SPLIT_EVENT→SEGMENT_SPLIT, MERGE_PREV/MERGE_NEXT→SEGMENT_MERGE (targets=[id, mergeTarget]), APPLY_AI_SUGGESTION→UPDATE_TRANSLATION, RETRIGGER→ANNOTATE review 槽 `{flags:[needs_retranslate], needs_human_review:true}` (core 无 LLM 重翻通道, 标记是唯一诚实落点, 与 _seg_merge 先例一致)
- **前端 OPCODE_MAP 补 8 键** + `patchDraftToApiFormat` 删 `|| 'ANNOTATE'` 静默降级 → 未知 opcode 显式抛错 (关闭假成功后门)
- **修 3 个前端真 bug**: APPLY_AI_SUGGESTION 写 `event.translation` 旧值 (应用 AI 建议却写原译文 = no-op 假数据) → 改取 AI_SUGGEST draft 的 suggestion; PatchManagementView 点"应用"AI 建议只 addDraft 不提交 → 补 applyDraft; MERGED_PATCH 是坏设计 (draft payload 无真实写入内容) → handleMerge 改批量应用选中 draft/AI 建议
- **AI_SUGGEST/DISMISS_AI_SUGGESTION 明确为本地状态**: 不进 patch 链 (applyDraft/applyAllDrafts 跳过), DISMISS 改 addDraft 后立即 removeDraft
- **修 review 槽持久化缺口** (`timeline_io.py` + `event_model.py`): v2 dict 此前只写扁平 `review_status`, flags/needs_human_review 只写内存槽位 persist 丢失 → `_event_to_v2_dict` 补 review 块完整落盘, `apply_event_to_state` 补 flags 回填, `Event.from_dict` 兼容旧 v2 扁平 review_status 归一进 Review — 这是 persist/reload 互逆缺口, SEGMENT_MERGE 的 needs_retranslate 标记同样受益
- 契约测试 +9 (8 个 opcode 映射 case 表 + merge_prev 缺目标拒绝 + 部分边界更新×2 + split/merge/retrigger/ai 应用端到端 + review 落盘往返)

### 决策
- **core 无重翻通道, 不假装支持**: RETRIGGER 不映射 UPDATE_TRANSLATION (会写空译文), 标记 needs_retranslate 进人工审核闭环
- **本地状态不进 patch 链**: AI_SUGGEST 是预览暂存, DISMISS 是本地丢弃 — 它们不是写操作, 硬映射会污染事件历史
- **映射后发现的下沉 bug**: RETRIGGER 冒烟暴露 review.flags 不落盘 (v2 只写 review_status) — 先补 persist 缺口再谈功能, 否则"已保存"是假的

### 冒烟实测 (Playwright, smoke_ws 副本)
- 右键"局部重算" → 全部应用 → patch 链 +1 + timeline.json review.flags 含 needs_retranslate ✓
- 右键"与上一事件合并" → 全部应用 → patch 链 +1 + 事件 33→32 ✓
- 全量 1040 passed + 10 xfailed, vitest 33/33, tsc 0

---

## 2026-08-01 — P2-C2: 死端点 + 死依赖全面清理 (server.py -1530 行)

### 改动
- **删 37 个零引用端点**: 旧 `/api/pipeline/*` 全套 (7) / batch/list+active / config/slots / env / files/stream / glossary/list / jobs / models×3 / project/manifest (保留 resolve) / runtime/status / settings×3 / subtitle/presets+qa-check / patch/history+generate / tts/cache-key+indextts-preset-audio / workspace/detail / emotion/to-prosody / export/incremental / media×2 / core/pipeline 的 events×2+gate+audit
- **删 11 个死 model** (RunResponse/StatusResponse/SettingsPayload/ResetPayload/Preflight×2/Mux×2/ConfigResolveResponse/EmotionToProsodyRequest/CoreEventResponse) + **10 个死 helper** (旧 pipeline 的 _run_job_sync/_build_cli_args/_read_log_tail/_read_log_range、settings 的 apply_subtitle_settings/reset_language/_sync_translate_config、_rel_path/_seconds_to_srt/_load_core_transcript)
- **AST 审计方法论**: 顶层符号 (def/class/import) 做内部调用 + 外部引用 (GUI 非 server/core/tests/入口) 双零判定; **修正审计 bug** — `def` 语句不产生 ast.Name, 定义处减一逻辑会把"恰调用 1 次"误判为死 (首版误报 63 个, 修正后真死 10 个)
- **事故记录**: helper 删除脚本块边界未包含顶层赋值语句, `_rel_path` 块吞掉 `app = FastAPI()` + CORS 中间件 + startup 钩子 + 7 个常量 + `_SKIP_LOG_PREFIXES` → HEAD/当前顶层语句对比脚本检出 5 项误删并恢复; 此后删除脚本一律加"活端点/关键符号存在断言"
- 全量 1031 passed + 10 xfailed, uvicorn 启动 + 三端点响应验证

### 决策
- **端点验证必须先于测试**: pytest 不 import server.py, 路由加载错误只有 uvicorn 启动暴露 — C2 每次删除后都启动验证
- **删除脚本的块边界必须是所有顶层语句类型**: 赋值/表达式/装饰器函数 (@app.on_event) 都是边界, 否则静默吞代码

---

## 2026-08-01 — P2-C1: speaker 写路径双轨收敛 — 统一走 patch

### 改动
- **core 注册表级 opcode +3** (`core/runtime/patch.py`): `REGISTER_SPEAKER` (create) / `UPDATE_SPEAKER` (name+color) / `LOCK_SPEAKER` (is_locked), 均带 PatchEngine handler (不可变 SpeakerNodeIR 重建保留其余字段); 删 PROPAGATE 枚举残留 (Phase 3B 已删 handler, 枚举是死成员)
- **patch_adapter 映射补全**: ASSIGN_SPEAKER→ASSIGN_SPEAKER (此前漏映射走 ANNOTATE 静默落库)、MERGE_SPEAKERS→MERGE_SPEAKERS、CREATE_SPEAKER→REGISTER_SPEAKER、RENAME_SPEAKER→UPDATE_SPEAKER (name/color)、LOCK_SPEAKER→LOCK_SPEAKER; **删 `_UNSUPPORTED_SPEAKER_OPS` 拒绝表** (Phase 4 临时防御, 现在有对等语义); MERGE_SPEAKERS 缺 target 显式拒绝
- **前端统一 patch**: `useAppStore` OPCODE_MAP 死映射清理 (MERGE_SPEAKERS/RENAME_SPEAKER→ANNOTATE 退役); SpeakerReviewView 的 handleMerge/handleRename 从 `/api/speaker/*` 端点改走 patch (addDraft+applyDraft); CREATE_SPEAKER 伪 eventId 规范化 (`SPEAKER_${Date.now()}`)
- **删 13 个 speaker 专用端点** (server.py -384 行): save/inspect/split/reassign/resize/rename/regenerate-srt/merge/overlap-strategy/clustering-suggestions/drift-suggestions/bind/bindings + 8 个死 Request model + 零消费者 `_derive_pass_trace`; helper 保留 (patch/apply|undo 共用)
- **颜色持久化落地**: UPDATE_SPEAKER 写注册表 color — 此前颜色选择器从没生效过 (adapter 拒绝 422 静默失败), 现在 lane 颜色稳定持久
- 契约测试: patch_engine +5 (register/duplicate/update/lock/missing), adapter 映射表重写, patch_log schema 词表 +3; 全量 1031 passed + 10 xfailed

### 决策
- **patch 就是做这个的** (用户方向): 双轨的真相是同一 PatchEngine 的两个 HTTP 入口 — merge 端点内部就是构造 Patch 走 PatchEngine; 专用端点改注册表**不进 patch 链, undo/回滚覆盖不到**, 这才是双轨的真正代价
- **注册表级操作语义**: speaker 级 (create/lock/rename/merge) 走 patch 注册表 handler, 事件级 (split/resize/reassign/delete) 走既有事件 handler — 词表各归其位
- **颜色编辑不删而是修好**: 注册表 color 字段一直存在只缺写路径, UPDATE_SPEAKER 补上后 Phase 4 的 "显式 unsupported" 决策退役

### 冒烟实测 (curl 端到端, smoke_ws 副本)
- RENAME_SPEAKER: 注册表 name+color 持久化 ✓; LOCK_SPEAKER: is_locked=true ✓; CREATE_SPEAKER: 注册表新增 ✓; MERGE_SPEAKERS: 事件全部归并 ✓; undo 无 bak 显式 409 (诚实行为, 既有设计)

---

### 改动
- `server.py /api/subtitle/review/load`: 从 timeline.json 构建事件 start→id 映射, entries 附 `eventId` (按开始时间匹配, ±500ms 容差) — SRT 是 timeline 派生物无 ID, 时间匹配是唯一可靠关联
- `useAppStore.saveReviewEntries`: **预解析 eventId** (后端值 → store events 按时间兜底 → 都找不到响亮抛错), 删除 `entry_N` 伪 target 伪造; 解析在写 SRT 之前完成 — 无法关联的条目零写入, 禁止半完成
- 契约测试 +3: 带 eventId 保存成功 / 无 eventId 按时间兜底匹配 / 无匹配抛错且 SRT 零写入 (vitest 33/33)

### 决策
- **时间匹配是关联语义**: SRT 由 timeline 派生 (core 引擎), 开始时间精确对齐; ±500ms 容差吸收 legacy 路径分段差异
- **预解析先于写入**: 旧代码写 SRT 后才发现无法打 patch (半完成状态); 现在全部条目验证通过后才动任何写入
- **禁止伪造 target**: `entry_N` 是静默假数据的变体 — patch 链里出现不存在的 target, 污染事件历史

### 冒烟实测 (Playwright)
- review 编辑 → 保存 → **toast 已保存 + patch 链 +1** (修复前必 422 "target not found: entry_N")
- timeline 编辑草案 → 全部应用 回归通过 (patch 链 +1, 无错误 snackbar)

---

## 2026-08-01 — entry_N 修复: review 条目关联真实事件 ID (字幕校验保存恢复可用)

### 改动
- `server.py /api/subtitle/review/load`: 从 timeline.json 构建事件 start→id 映射, entries 附 `eventId` (按开始时间匹配, ±500ms 容差) — SRT 是 timeline 派生物无 ID, 时间匹配是唯一可靠关联
- `useAppStore.saveReviewEntries`: **预解析 eventId** (后端值 → store events 按时间兜底 → 都找不到响亮抛错), 删除 `entry_N` 伪 target 伪造; 解析在写 SRT 之前完成 — 无法关联的条目零写入, 禁止半完成
- 契约测试 +3: 带 eventId 保存成功 / 无 eventId 按时间兜底匹配 / 无匹配抛错且 SRT 零写入 (vitest 33/33)

### 决策
- **时间匹配是关联语义**: SRT 由 timeline 派生 (core 引擎), 开始时间精确对齐; ±500ms 容差吸收 legacy 路径分段差异
- **预解析先于写入**: 旧代码写 SRT 后才发现无法打 patch (半完成状态); 现在全部条目验证通过后才动任何写入
- **禁止伪造 target**: `entry_N` 是静默假数据的变体 — patch 链里出现不存在的 target, 污染事件历史

### 冒烟实测 (Playwright)
- review 编辑 → 保存 → **toast 已保存 + patch 链 +1** (修复前必 422 "target not found: entry_N")
- timeline 编辑草案 → 全部应用 回归通过 (patch 链 +1, 无错误 snackbar)

---

## 2026-08-01 — P1 前端吞错修复: 编辑失败必须响亮

### 改动
- `useAppStore.applyDraft`: 后端失败 (网络/4xx/5xx) → 设置 store.error + **保留 draft 供重试**, 不再"本地照常记录"(旧行为: 刷新后编辑静默丢失); 成功才删 draft + 记录 appliedPatches; reload 失败不再静默吞
- `useAppStore.applyAllDrafts`: 逐条提交, 部分失败 → 失败草案保留 + error 显示失败数; 错误信息在 reload 之后设置 (避免成功刷新吞掉失败提示)
- `useAppStore.undoLastPatch`: 后端失败 → 不删本地 appliedPatches + error 设置; 返回 `{ok, patch}` 显式区分"无补丁可撤"与"撤销失败"
- `useAppStore.fetchSpeakerLanes`: **删 mock 降级** — 失败清空 lanes + 响亮报错, 绝不回退假数据 (MOCK_SPEAKER_LOAD 引用删除)
- `App.tsx`: 订阅 store.error → 全局 snackbar 展示 (此前 error 只在 WorkspaceSelector Popover 红字可见, timeline 等模式编辑失败用户无感知)
- `WordSplitDialog`: 仅 apply 成功才关闭对话框 (失败保留供重试)
- `saveReviewEntries`: applyDraft 返回 false → 抛错中断 (不再静默部分完成)
- 新增 `GUI/__tests__/useAppStoreFailLoud.test.ts` 契约测试 8 个: 网络失败/422/部分失败/全部失败/撤销失败/mock 降级删除
- 新增 `test_trail/fail_loud_smoke.cjs` Playwright 冒烟 (6 步, 需后端+vite)

### 决策
- **失败是用户的错误不是日志的**: 旧 catch 静默 + 本地记录 = "成功的错误输出"(三条原则明令禁止); 现在失败 → snackbar + draft 保留
- **加载失败不降级假数据**: fetchSpeakerLanes 失败回退 mock 是静默假数据, 与 mock 演示模式无关, 一律删
- **undo 返回值语义化**: `Promise<{ok, patch}>` 消灭 null 双义 (无补丁 vs 失败)

### 冒烟实测 (Playwright, smoke_ws 副本工作区)
- 成功路径: timeline 编辑译文 → 保存草案 → 补丁模式全部应用 → patch 链 +1, 无错误 snackbar
- 错误路径: review 保存 → snackbar "补丁应用失败: target not found: entry_1" t+1s 内出现; toast "已保存" 不出现
- **顺带暴露既有 bug**: saveReviewEntries 用 `entry_N` 伪造 patch target (review/load 条目无 eventId) → 保存必然失败 — 响亮化让问题显形, 留待 P2/P3 处理

---

## 2026-08-01 — xCOMET-lite 设为默认质量策略

- `GlobalConfig translation.gate.mode` 默认 logic_gate → **xcomet**; quality_check
  无配置 fallback 同步; CLI gate_mode fallback 同步
- 配置路径: config/translate.yaml `verification_mode` (xcomet|logic_gate) → gate.mode
- 契约测试更新: 无配置默认 → xcomet
- 模型缺失/加载失败 → 诚实降级 Gate B + 人工审核 (机制已锁定)
- 遗留: xcomet 阈值 (accept 0.70/review 0.40) 对短语气句偏严, 待校准

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
