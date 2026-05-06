# Translate_video — 视频字幕提取 / 翻译 / TTS 语音合成流水线

将视频自动转写字幕 → 翻译目标语言 → TTS 语音合成配音 → 最终合成视频的端到端流水线。

## 快速开始

### 环境要求

- Python 3.12（已验证，3.11+ 应该兼容）
- ffmpeg（自动使用 `imageio_ffmpeg` 捆绑版，无需手动安装）
- 网络：中国大陆用户自动走 `hf-mirror.com` 镜像下载模型
- GPU：推荐 NVIDIA GPU（CUDA），CPU 模式也支持但速度较慢

### 安装

```bash
# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

模型在首次运行时会自动下载到 `models/` 目录，无需手动操作。

### 运行流水线

**推荐方式 — `main.py`（3 步：提取 → 翻译 → TTS）：**

```bash
# GPU 默认（turbo 模型 + CUDA + float16）
.venv\Scripts\python main.py source_file/test.mp4 --lang ja

# 跳过 Demucs 人声分离（干净音频更快）
.venv\Scripts\python main.py source_file/test.mp4 --lang en --skip-demucs

# CPU 回退
.venv\Scripts\python main.py source_file/test.mp4 --device cpu --compute-type int8
```

**仅字幕提取（不翻译、不 TTS）：**

```bash
# GPU 默认
.venv\Scripts\python extract_subtitles.py source_file/test.mp4 --lang ja

# 并发加速（VRAM 足够时）
.venv\Scripts\python extract_subtitles.py source_file/test.mp4 --lang ja --num-workers 2

# CPU 回退
.venv\Scripts\python extract_subtitles.py source_file/test.mp4 --device cpu --compute-type int8
```

**仅翻译（已有 SRT 文件）：**

```bash
.venv\Scripts\python -m SRT.SRT_Translator path/to/file-collation.srt
```

**VAD 性能基准测试：**

```bash
# 对比 ONNX vs JIT 推理速度
.venv\Scripts\python tests/benchmark_vad.py source_file/video.mp4 --quick
```

### 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--lang` | 自动检测 | 源语言 (en/ja/zh)，指定后启用 wav2vec2 对齐 |
| `--model` | turbo | whisper 模型 (tiny/base/small/medium/turbo/large-v3) |
| `--device` | cuda | 计算设备 (cuda/cpu) |
| `--compute-type` | float16 | 计算精度 (float16/int8_float16/int8/float32) |
| `--engine` | edge | TTS 引擎 (edge/chattts) |
| `--num-workers` | 1 | whisper 并发 worker 数 (1=串行, 2~4=并行, VRAM 自动限制) |
| `--skip-extract` | — | 跳过字幕提取（复用已有 SRT） |
| `--skip-translate` | — | 跳过翻译 |
| `--skip-tts` | — | 跳过 TTS 合成 |
| `--skip-demucs` | — | 跳过 Demucs 人声/背景分离（使用完整音轨） |
| `--skip-defect-check` | — | 跳过音频缺陷检测 (NODE 1.5) |
| `--force` | — | 强制重新执行所有步骤 |
| `--backup-dir` | — | 每步自动备份到指定目录 |
| `--caption-font` | — | 字幕字体路径 |
| `--caption-font-size` | — | 字幕字号 (0=自动) |
| `--caption-font-color` | #ffffff | 字幕字体颜色 |
| `--caption-stroke-width` | — | 字幕描边宽度 |
| `--caption-stroke-color` | — | 字幕描边颜色 |
| `--caption-bg-color` | — | 字幕背景色 (rgba) |
| `--caption-alignment` | center | 字幕对齐 (center/left/right) |
| `--caption-position` | bottom | 字幕位置 (bottom/top) |
| `--caption-max-lines` | 2 | 最大行数 |
| `--caption-font-size-factor` | 0.030 | 自动字号比例因子 |
| `--caption-width-ratio` | 0.85 | 字幕最大宽度比例 |
| `--no-optimize-subtitles` | — | 禁用字幕拆分优化 |
| `--export-external-srt` | — | 输出外挂字幕优化版 |
| `--ext-srt-mode` | — | 外挂字幕模式 (target_only/source_only/bilingual) |

### WebUI 启动

项目提供了 React + Python 的 Web 界面，支持单视频处理和批处理模式：

