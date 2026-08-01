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
    │  │           启用: --lang zh 参数              │      │
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
    │  ● 启用: --lang zh（auto-detect 时不启用）           │
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
2. **TTS 引擎状态**：Edge TTS（默认）、ChatTTS 本地引擎、CosyVoice 跨语言引擎、IndexTTS 引擎均已可用
3. **SRT 时间戳质量问题**：`extract_subtitles.py` 生成的 SRT 首条偶有反转时间戳，`parse_srt()` 已自动修正
4. **Windows 路径兼容**：TimingAdjuster 原用 Unix `/` 路径拼接，已改为 `os.path.join`

## core/ — Adapter-Pass-Gate 三层架构（新 🆕）

`core/` 是新一代 pipeline 引擎，采用 **Adapter-Pass-Gate** 三层分离架构，
目标：类型安全、可独立测试、可线性编排的全流程引擎。

### 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        PassManager                               │
│  按 depends_on DAG 拓扑排序，线性执行 16 个 Pass                  │
└─────────────────────────────────────────────────────────────────┘
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│   Adapter 层   │   │    Pass 层     │   │    Gate 层     │
│  (14 adapters) │   │  (16 passes)   │   │   (2 gates)    │
│                │   │                │   │                │
│ • Whisper      │   │ • ASR          │   │ • TextGate     │
│ • Wav2Vec2     │   │ • Speaker      │   │   A/C/B 决策   │
│ • PyAnnote     │   │ • Translation  │   │ • EmotionGate  │
│ • ChatTTS      │   │ • TTS ×5       │   │   E1/E2/E3     │
│ • CosyVoice    │   │ • Emotion      │   │                │
│ • IndexTTS     │   │ • Quality      │   │                │
│ • OpenVoice    │   │ • AudioPre     │   │                │
│ • EdgeTTS      │   │ • SRTExport    │   │                │
│ • MiniLM       │   │ • SemanticMerge│   │                │
│ • PPL          │   │ • ASRToIR      │   │                │
│ • EmotionRecog │   │                │   │                │
└───────────────┘   └───────────────┘   └───────────────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
                             ▼
              ┌──────────────────────────┐
              │     TimelineProjectState  │
              │  ┌──────────────────────┐ │
              │  │  IR (immutable)      │ │
              │  │  events[], speakers{}│ │
              │  ├──────────────────────┤ │
              │  │  EventState × N      │ │
              │  │  _data (9 slots)     │ │
              │  │  patches[]           │ │
              │  ├──────────────────────┤ │
              │  │  Global patches[]    │ │
              │  └──────────────────────┘ │
              └──────────────────────────┘
                             │
                             ▼
              ┌──────────────────────────┐
              │    SynthesisEngine        │
              │  5-layer render:          │
              │  L1 raw IR → L2 deriv.   │
              │  → L3 patches →          │
              │  L4 speakers → L5 output │
              └──────────────────────────┘
```

### Adapter 层 — 外部引擎封装

每个 Adapter 封装一个外部引擎（Whisper, ChatTTS, MiniLM 等），
统一返回 `Patch` 对象写入 `TimelineProjectState`。

**14 个 Adapter：**

| Adapter | 封装引擎 | 输出 Patch |
|---------|---------|-----------|
| `MediaValidatorAdapter` | MediaValidator | AUDIO_DEFECT_DIAGNOSIS |
| `DemucsAdapter` | Demucs htdemucs | AUDIO_SEPARATION |
| `VADBoundaryAdapter` | Silero VAD | VAD_BOUNDARY |
| `WhisperAdapter` | faster-whisper (CTranslate2) | UPDATE_TRANSCRIPTION |
| `Wav2Vec2Adapter` | Wav2Vec2ForCTC | REFINE_ALIGNMENT |
| `PyAnnoteAdapter` | pyannote.audio | UPDATE_SPEAKER |
| `ChatTTSAdapter` | ChatTTS subprocess | UPDATE_TTS |
| `CosyVoiceAdapter` | CosyVoice subprocess | UPDATE_TTS |
| `IndexTTSAdapter` | IndexTTS subprocess | UPDATE_TTS |
| `OpenVoiceAdapter` | OpenVoiceCloner | UPDATE_TTS (fallback) |
| `EdgeTTSAdapter` | EdgeTTSEngine | UPDATE_TTS (last resort) |
| `MiniLMAdapter` | SentenceTransformer | ANNOTATE (similarity) |
| `PPLAdapter` | GPT-2 PPL | ANNOTATE (ppl_ratio) |
| `EmotionRecognizerAdapter` | EmotionModeler + funasr | UPDATE_EMOTION |

### Pass 层 — 编排标准操作

每个 Pass 是一个 `apply(state) → state` 函数，通过 `depends_on` 声明依赖，
`PassManager` 自动拓扑排序执行。

**16 个 Pass：**

| Pass | 依赖 | 功能 |
|------|------|------|
| `AudioPreprocessCompositePass` | — | MediaValidator + Demucs + VAD |
| `ASRToIRPass` | — | ASR 输出 → Timeline IR |
| `ASRCompositePass` | audio_preprocess | Whisper + Wav2Vec2 → Patch |
| `SpeakerCompositePass` | asr_composite | PyAnnote → Speaker Patch |
| `LLMTranslationPass` | asr_to_ir | LLM 翻译 → UPDATE_TRANSLATION |
| `TranslationQualityPass` | llm_translation | TranslationScorer + TextGate |
| `EmotionCompositePass` | speaker_composite, llm_translation | EmotionRecognizer + EmotionGate |
| `TTSCompositePass` | llm_translation | ChatTTS → UPDATE_TTS |
| `CosyVoiceCompositePass` | llm_translation | CosyVoice → UPDATE_TTS |
| `IndexTTSCompositePass` | llm_translation | IndexTTS → UPDATE_TTS |
| `OpenVoiceCompositePass` | tts_composite | OpenVoice fallback |
| `EdgeTTSCompositePass` | openvoice_composite | EdgeTTS last resort |
| `SemanticMergePass` | asr_to_ir | 语义合并相邻 segment |
| `ValidationCompositePass` | (any) | Schema + 跨槽位约束校验 |
| `SRTExportPass` | (末端) | State → SRT 文件 |

### Gate 层 — 质量门控

**TextGate** (Ch14) — 翻译质量门控：

```
A 门: new_sim < old_sim - sim_drop_limit → reject (退化)
C 门: new_ppl_ratio > old_ppl_ratio → reject (流畅度下降)
B 门: new_sim - old_sim > 0.05 → accept (质量提升)
      否则 → reject (无提升)

