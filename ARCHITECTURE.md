# 架构参考 — Translate_video

## 数据流概览

本系统支持**两条流水线**，共享前置检测/修复步骤：

1. **主线（faster-whisper 转录 + wav2vec2 对齐）** — `extract_subtitles.py`，推荐路径
2. **旧线（whisperX 完整包）** — `SRT_Extract.py`，仅作参考，因 whisperX 包依赖问题不推荐

无论哪条流水线，**C2 缺陷检测 + aresample 修复是前置必经步骤**。

```
输入视频.mp4
    │
    ├──┬─────────────────────────────────────────────────┐
    │  │  0. 视频时长缺陷检测  MediaValidator.py           │
    │  │     采集 CD(容器时长), ADD(解码音频时长), TVF     │
    │  │     TVF(帧数), avg_fps, VFR 标志                  │
    │  │     决策树: C2 / C1 / A2 / E1                    │
    │  │     诊断结果写入日志                             │
    │  │     注: 不下修视频本身（不动源 .mp4），         │
    │  │     音频修复在步骤 0.5 提取 WAV 时自动完成     │
    │  │                                                   │
    │  │  📍 嵌入位置:                                    │
    │  │     ● extract_subtitles.py NODE 1.5               │
    │  │     ● SRT_Extract.extract_with_whisperx() 开头    │
    │  │     ● Video_subtitle_pipeline 入口                │
    │  └────────────────────────────────────────────────────┘
    │
    ├──┬─────────────────────────────────────────────────┐
    │  │  0.5. 音频提取 + C2 修复                        │
    │  │     【核心入口】 ensure_audio_duration()         │
    │  │     定义在 MediaValidator.py，所有提取器统一调用  │
    │  │                                                   │
    │  │     流程:                                        │
    │  │       ffmpeg -i video → 解析 Duration →          │
    │  │       获取 CD → 判断 CD > 0 →                   │
    │  │       aresample=async=1:first_pts=0 + -t <CD> →  │
    │  │       验证 WAV 时长偏差是否 < 0.5s               │
    │  │                                                   │
    │  │     原理: aresample=async=1 在输入样本耗尽时     │
    │  │     自动插入样本保持 PTS 同步（非静音填充）。     │
    │  │     first_pts=0 让输出首帧从 0 开始。            │
    │  │     -t <CD> 让 ffmpeg 输出直到容器时长。         │
    │  │                                                   │
    │  │     ffmpeg 来源优先级:                           │
    │  │       imageio_ffmpeg.get_ffmpeg_exe() →           │
    │  │       .venv/binaries/ → PATH 内 ffmpeg             │
    │  │                                                   │
    │  │  📍 调用位置:                                    │
    │  │     ● extract_subtitles.py NODE 2 — 主线         │
    │  │     ● VocalSeparator._prepare_audio() — Demucs   │
    │  │     ● AudioSeparator.extract_audio() — spleeter  │
    │  └────────────────────────────────────────────────────┘
    │
    │  接下来分两条流水线：
    │
    ▼──────────────────────────────────────────────────────
    │                                                       │
    │  流水线 A: SRT_Extract 旧线 (whisperX 完整包)       │
    │  ─────────────────────────────────────────────────    │
    │  注: 因 whisperX 依赖 ctranslate2==4.4.0 与           │
    │  Python 3.14 不兼容，此路径仅作参考。                 │
    │                                                       │
    │  ┌──────────────────────────────────────────────┐    │
    │  │  1. 人声分离  VocalSeparator.py              │    │
    │  │     Demucs htdemucs (CPU)                   │    │
    │  │     _prepare_audio() 内部调用                │    │
    │  │     ensure_audio_duration() 自动 aresample   │    │
    │  │     输出: htdemucs/<name>/vocals.wav         │    │
    │  └──────────────────────────────────────────────┘    │
    │  │ 也可通过 AudioSeparator (spleeter/separate_vocals.py)
    │  │ 同样走 ensure_audio_duration()
    │  │ vocals.wav
    │  ▼
    │  ┌──────────────────────────────────────────────┐    │
    │  │  2. VAD 分段  VAD_Segmenter.py               │    │
    │  │     Silero VAD v4.0                          │    │
    │  │     阈值: 0.25（对 ASMR/弱人声友好）          │    │
    │  │     分块处理防 OOM（5min/块，1s 重叠）        │    │
    │  │     输出: 按时间排序的语音段列表              │    │
    │  └──────────────────────────────────────────────┘    │
    │  │ 语音段时间戳
    │  ▼
    │  ┌──────────────────────────────────────────────┐    │
    │  │  3. whisperX 转录 + wav2vec2 对齐            │    │
    │  │     SRT_Extract.extract_with_whisperx()       │    │
    │  │     输出: JSON（词级时间戳）                  │    │
    │  └──────────────────────────────────────────────┘    │
    │  │ 词级时间戳 JSON
    │  ▼
    │  ┌──────────────────────────────────────────────┐    │
    │  │  4. 字幕整理  Json_Convert_Srt.py            │    │
    │  │     词级 → 按语义/停顿重组整句               │    │
    │  │     日语: MeCab (fugashi+ipadic)              │    │
    │  │     输出: .srt 字幕                          │    │
    │  └──────────────────────────────────────────────┘    │
    │  │
    ├──▶ 后续共用翻译/核对/术语替换链 ──────────────────   │
    │                                                       │
    │  流水线 B: extract_subtitles.py 主线（推荐）        │
    │  ─────────────────────────────────────────────────    │
    │  extract_subtitles.py — 模块化编排器                 │
    │                                                       │
    │  设计原则: pipeline/ 模块分工→薄编排器                │
    │                                                       │
    │  流程:                                                │
    │  ┌────────────────────────────────────────────┐      │
    │  │  NODE 1   视频信息采集                     │      │
    │  │           pipeline/video_info.py           │      │
    │  │           get_video_info(ffmpeg -i)        │      │
    │  │           输出: Duration, codec, 文件大小  │      │
    │  └────────────────────────────────────────────┘      │
    │          │                                           │
    │          ▼                                           │
    │  ┌────────────────────────────────────────────┐      │
    │  │  NODE 1.5 时长缺陷检测                     │      │
    │  │           MediaValidator.diagnose()        │      │
    │  │           C2/CD-ADD偏差诊断                │      │
    │  └────────────────────────────────────────────┘      │
    │          │                                           │
    │          ▼                                           │
    │  ┌────────────────────────────────────────────┐      │
    │  │  NODE 2   音频提取 + aresample 修复        │      │
    │  │           pipeline/audio.py                │      │
    │  │           extract_audio_with_fix()         │      │
    │  │           输出: WAV (16kHz, mono, PCM16)   │      │
    │  └────────────────────────────────────────────┘      │
    │          │                                           │
    │          ▼                                           │
    │  ┌────────────────────────────────────────────┐      │
    │  │  NODE 3   VAD 分段 + faster-whisper 转录   │      │
    │  │           pipeline/transcriber.py          │      │
    │  │           VADTranscriber                   │      │
    │  │           3a. run_vad() → Silero VAD       │      │
    │  │           3b. merge_segments() → 合并短段  │      │
    │  │           3c. transcribe_all() → 逐段转录  │      │
    │  └────────────────────────────────────────────┘      │
    │          │                                           │
    │          ▼                                           │
    │  ┌────────────────────────────────────────────┐      │
    │  │  NODE 3.5  wav2vec2 强制对齐               │      │
    │  │           whisperx_local.alignment          │      │
    │  │           align_all()                      │      │
    │  │           加载 Wav2Vec2ForCTC (~8s/450MB)  │      │
    │  │           对每个 segment 执行 CTC 对齐      │      │
    │  │           输出帧级精度（~20ms）词级时间戳  │      │
    │  │           启用: --lang ja 参数              │      │
    │  └────────────────────────────────────────────┘      │
    │          │                                           │
    │          ▼                                           │
    │  ┌────────────────────────────────────────────┐      │
    │  │  NODE 4   SRT 生成                         │      │
    │  │           Json_Convert_Srt                 │      │
    │  │           convert_json_to_srt()             │      │
    │  │           (MeCab 日语分词，可选)            │      │
    │  └────────────────────────────────────────────┘      │
    │          │                                           │
    │          ▼                                           │
    │  ┌────────────────────────────────────────────┐      │
    │  │  NODE 5   翻译 (SRT_Translator)            │      │
    │  │           可选: 语义核对 + 术语替换        │      │
    │  └────────────────────────────────────────────┘      │
    │                                                       │
    │  NODE 3 特点:                                        │
    │  ● 合并短段（gap<0.5s 且总长<120s）减少推理调用     │
    │  ● 每段 sf.read 动态截取，避免加载全音频             │
    │  ● word_timestamps=True 获取词级时间戳               │
    │  ● 停顿>1.5s 切分 segment                          │
    │  ● 每 10 段 gc.collect() 防内存泄漏                  │
    │                                                       │
    │  NODE 3.5 (wav2vec2 强制对齐):                       │
    │  ● 从 whisperX 剥离（whisperx_local/）               │
    │  ● Wav2Vec2ForCTC 加载 ~450MB（缓存后 ~7s）          │
    │  ● 对每个 segment 逐段运行 CTC 强制对齐               │
    │  ● 输出 ~20ms 精度的词级时间戳                       │
    │  ● 解决 faster-whisper 词级时间戳偏差和漂移           │
    │  ● 启用: --lang ja（auto-detect 时不启用）           │
    │  ● 实现: transcriber.align_all()                      │
    │  ● 封装: SRT/Wav2Vec2Aligner.py                      │
    │                                                       │
    │  NODE 4 特点:                                        │
    │  ● 输入含 wav2vec2 精确时间戳的 JSON                  │
    │  ● 按语义/停顿重组整句                               │
    │  ● 日语: MeCab (fugashi+ipadic) 分词断句              │
    └──────────────────────────────────────────────────────
                │
                ▼
┌─────────────────────────────────────────────────────────┐
│  翻译管线 (可选)                                        │
│  ─────────────────────────────────────────────────      │
│  5. 翻译  SRT_Translator.py                            │
│     DeepSeek API (deepseek-chat)                        │
│     语义分组 → 批量翻译 → 三级降级 → 人工兜底          │
│     分组策略: 每 500 字符或 8 条为一组                 │
└─────────────────────────────────────────────────────────┘
    │ 翻译结果
    ▼
┌─────────────────────────────────────────────────────────┐
│  6. 语义核对  TranslationVerifier.py                   │
│     跨语言嵌入: paraphrase-multilingual-MiniLM-L12-v2   │
│     原文 vs 译文 余弦相似度 < 0.65 → 标记              │
│     标记后自动带上下文重翻，取相似度更高版本            │
└─────────────────────────────────────────────────────────┘
    │ 核对后的翻译
    ▼
┌─────────────────────────────────────────────────────────┐
│  7. 术语替换  TermReplacer.py                          │
│     词典替换（Minecraft 299 条，可扩展）                │
│     输出: 最终 .srt                                    │
└─────────────────────────────────────────────────────────┘
    │
    ▼
  输出: <name>-ZH_CN-replace.srt
```

