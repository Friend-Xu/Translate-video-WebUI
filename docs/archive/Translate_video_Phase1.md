# Phase 1 — VocalSeparator 完成

## 完成的工作

### 文件
- **新增** `SRT/VocalSeparator.py` — Demucs 人声分离封装（Python API 版）

### 设计决策
- **使用 Demucs Python API 而非 CLI 子进程**（`get_model_from_args` + `apply_model`）
  - 绕过 `separate.main()` 内部对 `ffprobe` 的依赖（我们只有 ffmpeg，没有 ffprobe）
  - 用 `torchaudio.load()` + `soundfile` backend 加载音频
  - 用 demucs `apply_model()` 推理
  - 用 demucs `save_audio()` 保存结果
- **缓存检测**：检查 `{out_dir}/{model}/{track}/vocals.wav` 是否存在且非空
- **视频→音频提取**：通过 ffmpeg 子进程（需要 ffmpeg 在 PATH 上）

### 性能基准（htdemucs, CPU only, 41s 音频）
- 模型加载：~0.3s（缓存后）
- 推理（7s segment）：~13s
- 实时率：~3x（比 whisperX 转录的 6x 快）
- 输出：~14MB 每个文件（float32 WAV, 44.1kHz stereo）

### 安装变更
- 新增依赖：`soundfile`（为 torchaudio 提供 WAV 读取 backend）

### 验证结果
- 人声 RMS 0.107 > 背景 RMS 0.04，分离有效 ✅
- 缓存检测即时跳过 ✅
- force 重新分离正常 ✅

## 下一步
Phase 2: VAD_Segmenter.py（VAD 语音段检测）
Phase 3: SRT_Extract.py 重构（whisperX 转录）
