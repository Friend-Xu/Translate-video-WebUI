# Translate_video — 视频字幕提取 / 翻译 / TTS 合成流水线

将视频自动转写为字幕、翻译目标语言、TTS 语音合成配音的端到端流水线。

支持两条线路：
- **字幕提取 + 翻译**（旧，成熟稳定）
- **字幕提取 + 翻译 + TTS 语音合成**（新，建议使用）

## 快速开始

### 环境要求

- Python 3.11.9（已验证）
- ffmpeg（需添加到 PATH）
- 网络：中国大陆用户自动走 `hf-mirror.com`

### 安装

```bash
# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 模型自动下载（首次运行自动触发，存放在 models/ 目录）
```

### 运行完整流水线（推荐 🆕）

一行命令走完 4 步：字幕提取 → 翻译 → TTS 合成 → 拼接最终视频：

```bash
.venv\Scripts\python translate_video.py source_file/test.mp4 --lang en
```

可选参数：

| 参数 | 说明 |
|------|------|
| `--lang en` | 指定源语言（自动检测可省略） |
| `--model small` | whisper 模型大小 (tiny/base/small/medium/large-v3) |
| `--tts-workers 2` | TTS 线程数 |
| `--skip-extract` | 跳过字幕提取（复用已有 SRT） |
| `--skip-translate` | 跳过翻译（复用已有翻译 SRT） |

输出目录 `source_file/{video_name}_out/`，最终视频 `{name}-TTS.mp4`。

### 运行旧流水线（仅字幕翻译）

```bash
# 方式一：交互式（旧）
.venv\Scripts\python multi_start_translate_video.py
# 按提示输入视频路径

# 方式二：一键提取
.venv\Scripts\python extract_subtitles.py source_file/test.mp4 --lang en
```

### 配置

#### TTS 配置 (`config/tts.yaml`)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `voice` | zh-CN-XiaoxiaoNeural | Edge TTS 发音人 |
| `base_speed` | +30% | TTS 基础语速 |
| `max_speed` | +70% | TTS 最大语速（超过此值调视频速度） |
| `speed_tolerance` | 0.15 | 容忍度：±15% 内调视频，超过则重调 TTS |
| `enable_caption` | true | 是否渲染字幕 |
| `enable_openvoice` | false | OpenVoice 音色克隆（暂为 Noop） |
| `video_codec` | libx264 | 视频编码器 |
| `video_bitrate` | 10M | 视频比特率 |

#### 翻译配置 (`config/translate.yaml`)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `api_key` | — | DeepSeek API Key（必填） |
| `model` | deepseek-chat | 翻译模型 |
| `source_lang` | ja | 源语言（ja/en/zh 等） |
| `semantic_check` | true | 启用语义核对 |
| `semantic_threshold` | 0.65 | 语义相似度阈值 |

## 模块一览

### TTS 语音合成模块（新 🆕）

| 模块 | 文件 | 职责 |
|------|------|------|
| TTS 引擎接口 | `pipeline/tts_engine.py` | BaseTTSEngine Protocol + NoopTTSEngine |
| Edge TTS | `pipeline/tts_edge.py` | edge-tts 实现（3 重试 + 错误日志） |
| 时序对齐 | `pipeline/tts_timing.py` | TimingAdjuster — 语速调整至目标时长 |
| 视频处理 | `pipeline/tts_video.py` | VideoSegmenter — 视频段裁剪/变速 |
| 字幕渲染 | `pipeline/tts_caption.py` | CaptionRenderer — 字幕叠加 |
| 音色克隆 | `pipeline/tts_openvoice.py` | OpenVoiceCloner（目前 Noop） |
| 编排器 | `pipeline/tts_pipeline.py` | TtsPipeline — TTS 全流程编排 |
| 断点恢复 | `pipeline/tts_resume.py` | ResumeManager — 进度保存/恢复 |
| 兼容层 | `pipeline/tts_adapter.py` | TTSAdapter — 旧接口包装 |
| 配置 | `pipeline/tts_config.py` | TTSConfig — 配置加载 + SRT 解析 |

### 字幕提取模块（旧）

| 模块 | 文件 | 职责 |
|------|------|------|
| 人声分离 | `SRT/VocalSeparator.py` | Demucs htdemucs 分离人声与背景 |
| VAD 分段 | `SRT/VAD_Segmenter.py` | Silero VAD 检测语音段（阈值 0.25） |
| 转写+对齐 | `SRT/SRT_Extract.py` | whisperX 转写 + wav2vec2 强制对齐（旧线） |
| 字幕整理 | `SRT/Json_Convert_Srt.py` | JSON → SRT，日语启用 MeCab 分词 |
| 翻译引擎 | `SRT/SRT_Translator.py` | DeepSeek API 翻译，三级降级 + 语义分组 |
| 语义核对 | `SRT/TranslationVerifier.py` | 跨语言嵌入比较相似度 |
| 定点识别 | `SRT/TargetedRecognizer.py` | 可疑字幕重新转录验证 |
| 术语替换 | `SRT/TermReplacer.py` | 技术术语词典替换（Minecraft 299 条） |
| 主线编排 | `extract_subtitles.py` | NODE 1→1.5→2→2.5→3→3.5→4（~200 行薄层） |

## 输出文件

输入 `test.mp4` → 输出 `source_file/test_out/`：

```
test.srt                    # 原文 SRT
test-en.srt                 # 英文字幕（源语言）
test-zh.srt                 # 翻译后 SRT
test-zh-replace.srt         # 最终 SRT（术语替换后）
test_(Instrumental).wav     # 背景音乐（供 TTS 合成）
video/                      # 逐段视频片段
tts_audio/                  # TTS 合成音频
audio/                      # 处理中间音频
test-TTS.mp4                # 最终合成视频
```

## 架构要点

详见 `ARCHITECTURE.md`。

- **TTS 引擎协议**：Protocol 模式，支持 Edge/ChatTTS/Cooqui/Azure 切换
- **两档语速决策**：±15% 容忍度内调视频速度，超出则重新 TTS 合成
- **背景音乐保留**：从原视频提取独立 Instrumental 音轨，保留背景乐
- **断点续传**：ResumeManager 支持进度保存，中断可恢复
- **零侵入**：新模块全部独立文件，旧代码一刀不改

## 模型存储

所有模型自动下载到项目 `models/` 目录，不依赖系统缓存，项目可整体迁移。

```
models/
├── whisper/       # faster-whisper-small (461MB)
├── alignment/     # wav2vec2 对齐模型 (1.2GB)
├── vad/           # Silero VAD v4.0 (3MB)
└── hf_cache/      # sentence-transformers 等 (470MB)
```