## 关键设计决策

### 1. 转录 + 对齐分离

| 阶段 | 工具 | 用途 |
|------|------|------|
| 转录 | faster-whisper | 语音→文本，产物含粗略时间戳 |
| 对齐 | whisperX 剥离的 alignment.py (whisperx_local/) | Wav2Vec2 CTC 强制对齐，精修时间戳至~20ms |

**为什么不用 whisperX 完整包做转录？**
- ctranslate2==4.4.0 与 Python 3.14 不兼容
- PyAnnote VAD 在 CPU PyTorch 2.8 上报 dtype 崩
- `--no-deps` 安装后缺 pyannote、nltk 等运行时依赖

**为什么对齐要单独剥离？**
- whisperX 的 alignment.py 只依赖 transformers + torch + nltk
- 无需 ctranslate2 / pyannote
- 使用 `whisperx_local/` 作为本地模块，零外部依赖冲突

### 2. 双轨策略（人声分离 + 原始音频）

- **VAD 分段和 faster-whisper 转录**：使用 Demucs 分离后的 `vocals.wav`
  - 干净人声 → 语音检出率更高，识别准确率更好
- **wav2vec2 强制对齐**：使用原始音频（或 vocals.wav，两者采样级一致）
  - wav2vec2 对齐需完整频谱信息，vocals.wav 与原始音频时间轴完全一致