Joint Formula 模式:
  score = 0.4 × (1 - PPL_ratio_norm) + 0.4 × sim_gain + 0.2 × (1 - length_err)
  score > 0.5 → accept
```

**EmotionGate** (Ch15) — 情感一致性门控：

```
E2 (硬门槛): current.confidence < 0.3 → review
E1 (连续性): |current.intensity - previous.intensity| > 0.7 → repair
E3 (说话人): current.distance(speaker_baseline) > 1.5 → repair
```

### 引擎层 — 工作流编排与事件系统

`core/engine/` 是 Pass 之上的编排层，管理 Workflow 生命周期、事件总线和进度报告。

#### WorkflowOrchestrator — 6 阶段生命周期

`WorkflowOrchestrator` 管理完整的 6 阶段流水线，集成 Gate 路由：

```
WorkflowStage = LOAD → EXTRACT → TRANSLATE → VALIDATE → TTS → EXPORT

每个 Stage:
  ├── StageExecutor.run() → PassManager.run_with_diff(stage_passes)
  ├── 输出 ProgressReport + RuntimeEvent
  └── Gate 路由决策 (A/B/C):
        A → 下一 Stage
        B → 暂停等待人工审核
        C → 重试当前 Stage（有上限）
```

**关键方法：**

| 方法 | 功能 |
|------|------|
| `run(video_path, policy)` | 启动完整流水线 |
| `resume(action)` | 从 Gate B 暂停恢复，可跳过/重试/接受 |
| `pause()` | 手动暂停，保存状态 |
| `cancel()` | 取消运行，标记 FAILED |

#### EventBus + RuntimeEvent — 发布/订阅系统

```
Adapter/Pass/Gate → emit(RuntimeEvent) → EventBus
                                            ├── ProgressCallback（前端 SSE）
                                            ├── StructuredLogger（磁盘日志）
                                            └── MetricsCollector（性能指标）
```

**22 种 RuntimeEventType：**

| 类别 | 事件 |
|------|------|
| Workflow | WORKFLOW_STARTED, WORKFLOW_COMPLETED, WORKFLOW_FAILED, WORKFLOW_PAUSED, WORKFLOW_CANCELLED |
| Stage | STAGE_STARTED, STAGE_COMPLETED, STAGE_FAILED |
| Pass | PASS_STARTED, PASS_COMPLETED, PASS_FAILED |
| Patch | PATCH_APPLIED, PATCH_REJECTED, PATCH_ROLLBACK |
| Gate | GATE_PASSED, GATE_REJECTED, GATE_PAUSED |
| Config | CONFIG_OVERRIDE_APPLIED, CONFIG_RESET |
| Audit | PROGRESS_REPORT, METRICS_UPDATE |

#### PassFactory — 基于闭包的工厂

`pass_factory.py` 将 Pass 名称映射到实例，28 个别名：

```python
AVAILABLE_PASS_NAMES = {  # 28 aliases
    "asr":           ASRCompositePass,
    "tts_chattts":   TTSCompositePass,
    "tts_cosyvoice": CosyVoiceCompositePass,
    "tts_indextts":  IndexTTSCompositePass,
    ...
}
create_pass_factory(video_path, translate_fn, ...) → factory_fn
```

`_RUNTIME_ARGS` 管理 CLI 注入的运行时参数（video_path, output_dir, engine 等）。

#### 引擎层模块布局

```
core/engine/
├── pass_base.py              # TimelinePass 抽象基类
├── pass_manager.py           # PassManager — Kahn 拓扑排序
├── pass_factory.py           # create_pass_factory() — 28 aliases + _RUNTIME_ARGS
├── stage_executor.py         # StageExecutor — 单阶段生命周期
├── workflow_orchestrator.py  # WorkflowOrchestrator — 6 阶段 + Gate 路由
├── runtime_event.py          # RuntimeEvent + RuntimeEventType (22 types)
├── event_bus.py              # EventBus — 线程安全单例
└── progress.py               # ProgressReport + StageProgress
```

### Timeline IR v2 — 9 槽位事件状态

`TimelineEventState` 管理 9 个语义槽位，每个槽位惰性初始化为 `dict`：

| 槽位 | 内容 | 写入者 |
|------|------|--------|
| `audio` | 音频路径、VAD 边界 | AudioPreprocess |
| `asr` | 转录文本、词级时间戳 | ASRComposite |
| `speaker` | speaker_id、嵌入向量 | SpeakerComposite |
| `semantic` | 语义分组 | SemanticMerge |
| `translation` | 翻译文本、质量评分 | LLMTranslation + Quality |
| `tts` | TTS 输出路径、时长 | TTS Composite |
| `emotion` | valence/arousal/dominance | EmotionComposite |
| `review` | 人工审校标记 | WebUI |
| `runtime` | 重算标记、版本 | PatchEngine |

**OpCode 枚举** — 20+ 操作码：

```
REPLACE, MERGE, SPLIT, INSERT, DELETE,
UPDATE_TRANSCRIPTION, UPDATE_TRANSLATION, UPDATE_SPEAKER,
UPDATE_TTS, UPDATE_EMOTION, REFINE_ALIGNMENT,
ASSIGN_SPEAKER, MERGE_SPEAKERS, ANNOTATE, ...
```

### Patch Engine (Ch12) — 补丁状态机

`PatchEngine` 是整个 core/ 的运行时核心，将 Patch 应用到 State：

```
Patch.apply(state) → 分发到 handler
  ├── _replace    → target.derivatives.update(value)
  ├── _seg_split  → 创建 2 个新 EventState
  ├── _seg_merge  → 合并 N 个 EventState
  ├── _seg_insert → 创建 1 个新 EventState
  ├── _assign_speaker → 更新 speaker_ref
  ├── _merge_speakers → 重映射 speaker_id
  ├── _annotate   → 写入指定槽位
  └── _propagate  → 批量更新多个 target