```bash
# 双击运行
GUI\start_WebUI.bat

# 或手动启动后端（端口 8000）
.venv\Scripts\python -m uvicorn GUI.server:app --host 127.0.0.1 --port 8000
```

启动后浏览器访问 `http://localhost:5173`（前端开发模式）或 `http://localhost:8000`（后端直连）。

**WebUI 功能：**
- **步骤配置面板**：三步可视化配置（字幕提取 / 翻译 / TTS），支持 GPU VRAM 自动检测和并发限制
- **单视频模式**：选择视频 → 配置参数 → 一键处理，SSE 实时日志推送
- **批处理模式**：添加多个视频 → 拖拽排序 → 顺序处理，支持跳过/取消当前视频
- **字幕校准面板**：手动审核翻译、标记问题条目、保存修改
- **外挂字幕优化器**：独立工具，优化字幕可读性（拆分长句、调整时长）

## 配置

### 翻译配置 (`config/translate.yaml`)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `api_key` | — | DeepSeek API Key（必填，也可设环境变量 `DEEPSEEK_API_KEY`） |
| `model` | deepseek-chat | 翻译模型 |
| `source_lang` | ja | 源语言 |
| `semantic_check` | true | 启用语义相似度核对 |
| `semantic_threshold` | 0.65 | 语义相似度阈值 |
| `terms_dict.enabled` | true | 启用术语词典替换 |
| `max_group_size` | 8 | 批翻译每组最大条数 |
| `max_retries` | 2 | 翻译失败重试次数 |

### TTS 配置 (`config/tts.yaml`)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `voice` | zh-CN-XiaoxiaoNeural | Edge TTS 发音人 |
| `base_speed` | 30 | TTS 基础语速 (+30%) |
| `max_speed` | 70 | TTS 最大语速 (+70%) |
| `speed_tolerance` | 0.15 | 语速容忍度 |
| `enable_caption` | true | 渲染字幕到视频 |
| `enable_openvoice` | false | OpenVoice 音色克隆 |
| `video_codec` | libx264 | 视频编码器 |
| `video_bitrate` | 10M | 视频比特率 |
| `threading_workers` | 7 | TTS 并行线程数 |
| `imagemagick_binary` | magick | ImageMagick 路径（字幕渲染依赖） |

### 字幕样式配置 (`config/caption.yaml`)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `font` | — | 字幕字体路径 |
| `font_size` | 0 | 字号 (0=自动按视频尺寸计算) |
| `font_size_factor` | 0.03 | 自动字号比例因子 |
| `width_ratio` | 0.85 | 字幕最大宽度比例 |
| `font_color` | #ffffff | 字体颜色 |
| `stroke_width` | 1.5 | 描边宽度 |
| `stroke_color` | — | 描边颜色 |
| `bg_color` | — | 背景色 (rgba) |
| `alignment` | center | 对齐方式 |
| `position` | bottom | 字幕位置 |
| `max_lines` | 2 | 最大行数 |
| `enable_subtitle_optimization` | true | 启用字幕质量优化 |

## 输出文件

输入 `test.mp4` → 输出到 `source_file/test_out/`：

```
test.srt                    # 原文 SRT
test-en.srt                 # 英文字幕（源语言）
test-zh.srt                 # 翻译后 SRT
test-zh-replace.srt         # 术语替换后最终 SRT
test_(Instrumental).wav     # 背景音乐（Demucs 分离）
video/                      # 逐段视频片段
tts_audio/                  # TTS 合成音频
test-TTS.mp4                # 最终合成视频（目标语言配音 + 双语字幕）
```

## 模块结构