- **验证结论**：Demucs 不产生任何时间偏移，vocals.wav 与原始音频帧级一致

### 3. VAD 阈值 0.25

- Silero VAD 默认阈值 0.5
- 对 ASMR/低音量/弱人声内容不够敏感，漏段严重
- 实验验证 0.20~0.30 可显著提升覆盖，0.25 为平衡点
- 参数可通过 `vad_threshold` 覆盖

### 4. 三级降级翻译兜底

| 级别 | 策略 | 适用场景 |
|------|------|----------|
| 1 | 批量翻译（8条/组） | 正常流程 |
| 2 | 单条翻译 | 批量翻译失败时逐条重试 |
| 3 | 人工兜底 | 单条也失败时输出待翻译文件，人工填写后自动合并 |

### 5. 跨语言嵌入语义核对

- 使用 `paraphrase-multilingual-MiniLM-L12-v2` 直接比较原文与译文
- 跳过本地 MT 步骤（`opus-mt-ja-zh` 在中国镜像上不存在）
- 日语原文和中文译文在同一向量空间直接比较
- 低于 0.65 时自动触发带上下文的重新翻译
- 两版本取相似度高者，两次都低于阈值则标注"建议人工复核"

### 6. 自动重新翻译机制

- 不随意调阈值（Sir 明确指示）
- 被标记的字幕自动收集前后各 2 条作为上下文
- 调用 DeepSeek 重新翻译
- 两版取相似度更高者
- 测试数据：129 条中 10 条触发重翻，5/10 质量提升