```

**配套子系统：**

| 模块 | 功能 |
|------|------|
| `DependencyGraph` | 段间时间依赖图，级联失效检测 |
| `RecomputeEngine` | 增量重算，最小化重处理范围 |
| `ConflictDetector` | OVERWRITE/IDENTITY/TEMPORAL 冲突检测 |
| `ConflictResolver` | 规则优先级 + 置信度仲裁 |
| `RollbackManager` | Patch undo/redo，版本回退 |
| `SnapshotManager` | State 快照，崩溃恢复 |
| `PatchStore` | 三层存储（内存→磁盘→远程） |
| `Reducer` | 确定性重放至指定时间戳 |
| `GateValidator` | 预应用校验（幂等性、置信度、必填字段） |

### 评分器 — 8 个 Scorer

| Scorer | 评估维度 | 输出 |
|--------|---------|------|
| `TranslationScorer` | semantic + fluency + faithfulness + temporal + length | composite ∈ [0,1] |
| `EmotionScorer` | consistency + intensity + speaker_fit + translation_alignment | composite ∈ [0,1] |
| `ASRScorer` | confidence + alignment + coverage | score ∈ [0,1] |
| `TTSScorer` | duration_fit + quality + naturalness | score ∈ [0,1] |
| `CosyVoiceScorer` | duration_fit + cross_lingual + quality | score ∈ [0,1] |
| `IndexTTSScorer` | duration_fit + voice_match + emotion_fit | score ∈ [0,1] |
| `OpenVoiceScorer` | duration_fit + transfer_quality | score ∈ [0,1] |
| `EdgeTTSScorer` | duration_fit + fallback_reason | score ∈ [0,1] |

### 与旧架构关系

```
旧架构: main.py → extract_subtitles.py → SRT_Translator → TtsPipeline
新架构: main.py --use-core → WorkflowOrchestrator → 16 Pass → SynthesisEngine

迁移策略: 渐进，双系统共存。--use-core 默认不启用。
```

### Config 层 — 参数配置体系（v3.0 新增 🆕）

四层对象域 + 三级优先级 + 配置注入，将所有引擎参数从 CLI 扁平化提升为
分层、可覆盖、可追溯的配置系统。详见 `计划开发/工作流参数新架构设计-定稿.md` 第 1 章。

#### 四层对象域

```
┌─────────────────────────────────────────────────────────────┐
│                    ProjectPolicy                            │
│  全局策略：target_lang、quality_profile、default_tts_engine   │
│  作用域：整个项目，所有事件继承                                │
├─────────────────────────────────────────────────────────────┤
│                    WorkflowPolicy                           │
│  工作流路径选择：启用的 Pass 列表、skip_demucs、glossary_mode │
│  作用域：单次工作流运行                                      │
├─────────────────────────────────────────────────────────────┤
│                    EnginePolicy                             │
│  引擎运行方式：model_size、device、compute_type、temperature  │
│  作用域：特定 Adapter，由系统自动检测 + 用户调优               │
├─────────────────────────────────────────────────────────────┤
│                    SegmentRuntimeState                      │
│  事件级运行时决策：event.tts.config.engine=cosyvoice          │
│  作用域：单个事件，最高优先级，覆盖以上三层                     │
└─────────────────────────────────────────────────────────────┘
```

#### 三级配置优先级

```
Event.config  >  Speaker.config  >  Global.config
   (最高)           (中间)            (最低)
