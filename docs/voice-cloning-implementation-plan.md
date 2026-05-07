# Voice Cloning 实现计划 — 并行 Agent 执行版

*Created: 2026-05-07 | Target: OpenVoice 优化 + CosyVoice 2.0 VC 集成*

## 执行策略

使用 ECC 子代理并行处理互不干扰的子任务，减少上下文膨胀，加快开发速度。

```
Phase 1 (主线程, 30min)
├── 1.1 VoiceCloner Protocol 定义
├── 1.2 TTSConfig 配置字段扩展
└── 1.3 VRAM 检测模块
         │
         │  ← 共享契约就绪，分叉并行
         │
    ┌────┴────────────────────┐
    │                         │
Phase 2 (Agent A, 3-4h)   Phase 3 (Agent B, 4-6h)
OpenVoice 优化             CosyVoice 2.0 VC
    │                         │
    └────┬────────────────────┘
         │  ← 两个模块都完成，合并
         │
Phase 4 (主线程, 1-2h)
├── 4.1 Pipeline 集成
├── 4.2 CLI 参数
├── 4.3 配置 YAML
└── 4.4 测试验证
```

---

## Phase 1: 共享契约 (主线程，顺序执行)

Phase 2 和 3 的共同依赖，必须先行。

### 1.1 VoiceCloner Protocol → `pipeline/vc_base.py` (新建)

统一的音色克隆 Protocol，替代现有 `OpenVoiceCloner` Protocol:

- `VoiceCloneConfig` 数据类: engine, device, vram_limit_mb, concurrent_workers, model_dir, color_audio_path, enable_watermark
- `VoiceCloner` Protocol: prepare(), clone(), device_info(), cleanup()
- `NoopVoiceCloner`: 空操作占位实现

### 1.2 TTSConfig 扩展 → `pipeline/tts_config.py`

新增字段（保持向后兼容）:
- `voice_clone_engine: str = "openvoice"` — "openvoice" | "cosyvoice" | "none"
- `voice_clone_device: str = "auto"`
- `voice_clone_concurrency: int = 1`
- `voice_clone_vram_limit_mb: int = 0` — 0=自动检测

兼容迁移: `enable_openvoice=True` 自动映射为 `voice_clone_engine="openvoice"`

### 1.3 VRAM 检测 → `pipeline/vc_device.py` (新建)

- `detect_vram_mb(device)` — 查询 GPU 显存
- `detect_best_device(vram_limit)` — 返回最优 device 字符串
- `recommend_engine(available_vram)` — 根据 VRAM 推荐引擎

阈值: `<4GB` → CPU/OpenVoice, `4-8GB` → GPU OpenVoice, `≥8GB` → CosyVoice

---

## Phase 2: OpenVoice 优化 (Agent A, background)

**独立文件** (不与 Phase 3 冲突):
- `pipeline/vc_openvoice.py` — 新建
- `openvoice_cli/se_extractor.py` — 修改: 参数化 device
- `openvoice_cli/api.py` — 修改: 参数化 device

**任务**:

| # | 任务 | 说明 |
|---|------|------|
| 2.1 | `OpenVoiceCloner` | 实现 VoiceCloner Protocol |
| 2.2 | 低显存模式 | CPU fallback, fp16, chunked, Whisper 延迟加载 |
| 2.3 | 高显存并发 | ThreadPoolExecutor 并行 clone, embedding 内存缓存 |
| 2.4 | Embedding 持久化 | `.se_cache/{hash}.pt` 跨会话复用 |
| 2.5 | 修复硬编码 device | se_extractor/api 接受 device 参数 |

---

## Phase 3: CosyVoice 2.0 VC 集成 (Agent B, background)

**独立文件** (不与 Phase 2 冲突):
- `pipeline/vc_cosyvoice.py` — 新建
- `config/cosyvoice.yaml` — 新建

**任务**:

| # | 任务 | 说明 |
|---|------|------|
| 3.1 | 调研 API | CosyVoice 2.0 VC 调用方式: pip vs Docker |
| 3.2 | `CosyVoiceCloner` | 实现 VoiceCloner Protocol, zero-shot 克隆 |
| 3.3 | 高显存优化 | GPU 推理, embedding 缓存 |
| 3.4 | Error handling | 失败降级 OpenVoice |
| 3.5 | Docker 支持 | 可选 Docker 部署 |

---

## Phase 4: Pipeline 集成 (主线程，顺序执行)

Phase 2+3 完成后统一接入:

### 4.1 VoiceCloner 工厂 → `pipeline/tts_pipeline.py`

`_default_openvoice()` 改为 `_default_voice_cloner()`，按 `voice_clone_engine` 工厂创建。

### 4.2 VideoSegmenter 适配 → `pipeline/tts_video.py`

`clone_color` 回调改为 VoiceCloner 接口。

### 4.3 配置 → `config/tts.yaml`

新增 voice_clone 配置段。

### 4.4 CLI → `main.py`

新增 `--voice-clone-engine`, `--vram-limit`。

### 4.5 测试 → `tests/test_vc/`

`test_vc_device.py`, `test_vc_openvoice.py`, `test_vc_cosyvoice.py`

---

## 文件冲突矩阵

确保两个并行 Agent 不编辑同一文件:

| 文件 | P1 | P2(A) | P3(B) | P4 |
|------|-----|------|------|-----|
| `pipeline/vc_base.py` | **新建** | 读 | 读 | 读 |
| `pipeline/vc_device.py` | **新建** | 读 | 读 | 读 |
| `pipeline/tts_config.py` | **修改** | — | — | **修改** |
| `pipeline/vc_openvoice.py` | — | **新建** | — | 读 |
| `openvoice_cli/se_extractor.py` | — | **修改** | — | — |
| `openvoice_cli/api.py` | — | **修改** | — | — |
| `pipeline/vc_cosyvoice.py` | — | — | **新建** | 读 |
| `config/cosyvoice.yaml` | — | — | **新建** | — |
| `pipeline/tts_pipeline.py` | — | — | — | **修改** |
| `pipeline/tts_video.py` | — | — | — | **修改** |
| `config/tts.yaml` | — | — | — | **修改** |

**结论**: Phase 2 和 Phase 3 写入文件完全不重叠，可安全并行。

---

## 执行顺序总结

```
Step 1: 主线程 Phase 1 (30min)
        → vc_base.py, vc_device.py, tts_config.py 修改
        → git commit checkpoint

Step 2: 并行 Agent A + Agent B
        → Agent A: vc_openvoice.py + openvoice_cli 修改
        → Agent B: vc_cosyvoice.py + cosyvoice.yaml
        → 独立工作，无通信

Step 3: 主线程 Phase 4 (1-2h)
        → tts_pipeline.py, tts_video.py, tts.yaml 集成

Step 4: Code Review + Security Review (并行 agent)
```

## Risk Control

- Phase 1 先 commit checkpoint
- Phase 2/3 任一失败不影响另一条线
- 写入文件零重叠，不会 git conflict