### 7. 定点识别 TargetedRecognizer

- 对标记的字幕从 WAV 中提取对应音频段
- 使用 faster-whisper 重新转录（不再依赖 whisperX 完整包）
- 编辑距离对比新旧文本
- 用于区分「翻译错误」与「whisper 识别错误」
- 可选: 启动时自动加载 whisperx_local alignment 精修时间戳

### 8. 网络与模型存储

- 自动 `HF_ENDPOINT=https://hf-mirror.com`（仅当未设置时）
- `HF_HOME` 指向 `models/hf_cache/`，所有模型在项目内
- whisperx_local/ 模块剥离自 whisperX 3.2.0，作为代码存在于项目内
- 项目可整体迁移，无需重新下载模型或重新 pip install whisperx

### 9. 音频时长修正 (ADR-001) — C2 缺陷修复

#### 问题背景

OBS 录制的 MP4 文件常出现「容器报告时长(CD) > 音频解码时长(ADD)」的偏差。
根因是 AAC 编码器在末尾写入 padding 帧（约 613 帧零填充），
解码器自动丢弃这些帧，导致 ADD < CD。

**LongTest1 实测**: CD=2441.87s, ADD=2428.40s, 差 +13.48s (+0.55%)

问题分级（MediaValidator 决策树）:

| 缺陷类型 | 现象 | 严重度 | 处理方式 |
|----------|------|--------|----------|
| **C2** | ADD < CD（AAC padding 导致） | minor | aresample=async=1 + -t <CD> |
| **C1** | ADD > CD（视频丢帧） | moderate | 下游比例修正 |
| **A2** | moov/mvhd duration 错误 | minor | 重新 remux |
| **E1** | 文件截断/损坏 | severe | 重新获取源文件 |

#### 三层修复策略

| 优先级 | 方案 | 原理 | 实战验证 |
|--------|------|------|----------|
| **1 (首选)** | `aresample=async=1:first_pts=0` + `-t <CD>` | aresample 在输入耗尽时自动插样本保持 PTS 同步（非静音填充）。`-t <CD>` 让 ffmpeg 输出精确对齐容器时长 | ✅ 偏差从 +13.475s 降至 **+0.010s** |
| 2 (兜底) | 所有 timestamp × CD/ADD | 当无法重新提取音频时做后处理修正 | — |
| 废弃 | VFR→CFR 重编 | 视频重编不改音频采样数，无效 | ❌ |

#### 关键实现细节

**对应的 ffmpeg 命令**:
```bash
ffmpeg -y -i video.mp4 -vn \
    -af "aresample=async=1:first_pts=0" \
    -c:a pcm_s16le -ar 16000 -ac 1 \
    -t 2441.87 \
    output.wav
```

- `aresample=async=1`: 异步重采样，输入耗尽时插入样本保持输出 PTS 连续性
- `first_pts=0`: 输出流首帧从 PTS=0 开始对齐
- **`-t <CD>` 是关键**: 让 ffmpeg 以容器时长而非音频解码时长为标准输出
- **无静音填充**（无 `apad`），仅在采样层做 PTS 保持

**验证方式**:
```bash
ffmpeg -i output.wav  # 读取 Duration 字段
```
理想结果：偏差 < 0.5s

#### 共享函数 `ensure_audio_duration()`

定义在 `MediaValidator.py`，所有上游提取器统一调用此函数：

```python
def ensure_audio_duration(video_path, output_wav, sr=44100, ch=2):
    """
    1. 解析 ffmpeg -i 获取 CD
    2. 若 CD > 0: 直接 aresample=async=1:first_pts=0 + -t <CD> 一次到位
    3. 若 CD <= 0: 裸提取（无修复），日志警告
    4. 验证输出 WAV 时长，偏差应 < 0.5s
    """
```

调用者：
- `VocalSeparator._prepare_audio()` — Demucs 分支
- `AudioSeparator.extract_audio()` — Spleeter 分支
- `extract_subtitles.py` NODE 2 — 主线

#### ffmpeg 路径解析层次

为确保跨环境兼容，`_find_ffmpeg()` 按优先级探测：

```python
1. imageio_ffmpeg.get_ffmpeg_exe()  # ✅ 项目 .venv 内，版本无关
2. .venv/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg*.exe  # 通配符匹配版本号
3. PATH 内 "ffmpeg"
```

`MEDIAINFO` 元数据通过 `stderr` 获取（`ffmpeg -i` 输出到 stderr），
解析 `Duration: HH:MM:SS.mmm` 正则。

#### 验证结论

- `aresample=async=1:first_pts=0` + `-t <CD>` 实测偏差 **0.010s**（LongTest1）
- 跨相关验证：aresample[742s] vs base[738s] = 0.8754（同一段内容被拉伸 0.55%）
- **音频不损失采样精度**，仅做时序对齐
- AED-001 详细决策过程见 `docs/decisions/ADR-001-audio-duration-fix-strategy.md`

### 10. whisperx_local 剥离方案

**目的**: 仅使用 whisperX 的 wav2vec2 对齐功能，不安装完整 whisperX 包。

**来源**: whisperX 3.2.0 的 alignment.py + 必要依赖（audio.py, utils.py, types.py）

**改动**:
- 相对导入 `from .audio` → `from whisperx_local.audio`
- `audio.py` 的 `load_audio()` 调用外部 ffmpeg 不可用 → 改为由调用方传入 float32 numpy 数组
- 删除所有 `transcribe` / `diarize` 相关引用