```

**关键规则：**
1. **只有显式设定的值才参与覆盖** — `event.asr.config = {"model": "large-v3"}` 只覆盖 model，其余字段继承
2. **深度合并（deep_merge）** — 嵌套对象递归合并，非浅层替换
3. **null = 删除覆盖** — 显式设 null 恢复继承，语义不同于"字段不存在"
4. **差异化存储（delta storage）** — 事件级 config 仅序列化与上级默认值的差异

#### ConfigResolver (`core/runtime/config_resolver.py`)

三级合并引擎，`resolve_event_config(event_id, slot, state)` 按优先级深度合并：
```python
def resolve_event_config(event_id, slot, state) -> dict:
    base = deep_merge(global_config[slot], speaker.config[slot])  # L3+L2
    return deep_merge(base, event.config[slot])                    # +L1
```

`deep_merge(base, override)` 实现了 null 语义：
- `override[key] = null` → 从结果中删除 key（恢复继承）
- 嵌套 dict 递归合并，非 dict 值直接替换
- `serialize_event_config()` 输出差异化存储（仅保存与默认值的差异）

#### SlotLevelDependencyGraph (`core/runtime/slot_dependency.py`)

细粒度脏传播：改变某槽位的特定字段只传播到受影响的下游槽位。
```
audio.config.vad_threshold  →  audio, asr, speaker  (VAD 影响 ASR 分段)
asr.config.model            →  asr                   (只影响 ASR 自身)
tts.config.speed_factor     →  tts                   (只影响 TTS)
translation.config.lang     →  translation           (只影响翻译)
```

#### Config OpCodes

| OpCode | 语义 | 合并方式 |
|--------|------|---------|
| `SET_CONFIG` | 全量替换槽位配置 | 完全替换 |
| `OVERRIDE_CONFIG` | 深度合并部分字段 | deep_merge |
| `RESET_CONFIG` | 恢复继承（删除事件级覆盖） | 移除槽位 config |
| `BATCH_SET_CONFIG` | 批量应用多个槽位配置 | 逐槽位 OVERRIDE |

每个 config patch 通过 `SnapshotManager` 自动记录 `previous_state`（仅变更字段），
支持 undo/redo。`GateValidator` 在 pre-apply 阶段校验 JSON Schema + 跨槽位约束。

#### 跨槽位约束（6 规则）

| 规则ID | 条件 | 约束 | 级别 |
|--------|------|------|------|
| ASR-C01 | language=auto + alignment_enabled=true | alignment 强制中文 | WARN |
| TR-C02 | glossary_mode=CONTEXTUAL + backend=local_dict | local_dict 不支持上下文 | ERROR |
| GATE-C03 | gate_mode=joint_formula + gate_threshold_accept < gate_threshold_reject | 阈值倒挂 | ERROR |
| TTS-C01 | engine=cosyvoice + cosy_lang not in speakers | 语言不在说话人语言集 | WARN |
| EMO-C01 | emotion.enabled=true + text_model=distiluse + fusion_strategy=text_primary | 轻量模型不适合主策略 | WARN |
| ENG-C02 | engine=chattts + chattts_temperature > 1.5 | 高温可能产生不稳定输出 | WARN |

#### 配置注入流程

```
main.py / CLI args
      │
      ▼
GlobalConfig.load("config/global.yaml")  ──→ ProjectPolicy + EnginePolicy
      │
      ▼
WorkflowOrchestrator.run(video, policy)
      │
      ├── 1. 加载 GlobalConfig，derive_engine_policy() 自动检测 GPU
      ├── 2. 每个 Stage 前：ConfigResolver.resolve_event_config(event_id, slot, state)
      ├── 3. 注入 Adapter：adapter.configure(resolved_config)
      └── 4. 用户修改 → InspectorPanel → OVERRIDE_CONFIG patch → GateValidator → PatchEngine
```

### core/ 模块布局

```
core/
├── engine/           # PassManager + PassBase
├── ir/               # Timeline IR (不可变数据模型)
├── adapters/         # 14 个外部引擎封装 (均含 configure() 方法)
├── passes/           # 16 个编排 Pass
├── gates/            # 2 个质量门控
├── scoring/          # 8 个评分器
├── runtime/          # 补丁引擎 + 状态管理 + 配置解析
├── config/           # 全局配置 + Schema 加载 + EnginePolicy 推导 🆕
│   ├── global_config.py    # GlobalConfig + ProjectPolicy + EnginePolicy
│   ├── schema_loader.py    # SchemaLoader — 10 槽位 JSON Schema 校验
│   └── engine_policy.py    # derive_engine_policy() — GPU 自动检测
├── emotion/          # 情感空间
├── speaker/          # 说话人识别
├── tts/              # TTS 控制
└── refiner/          # 翻译结果精炼
    ├── engine.py
    └── prob_builder.py