```
Translate_video/
├── main.py                  # 推荐入口：3 步流水线
├── translate_video.py       # 备选入口：4 步流水线
├── extract_subtitles.py     # 字幕提取入口（独立运行）
├── pipeline/                # 核心模块
│   ├── audio.py             # 音频提取 + C2 缺陷修复
│   ├── transcriber.py       # Silero VAD + faster-whisper + wav2vec2 对齐
│   ├── video_info.py        # 视频元数据采集
│   ├── gpu_detect.py        # GPU/编码器自动检测
│   ├── speed_strategy.py    # 语速调整策略
│   ├── demucs_instr.py      # Demucs 人声/背景分离
│   ├── tts_engine.py        # TTS 引擎协议 (Protocol)
│   ├── tts_edge.py          # Edge TTS 实现
│   ├── tts_chattts.py       # ChatTTS 实现
│   ├── tts_timing.py        # 时序对齐 (TimingAdjuster)
│   ├── tts_video.py         # 视频分段/变速/合成
│   ├── tts_caption.py       # 字幕渲染 (CaptionRenderer)
│   ├── tts_pipeline.py      # TTS 全流程编排
│   ├── tts_adapter.py       # 兼容层封装
│   ├── tts_config.py        # 配置加载 + SRT 解析
│   ├── tts_resume.py        # 断点续传
│   ├── caption_config.py    # 字幕样式配置
│   ├── subtitle_optimizer.py # 字幕质量优化
│   └── utils.py             # 通用工具 (ffmpeg 路径等)
├── SRT/                     # 字幕处理工具
│   ├── SRT_Translator.py    # DeepSeek 翻译（3 级降级）
│   ├── TranslationVerifier.py # 跨语言语义核对
│   ├── TermReplacer.py      # 术语词典替换
│   ├── Wav2Vec2Aligner.py   # wav2vec2 强制对齐封装
│   ├── VAD_Segmenter.py     # Silero VAD (ONNX 加速, ~9x 提速)
│   ├── Json_Convert_Srt.py  # JSON → SRT 转换器
│   └── Json_Convert_Srt_EN.py # JSON → SRT 转换器 (英文)
├── whisperx_local/          # 剪裁版 whisperX 对齐模块
├── openvoice_cli/           # OpenVoice 音色克隆 CLI
├── config/                  # YAML 配置文件
│   ├── translate.yaml       # 翻译配置（gitignored，含 API Key）
│   ├── translate.yaml.example # 翻译配置模板
│   ├── tts.yaml             # TTS 配置
│   ├── caption.yaml         # 字幕样式配置
│   └── terms/               # 术语词典
├── GUI/                     # React WebUI
│   ├── start_WebUI.bat      # 一键启动前后端
│   ├── launcher.py          # WebUI 启动器
│   ├── server.py            # Python 后端 (FastAPI + uvicorn)
│   └── ...
├── tests/                   # 测试
│   ├── test_tts/            # TTS 测试套件
│   └── benchmark_vad.py     # VAD 性能基准测试 (ONNX vs JIT)
├── models/                  # 模型缓存（gitignored）
└── source_file/             # 测试视频（gitignored）
```

## 模型存储

所有模型自动下载到 `models/` 目录，项目可整体迁移：

```
models/
├── whisper/       # faster-whisper (small/medium/turbo/large-v3)
├── alignment/     # wav2vec2 对齐模型
├── vad/           # Silero VAD v4.0 (ONNX 主后端 + JIT fallback)
├── hf_cache/      # HuggingFace 缓存
├── TTS_model/     # ChatTTS 模型
├── Demucs/        # 人声分离模型
├── font/          # 字幕字体
└── WavMark/       # 音频水印模型
```

## 运行测试

```bash
# 运行所有 TTS 测试
.venv\Scripts\python -m pytest tests/test_tts/ -v

# 运行单个测试文件
.venv\Scripts\python -m pytest tests/test_tts/test_tts_edge.py -v

# VAD 性能基准测试（对比 ONNX vs JIT）
.venv\Scripts\python tests/benchmark_vad.py source_file/video.mp4 --quick
```

## 架构要点

详见 `ARCHITECTURE.md`。

- **GPU 默认加速**：faster-whisper 默认使用 CUDA + float16 + turbo 模型，比旧 CPU/small/int8 默认快 15-50 倍
- **ONNX VAD 推理**：Silero VAD 从 PyTorch JIT 切换至 ONNX Runtime，~9 倍提速，bit-exact 精度（JIT 自动 fallback）
- **并发控制**：`--num-workers` 并行 whisper 转录，VRAM 自动限制防 OOM
- **TTS 引擎协议**：Protocol 模式，支持 Edge/ChatTTS 切换
- **两档语速决策**：±15% 容忍度内调视频速度，超出重新 TTS 合成
- **背景音乐保留**：Demucs 分离人声，保留背景乐到最终视频
- **断点续传**：ResumeManager 支持进度保存，中断可恢复
- **C2 缺陷修复**：OBS 录制视频 AAC 填充间隙自动修复
- **GPU 编码器自动检测**：自动选择最优 ffmpeg 编码器
- **模型自包含**：所有模型存于项目目录，不依赖系统路径

## 许可证

MIT License — 详见 `LICENSE`