**依赖**: transformers + torch + numpy + nltk（所有已安装）

**载入时机**: 懒加载（`_init_aligner()`），仅在 NODE 3.5 启用时加载 Wav2Vec2ForCTC 模型

## TTS 语音合成模块（新 🆕）

从 `translate_video.py` 入口，接续字幕提取 + 翻译步骤，执行 TTS 合成 + 视频段处理 + 最终拼接。

### 流程概览

```
输入: 中文 SRT + 原视频 + 背景乐 WAV
        │
        ▼
┌──────────────────────────────────────────────────────┐
│  TtsPipeline.run()                                   │
│                                                        │
│  1. handle_begin_end_silence                          │
│     开头/结尾无人声段 → 直接截取原视频保留背景乐      │
│                                                        │
│  2. 逐个字幕段处理 (for each subtitle)                │
│     ┌─────────────────────────────────────────┐      │
│     │  a. 裁剪视频段 (VideoSegmenter)          │      │
│     │  b. 提取背景乐段 (ffmpeg subprocess)     │      │
│     │  c. TTS 合成 (EdgeTTSEngine)             │      │
│     │  d. 时序对齐 (TimingAdjuster)            │      │
│     │     ├─ ±15% → 调视频速度 (视觉无感)    │      │
│     │     └─ >±15% → 重调 TTS 语速            │      │
│     │  e. 叠加字幕 (CaptionRenderer)           │      │
│     │  f. 混合背景乐 + TTS 音频                │      │
│     │  g. 写出视频段 (.mp4)                   │      │
│     └─────────────────────────────────────────┘      │
│                                                        │
│  3. concat 拼接所有视频段                              │
│     ffmpeg concat demuxer → 最终输出                  │
└──────────────────────────────────────────────────────┘
```

### 模块架构

```
translate_video.py  ← 入口编排，走 4 步
       │
       ├── extract_subtitles.py  ← 子进程调用（步骤 1）
       ├── SRT.SRT_Translator    ← 翻译（步骤 2）
       ├── TTSAdapter            ← 兼容层（步骤 3）
       │       └── TtsPipeline   ← 核心编排
       │               ├── EdgeTTSEngine        ← TTS 合成
       │               ├── TimingAdjuster       ← 时序对齐
       │               │       └── (提取自原 compare_audio_time)
       │               ├── VideoSegmenter       ← 视频裁剪/变速
       │               ├── CaptionRenderer      ← 字幕渲染
       │               ├── OpenVoiceCloner      ← 音色克隆(Noop)
       │               └── ResumeManager        ← 断点续传
       └── ffmpeg concat          ← 拼接（步骤 4）
```

### 核心设计决策

#### 1. Protocol 引擎抽象

```python
class BaseTTSEngine(Protocol):
    def synthesize(self, text: str, output_path: str, rate: str) -> float: ...
```

- 使用 Python Protocol（结构类型），非 ABC
- 任何实现了 `synthesize` 签名的对象均可作为引擎
- 内置 NoopTTSEngine（存空文件，返回 0）用于调试
- 新增后端只需实现该协议，无需改动编排器

#### 2. 两档语速决策 (`speed_tolerance`)

```
diff = (tts_duration - video_duration) / video_duration
if abs(diff) <= speed_tolerance (15%):
    → 微调视频播放速度（视觉影响极小，不额外调用 TTS）
else:
    → 调用 TimingAdjuster 重新合成不同语速版本
        ├─ 在 base_speed ~ max_speed 之间递增语速
        └─ 达 max_speed 仍不够 → 视频变速兜底
```

#### 3. 背景乐独立音轨