```

### core/runtime/ 详解

`runtime/` 是 core/ 的核心引擎层，包含完整的状态管理、补丁系统和数据生命周期：

```
runtime/
├── patch.py              # Patch 数据类 + OpCode 枚举 (20+ 操作码)
├── event_state.py        # TimelineEventState — 9 槽位惰性初始化
├── project_state.py      # TimelineProjectState — 项目级状态容器 (+ global_config)
├── patch_engine.py       # PatchEngine — 核心补丁状态机 (14 handler, v3.0)
├── synthesis.py          # SynthesisEngine — 5 层渲染 (IR→衍生→补丁→说话人→输出)
├── index.py              # TimelineIndex — 时间轴索引查询
├── context.py            # RuntimeContext — 统一 CLI/WebUI 参数模型 🆕
├── logging.py            # StructuredLogger + RuntimeLog — 结构化日志 🆕
├── gc.py                 # GCOperation + archive_workspace() — 工作空间 GC 🆕
├── profiler.py           # ProfileResult + profile_workspace() — 性能分析 🆕
├── workspace.py          # WorkspaceResolver — 路径解析 + 生命周期状态机 🆕
├── verify.py             # dual_write_verify() — 结构校验 + 双写一致性 🆕
├── dependency_graph.py   # DependencyGraph — 段间时间依赖图
├── recompute.py          # RecomputeEngine — 局部增量重算
├── conflict.py           # ConflictDetector + ConflictResolver
├── reducer.py            # Reducer — 确定性补丁重放
├── rollback.py           # RollbackManager — undo/redo + 版本回退
├── snapshot.py           # SnapshotManager — State 快照
├── snapshot_manager.py   # SnapshotManager — 配置 undo 增量快照 (v3.0 🆕)
├── slot_dependency.py    # SlotLevelDependencyGraph — 槽位级脏传播 (v3.0 🆕)
├── config_resolver.py    # ConfigResolver — 三级合并引擎 + deep_merge (v3.0 🆕)
├── gate_validator.py     # GateValidator — 预应用校验 + Schema + 跨槽位约束 (v3.0)
├── patch_store.py        # PatchStore — 三层存储 (内存/磁盘/远程)
└── patch_planner.py      # PatchPlanner — 补丁策略规划
```

### 5 层渲染引擎 (SynthesisEngine)

`SynthesisEngine.render(event_state)` 按优先级合成最终输出：

```
Layer 1 (Raw IR):        ir.start, ir.end, ir.speaker_ref, ir.text_ref
Layer 2 (Derivatives):   event_state.derivatives 覆盖 L1
Layer 3 (Patches):       replace 类 patch 覆盖 L2 (按 timestamp 排序)
Layer 4 (Speakers):      注入 speaker 元数据 (name, embedding_ref)
Layer 5 (Output):        合并所有层，输出 dict
```

## timeline/ — Timeline 中间层 + Strangler Fig 迁移系统

`timeline/` 是**新旧 IR 之间的桥接层**，实现 Strangler Fig 渐进迁移模式。
目标是让所有消费端（API、WebUI、CLI）不直接依赖具体 IR 实现，
而是通过统一 Protocol 消费，实现新旧 IR 的透明切换。

### 统一消费协议 (abstract.py)

核心是两个 `@runtime_checkable` Protocol，消费端**只依赖协议，不依赖实现**：

```python
class SegmentView(Protocol):
    id: str; start: float; end: float
    speaker: str | None; text: str; type: str
    @property
    def duration(self) -> float: ...

class TimelineView(Protocol):
    segments: list[SegmentView]
    speakers: list[dict]
    def to_dict(self) -> dict: ...        # → WebUI JSON
    def to_project_ir(self) -> ...: ...   # → 新引擎 TimelineProjectIR
```

### 数据流全景

```
extract_subtitles.py 输出
        │
        ├── transcript.json (旧格式)
        │       │
        │       ▼
        │   timeline/fusion.py
        │   from_extract_result() → TimelineIR (旧 IR)
        │       │
        │       ├─── to_project_ir() → TimelineProjectIR (新 IR) → core/
        │       │
        │       └─── to_dict() → WebUI JSON
        │
        └── project.json (旧格式)
                │
                ▼
           旧架构消费 (SRT_Translator, TtsPipeline)
```

### Fusion 引擎 (fusion.py) — 新旧 IR 数据合并

```
VAD segments  ─┐
ASR words      ─┤
Speaker info   ─┼──→ from_extract_result() → TimelineIR
Alignment      ─┤                                   │
Metadata       ─┘                                   │
                                          ┌─────────┴──────────┐
                                          │                    │
                                    to_project_ir()    from_project_ir()
                                          │                    │
                                          ▼                    ▼
                                  TimelineProjectIR      TimelineIR
                                    (新 core/ IR)        (旧 timeline IR)
```

**关键函数：**

| 函数 | 方向 | 功能 |
|------|------|------|
| `from_extract_result()` | 旧输出 → 旧 IR | VAD/ASR/Speaker 片段 → TimelineIR，自动检测 overlap |
| `to_project_ir()` | 旧 IR → 新 IR | 深度迁移：TimelineSegment → TimelineEventIR，Speaker → SpeakerNodeIR |
| `from_project_ir()` | 新 IR → 旧 IR | 反向迁移：含 derivatives_map 填充 translation/words |

### 双写基础设施 (dual_write.py) — Strangler Fig 核心

补丁同步应用到新旧两套 IR，比对结果确保行为等价：

```
WebUI 用户操作
      │
      ▼
  TimelinePatch (旧 OpCode: MERGE, SPLIT, RETAG_SPEAKER, ...)
      │
      ├──→ apply_patch(old_segments)  → 旧 IR 结果
      │
      ├──→ _map_opcode() → CorePatch  → PatchEngine.apply() → 新 IR 结果
      │
      └──→ _compare(old, new)  → {"status": "ok"|"diff", "diffs": [...]}
