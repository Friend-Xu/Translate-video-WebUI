# Translate_video Phase 0 完成

## 时间
2026-04-24 16:37-16:50

## 已完成

### 环境安装
- `faster-whisper==1.2.1` ✅
- `demucs==4.0.1` ✅
- `torchaudio==2.11.0` ✅
- `transformers==5.6.0` ✅
- `soundfile` / `librosa` ✅

### 镜像配置
- PyPI: `https://mirrors.aliyun.com/pypi/simple/`（阿里云镜像）
- HuggingFace: `https://hf-mirror.com`（环境变量 `HF_ENDPOINT`）

### 验证结果
1. ✅ **faster-whisper small 模型加载** — CPU 1.5s（int8 量化）
2. ✅ **faster-whisper 实际转录** — 15s 音频 0.1s 完成，识别为英文，置信度 100%
3. ✅ **wav2vec2 对齐依赖** — `transformers` + `torchaudio` 可用
4. ✅ **demucs 导入** — 模块正常（需实际音频测试分离）

### 注意点
- **whisperx 不兼容 Python 3.14**：它锁死 `ctranslate2==4.4.0` 但对应版本没有 3.14 的 wheel。改用 `faster-whisper`（whisperx 底层依赖）替代，对齐用 `transformers` 的 `Wav2Vec2ForCTC`
- **ffmpeg 不在 PATH**：通过 `imageio_ffmpeg.get_ffmpeg_exe()` 获取 bundle 路径
- **Python 3.14.4**：最新版，大部分包已有 wheel

## 下一步
Phase 1: 创建 `SRT/VocalSeparator.py` — 封装 demucs 人声分离