- 在 `extract_subtitles.py` NODE 2.5 中提取：`ffmpeg` 降混为 44100Hz 立体声 PCM
- 每个字幕段处理时，截取对应时间段的背景乐
- **禁止使用 `AudioFileClip.subclipped()`** 共享 reader（moviepy 2.x 的 GC 问题）
- 改用子进程 ffmpeg 提取独立 WAV 文件，确保 reader 生命周期隔离

#### 4. 断点续传 (ResumeManager)

- 每处理完一个字幕段，写入 `progress.json`
- 中断后重新运行，自动跳过已处理段
- 状态文件路径：`{output_dir}/progress.json`

### TTS 模块文件布局

```
pipeline/
├── tts_engine.py      # BaseTTSEngine Protocol + EmotionStyle + NoopTTSEngine
├── tts_edge.py        # EdgeTTSEngine（edge-tts 实现，3 重试）
├── tts_timing.py      # TimingAdjuster（从原 compare_audio_time 提取，零行为变化）
├── tts_video.py       # VideoSegmenter（裁剪/变速/背景乐混合）
├── tts_caption.py     # CaptionRenderer（字幕叠加）
├── tts_openvoice.py   # OpenVoiceCloner + NoopCloner
├── tts_pipeline.py    # TtsPipeline（全流程编排）
├── tts_resume.py      # ResumeManager（进度保存/恢复）
├── tts_config.py      # TTSConfig（配置加载）+ parse_srt()
├── tts_adapter.py     # TTSAdapter（兼容旧 SrtTxtToAudio 接口）
└── tests/
    └── test_tts/      # 7 个测试文件，65 个单元测试
```

### 已知限制

1. **OpenVoice 暂为 Noop**：`NoopCloner` 空操作，音色克隆待集成
2. **仅 Edge TTS 可用**：ChatTTS/Cooqui/Azure 引擎待实现
3. **SRT 时间戳质量问题**：`extract_subtitles.py` 生成的 SRT 首条偶有反转时间戳，`parse_srt()` 已自动修正
4. **Windows 路径兼容**：TimingAdjuster 原用 Unix `/` 路径拼接，已改为 `os.path.join`

## 配置参考 (`config/translate.yaml`)

```yaml
translate:
  api_key: '<your-deepseek-api-key>'
  model: deepseek-chat
  source_lang: ja                  # 源语言
  semantic_check: true             # 启用语义核对
  semantic_threshold: 0.65         # 相似度阈值
  temperature: 0.1                 # 翻译稳定度
  max_group_chars: 500             # 每组最大字符数
  max_group_size: 8                # 每组最大字幕条数
  max_retries: 2                   # 最大重试次数
  fallback_to_single: true         # 批量失败→单条
  manual_fallback: true            # 单条失败→人工兜底
  rate_limit:
    min_interval_seconds: 0.5
    requests_per_minute: 20
  terms_dict:
    enabled: true
    default_dict: minecraft.json
    dict_dir: config/terms/
```

## 模块布局 / 文件目录结构