```

**OpCode 映射** (dual_write.py:77-84)：

| 旧 OpCode | 新引擎 OpCode |
|-----------|--------------|
| MERGE | merge |
| SPLIT | split |
| RETAG_SPEAKER | replace |
| SET_TRANSLATION | replace |
| RELINK_WORDS | propagate |
| ANNOTATE | replace |

### 灰度路由 (api/timeline.py)

API 层根据配置开关，在 `TimelineView` 协议的两种实现间透明切换：

```
GET /api/timeline/{project_id}
      │
      ├── use_new_ir=True  → NewIRAdapter  → TimelineView (新 core/ IR)
      └── use_new_ir=False → OldIRAdapter  → TimelineView (旧 timeline IR)
```

消费端代码只依赖 `TimelineView` Protocol，不感知底层是哪种 IR。

### 适配器层 (adapters/)

| 适配器 | 功能 |
|--------|------|
| `OldIRAdapter` | 旧 `TimelineIR` → `TimelineView` Protocol |
| `NewIRAdapter` | 新 `TimelineProjectState` → `TimelineView` Protocol |
| `speaker.py` | Speaker 数据在新旧格式间的映射 |

### UI 适配器 (ui_adapter/mapper.py)

将 IR 数据映射为前端 Zustand store 消费的格式：

```
TimelineView.to_dict() → mapper → {
    events: TimelineEvent[],    # EventBlock 直接渲染
    speakers: SpeakerInfo[],    # SpeakerReviewPanel 使用
    patches: PatchDraft[],      # PatchManagementView 使用
}
```

### 迁移配置 (config.py)

```python
# 灰度开关
USE_NEW_IR = os.getenv("USE_NEW_IR", "false").lower() == "true"

# 双写开关
DUAL_WRITE_ENABLED = True  # 新旧同时写入, 差异仅记录不阻断
```

### 补丁与恢复系统

```
timeline/patch/
├── model.py      # TimelinePatch — OpCode + payload + targets
├── opcode.py     # OpCode 枚举 (MERGE, SPLIT, RETAG_SPEAKER, SET_TRANSLATION, ...)
├── apply.py      # apply_patch() — 基于索引的语义级补丁应用
├── conflict.py   # 冲突检测
└── planner.py    # 补丁规划

timeline/recovery/
├── graph.py      # 补丁依赖图
├── replay.py     # 确定性重放到指定检查点
└── snapshot.py   # 时间轴状态快照

timeline/rules/
└── extractor.py  # 从补丁历史中提取规则 (speaker 偏好、分段模式)

timeline/safety/
└── guard.py      # 补丁安全边界 (禁止删除全部 segment、禁止负时间等)

timeline/scorer/
└── scorer.py     # AI 补丁质量评分
```

### 新旧 IR 对比

| 维度 | 旧 IR (timeline/ir.py) | 新 IR (core/ir/) |
|------|----------------------|-------------------|
| 核心类型 | TimelineSegment (mutable dataclass) | TimelineEventIR (frozen dataclass) |
| 状态管理 | 直接修改 segment 字段 | Patch + EventState 9 槽位 |
| 说话人 | speaker_map: dict | SpeakerNodeIR (frozen) |
| 版本 | "1.0" 字符串 | Version 系统 (MAJOR.MINOR) |
| OpCode | 自定义字符串 | OpCode 枚举 (20+ 成员) |
| 可逆性 | 无内置回滚 | RollbackManager + SnapshotManager |

### 目录布局

```
timeline/
├── abstract.py          # TimelineView / SegmentView Protocol
├── ir.py                # 旧版 TimelineIR + TimelineSegment
├── schema.py            # JSON Schema 定义 + 结构校验
├── fusion.py            # 新旧 IR 双向迁移 (from_extract_result / to_project_ir / from_project_ir)
├── dual_write.py        # 双写: 补丁同步应用到新旧 IR + 结果比对
├── config.py            # 灰度开关 (USE_NEW_IR, DUAL_WRITE_ENABLED)
├── io.py                # 文件 I/O
├── api/
│   └── timeline.py      # API 灰度路由
├── adapters/
│   ├── old_ir_adapter.py    # 旧 IR → TimelineView Protocol
│   ├── new_ir_adapter.py    # 新 IR → TimelineView Protocol
│   └── speaker.py           # Speaker 映射适配器
├── patch/
│   ├── model.py         # TimelinePatch 模型
│   ├── opcode.py        # OpCode 枚举
│   ├── apply.py         # 补丁应用引擎
│   ├── conflict.py      # 冲突检测
│   └── planner.py       # 补丁规划
├── recovery/
│   ├── graph.py         # 依赖图
│   ├── replay.py        # 确定性重放
│   └── snapshot.py      # 快照
├── rules/
│   └── extractor.py     # 规则特征提取
├── safety/
│   └── guard.py         # 安全边界守卫
├── scorer/
│   └── scorer.py        # AI 补丁评分
├── speaker/
│   └── model.py         # 说话人模型
└── ui_adapter/
    ├── mapper.py        # IR → 前端 Zustand store 映射
    └── patch_factory.py # 前端操作 → Patch 对象工厂 🆕

## schemas/ — JSON Schema 数据规范