```
Translate_video/
├── extract_subtitles.py        # → 主线编排器（薄层，~200 行）
├── translate_video.py          # → TTS 全流程入口（4 步：提取→翻译→TTS→拼接）🆕
├── pipeline/                   # 主线 + TTS 模块
│   ├── __init__.py
│   ├── utils.py                # 共享工具 (ffmpeg路径、格式化)
│   ├── video_info.py           # NODE 1: 视频信息 + C2 诊断
│   ├── audio.py                # NODE 2: 音频提取/修复
│   ├── transcriber.py          # NODE 3+3.5: VAD→转录→wav2vec2对齐
│   ├── tts_config.py           # TTSConfig 配置 + parse_srt()
│   ├── tts_engine.py           # BaseTTSEngine Protocol + NoopTTSEngine
│   ├── tts_edge.py             # EdgeTTSEngine (edge-tts, 3 retries)
│   ├── tts_timing.py           # TimingAdjuster (时序对齐)
│   ├── tts_video.py            # VideoSegmenter (裁剪/变速/混合)
│   ├── tts_caption.py          # CaptionRenderer (字幕叠加)
│   ├── tts_openvoice.py        # OpenVoiceCloner + NoopCloner
│   ├── tts_pipeline.py         # TtsPipeline (全流程编排)
│   ├── tts_resume.py           # ResumeManager (断点续传)
│   └── tts_adapter.py          # TTSAdapter (旧接口包装)
├── SRT/                        # 字幕工具集
│   ├── __init__.py             # 模块列表
│   ├── MediaValidator.py       # C2 缺陷诊断 + ensure_audio_duration
│   ├── VAD_Segmenter.py        # Silero VAD 分段
│   ├── Json_Convert_Srt.py     # JSON → SRT (MeCab 可选)
│   ├── SRT_Translator.py       # DeepSeek API 翻译
│   ├── TranslationVerifier.py  # 跨语言语义相似度核验
│   ├── TermReplacer.py         # 技术术语字典替换
│   ├── TargetedRecognizer.py   # 定点重转录验证
│   ├── Wav2Vec2Aligner.py      # wav2vec2 对齐封装（调用 whisperx_local）
│   ├── VocalSeparator.py       # Demucs 人声分离
│   └── SRT_Extract.py          # 旧线 (whisperX 完整包, 参考)
├── whisperx_local/             # 从 whisperX 剥离的对齐模块
│   ├── __init__.py
│   ├── alignment.py            # load_align_model + align
│   ├── audio.py                # 工具函数
│   ├── utils.py                # 工具函数
│   └── types.py                # 类型定义
├── config/                     # 配置
│   ├── translate.yaml          # 翻译配置 (API key, 策略)
│   └── terms/                  # 术语词典
├── docs/                       # 设计文档
│   └── decisions/
│       └── ADR-001-audio-duration-fix-strategy.md
└── models/                     # 本地模型缓存
    ├── whisper/
    │   └── Systran/faster-whisper-{size}/  (461MB, 由 faster-whisper 自动下载)
    ├── alignment/              # Wav2Vec2 模型 (HF 缓存)
    ├── vad/                    # Silero VAD (flat files)
    └── hf_cache/               # 其他 HF 模型缓存
```

## 模型存储布局

```
Translate_video/models/
├── whisper/
│   └── Systran/faster-whisper-small/     (461MB, faster-whisper 原生格式)
├── alignment/ (HF hub 缓存目录)
│   └── models--jonatasgrosman--wav2vec2-large-xlsr-53-japanese/  (1.2GB)
├── vad/
│   └── snakers4/silero-vad/              (3MB, flat files)
└── hf_cache/
    └── hub/models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2/  (470MB)
```

注: whisperx_local/ 是代码（~10KB），不是模型。Wav2Vec2 模型运行时自动从 HF 镜像下载缓存。

## 已知问题

1. **whisperX 旧线 SRT_Extract.py 已废弃**
   - 因 ctranslate2==4.4.0 与 Python 3.14 不兼容
   - whisperX 的 pyannote VAD 在 CPU 上 dtype 崩溃
   - 保留仅作参考，所有新开发走 extract_subtitles.py 主线

2. **wav2vec2 对齐速度**
   - 每个 segment 独立跑 Wav2Vec2 推理，CPU 上 ~0.8s/段
   - 186 段约需 2.5 分钟（不包含模型加载 ~8s）
   - 可考虑批处理优化，目前按 segment 逐个处理

3. **`_load_audio_segment` 中 `int()` 截断误差**
   - `int(start_s * sr)` 在长视频中可能累积
   - 建议改用 `round()` 修复

4. **whisper 对拟声词识别不稳定**
   - 同一音频不同批次可能得到不同结果
   - 弱音频段可能产生幻觉

5. **wav2vec2 对齐仅在指定 `--lang` 时启用**
   - auto-detect 语言时不启用（对齐需要明确语言代码）
   - 若自动检测出日语后仍需对齐，需手动加 `--lang ja`