```
schemas/
├── timeline.schema.json         # Timeline IR Schema
├── export_config.schema.json    # 导出配置 Schema
├── patch_log.schema.json        # 补丁日志 Schema (v3.0)
├── speaker_map.schema.json      # 说话人映射 Schema (v3.0)
└── ir_v2/                       # 槽位级 JSON Schema (v3.0 🆕)
    ├── audio_config.schema.json          # 音频预处理参数
    ├── asr_config.schema.json            # ASR 引擎参数
    ├── speaker_config.schema.json        # 说话人识别参数
    ├── semantic_config.schema.json       # 语义分析参数
    ├── translation_config.schema.json    # 翻译引擎参数
    ├── tts_config_routing.schema.json       # TTS 路由参数
    ├── tts_cosyvoice.schema.json         # CosyVoice 专属参数
    ├── tts_chattts.schema.json           # ChatTTS 专属参数
    ├── tts_edge.schema.json              # Edge TTS 专属参数
    └── emotion_config.schema.json        # 情感控制参数
```

所有 ir_v2 Schema 均为 JSON Schema Draft-07，由 `SchemaLoader` 加载校验。

## core/ constants, model, speaker, emotion, tts 子系统

### core/constants/ — 命名注册表

`naming.py` 提供枚举化的 Adapter/Pass/Gate 注册表，确保跨模块引用一致：

```python
class AdapterRegistry(enum.Enum):
    WHISPER = "whisper"
    CHATTTS = "chattts"
    COSYVOICE = "cosyvoice"
    ...

class PassRegistry(enum.Enum):
    ASR_COMPOSITE = "asr_composite"
    LLM_TRANSLATION = "llm_translation"
    ...

def resolve_adapter(name: str) -> type: ...
def resolve_pass(name: str) -> type: ...
```

### core/model/ — 模型注册与路径管理

`registry.py` 管理所有外部模型的下载、缓存和路径解析：

```
ModelEntry(name, hf_repo, local_dir, version)
    │
    ▼
ModelRegistry
    ├── get_model_path(name) → Path
    ├── require_model(name)  → 自动下载
    └── list_models()        → list[ModelEntry]
```

所有模型通过 HF_ENDPOINT 下载到 `models/` 目录，确保项目可整体迁移。

### core/speaker/ — 说话人识别子系统

```
core/speaker/
├── embedding.py    # SpeakerEmbeddingExtractor — 说话人嵌入提取
├── clustering.py   # SpeakerClustering + ClusterResult — 聚类算法
├── drift.py        # SpeakerDriftDetector + DriftCandidate — 说话人漂移检测
└── voice_memory.py # VoiceMemoryIndex + VoicePrototype + VoiceInstance + VoiceAsset
                    # 增量构建说话人音色档案，支持跨段匹配
```

**VoiceMemoryIndex** 是核心类型——为每个说话人维护 VoicePrototype（聚合嵌入），
每个原型关联多个 VoiceInstance（具体音频段的嵌入），支持增量更新和跨视频回忆。

### core/emotion/ — 情感控制子系统

```
core/emotion/
├── emotion_space.py       # EmotionVector — VAD 三维情感空间
├── alignment_checker.py   # EmotionAlignmentChecker — 翻译情感一致性
└── tts_router.py          # EmotionTTSRouter + TTSRoute — 情感驱动的 TTS 路由
```

### core/tts/ — TTS 控制子系统

```
core/tts/
├── duration_control.py    # DurationController + duration_fit_score()
├── cosyvoice_duration.py  # CosyVoiceDurationController — 跨语言时长预估
├── cross_lingual.py       # CrossLingualProcessor — 跨语言文本预处理
├── emotion.py             # EmotionModeler — TTS 情感注入
├── fallback_decider.py    # FallbackDecider + FallbackDecision — 引擎降级决策
└── index_emotion.py       # EmotionVectorMapper — IndexTTS 情感向量映射
```

## core/refiner/ — 翻译结果精炼（续）

```
core/refiner/
├── engine.py            # RefinerEngine — 翻译后处理
└── prob_builder.py      # ProblemBuilder — 问题定位
```

## 新旧架构入口对照

```
旧架构 (默认):
  main.py
    ├── extract_subtitles.py (子进程)  → NODE 1~4 → SRT
    ├── SRT.SRT_Translator            → 翻译
    └── TtsPipeline                   → TTS + 合并

新架构 CLI (tvw.py):
  tvw run <video> --lang zh
    ├── tvw inspect <workspace>       → 工作空间状态检查
    ├── tvw stage <workspace> --stage TTS
    │       → 单阶段执行 (LOAD/EXTRACT/TRANSLATE/VALIDATE/TTS/EXPORT)
    ├── tvw validate <workspace>      → 校验工作空间一致性
    ├── tvw export <workspace> --format srt  → 导出最终产物
    ├── tvw benchmark <workspace>     → 性能基准测试
    ├── tvw profile <workspace>       → 工作空间 Profiling
    └── tvw gc <workspace>            → 工作空间清理/归档

核心入口 (tvw.py run --use-core):
  tvw.py --use-core
    └── WorkflowOrchestrator
          ├── WorkflowPolicy         → 统一配置
          ├── 6 阶段编排 (LOAD→EXTRACT→TRANSLATE→VALIDATE→TTS→EXPORT)
          ├── PassManager.run()      → 16 Pass 线性执行
          └── SynthesisEngine        → 5 层渲染输出

WebUI 入口 (GUI/server.py):
  POST /api/core/pipeline/run        → WorkflowOrchestrator (新架构)
  POST /api/pipeline/run             → main.py subprocess (旧架构)

双写 (transitional):
  extract_subtitles.py 同时输出
    ├── 旧格式 (project.json + SRT)  → 旧架构可消费
    └── 新格式 (TimelineIR JSON)     → core/ 可消费
```

## 配置参考 (`config/translate.yaml`)

```yaml
translate:
  api_key: '<your-deepseek-api-key>'
  model: deepseek-chat
  source_lang: zh                  # 源语言
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
├── tvw.py                        # → 统一 CLI Runtime（8 命令：run/inspect/stage/validate/export/benchmark/profile/gc）🆕
├── main.py                       # → 旧架构主入口（extract→translate→TTS）
├── extract_subtitles.py          # → 主线编排器（薄层，~200 行）
├── translate_video.py            # → TTS 全流程入口（4 步：提取→翻译→TTS→拼接）
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
├── openvoice_cli/               # OpenVoice TTS CLI（vendored，8 .py 文件）🆕
│   ├── attentions.py            # 注意力机制
│   ├── commons.py               # 共享组件
│   ├── models.py                # 模型定义
│   ├── modules.py               # 网络模块
│   ├── transforms.py            # 音频变换
│   ├── mel_processing.py        # Mel 频谱处理
│   ├── downloader.py            # 模型下载
│   └── utils.py                 # 工具函数
└── models/                     # 本地模型缓存
    ├── whisper/
    │   └── Systran/faster-whisper-{size}/  (461MB, 由 faster-whisper 自动下载)
    ├── alignment/              # Wav2Vec2 模型 (HF 缓存)
    ├── vad/                    # Silero VAD (flat files)
    └── hf_cache/               # 其他 HF 模型缓存
```

## 工作空间目录结构（6 子目录）

Pipeline 为每个输入视频创建结构化工作空间：

```
{video_dir}/{stem}_project/
├── project.json            ← 清单：跟踪阶段进度 + 输出文件 + RuntimeState
├── pipeline.log            ← 结构化日志（SSE 流式传输）
├── 01_extract/             ← source.srt, transcript.json, audio.wav, vocals.wav
├── 02_translate/           ← machine.srt, translate-log.json, quality_report.json
├── 03_speaker/             ← speaker_diarization.json, voice_profiles/  🆕
├── 04_patch/               ← timeline_patches.json (补丁历史)  🆕
├── 05_tts/                 ← TTS 音频段 + 视频片段
└── 06_export/              ← dubbed.mp4 (最终输出)

生命周期状态:
  draft → processing → reviewable → frozen → archived
```

相比旧 4 目录布局（01_extract/02_translate/03_tts/04_output），
新布局新增 `03_speaker/`（说话人数据）和 `04_patch/`（补丁日志），
`06_export/` 替代 `04_output/`。

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

## WebUI — 参数配置面板与 Config API（v3.0 🆕）

### InspectorPanel — 7 区手风琴组件

`GUI/components/InspectorPanel.tsx`（170 行）提供事件级参数检查与覆盖，
7 个可折叠区域覆盖全部 9 语义槽位中的可配置参数：

| 区域 | 控件数 | 关键参数 |
|------|--------|---------|
| **Audio Preprocess** | 5 | skip_demucs, demucs_model, vad_threshold, silence_handling, loudness_compensation |
| **ASR Transcription** | 3 | model (tiny→large-v3), language, alignment_enabled |
| **Speaker** | 5 | clustering_threshold, clustering_method, min/max_speakers, gender |
| **Translation & Gate** | 7 | lang, backend, glossary_mode, gate_mode, gate_threshold_accept/reject |
| **TTS Synthesis** | 5+ | engine, voice_gender, speed_factor, timing_adaptive + 引擎专属子面板 |
| **Emotion Control** | 8 | enabled, fusion_strategy, audio/text_weight, text_model, EmotionGate E1/E2/E3 |
| **Review** | 1 | force_accept |

**引擎专属动态子面板：** TTS 区域根据所选引擎（chattts/cosyvoice/edge）动态显示不同控件。
- CosyVoice: model_version, target_lang, num_norm, fp16
- ChatTTS: speaker_seed, temperature, top_k, top_p, emotion_injection
- Edge TTS: voice_name, pitch, volume

每个字段显示**继承来源 Chip**（Event/Speaker/Global），被覆盖的字段显示**恢复按钮**。
Slider/Number 类型通过 `useConfigInspector` hook 实现 300ms debounce，
Select/Toggle 类型即时发送。

### Config API 端点 (`GUI/server.py`)

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/timeline/config/apply` | POST | 应用单个 ConfigChange（OVERRIDE_CONFIG patch） |
| `/api/timeline/config/resolve` | GET | 获取事件的三级合并后最终配置 |
| `/api/config/slots` | GET | 列出所有可配置槽位及其 Schema |

### useConfigInspector Hook (`GUI/hooks/useConfigInspector.ts`)

```typescript
const { config, loading, handleConfigChange, handleResetField, handleResetSlot, handlePreviewTTS }
  = useConfigInspector(eventId);
```

- `fetchConfig` — 并行加载全部 7 槽位的 resolve 结果
- `handleConfigChange(slot, field, value)` — number 类型 300ms debounce，其他即时发送
- `handleResetField(slot, field)` — 发送 RESET_CONFIG 恢复继承
- `handleResetSlot(slot)` — 批量重置整个槽位
- `handlePreviewTTS()` — 调用 TTS 引擎生成预览音频

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
   - 若自动检测出中文后仍需对齐，需手动加 `--lang zh`
