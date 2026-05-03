# Translate_video Phase 0 完成 - 强制使用 whisperX

## 时间
2026-04-24 16:41-17:05

## 关键决策
- **强制使用 whisperX**（Sir 指定），替代之前做的 faster-whisper 方案
- 由于 whisperX 3.8.5 要求 `requires_python: <3.14, >=3.10`，系统 Python 3.14 不兼容
- **新建 Python 3.11.9 venv** 专用于此项目

## 虚拟环境
- 路径：`C:\SoftWare\OpenClaw\WorkSpace\Translate_video\.venv`
- Python 3.11.9（从华为云镜像下载安装到 `C:\Python311`）

## 已验证
| 组件 | 状态 | 明细 |
|------|------|------|
| **whisperX 3.8.5** | ✅ | 导入、转录均正常 |
| **faster-whisper 1.2.1** | ✅ | whisperX 自带依赖 |
| **wav2vec2 对齐** | ✅ | 词级时间戳，30s 音频对齐仅 1.4s |
| **demucs htdemucs** | ✅ | 模型加载 2.5s，81MB checkpoint |
| **ctranslate2 4.7.1** | ✅ | Python 3.11 兼容 |
| **torch 2.8.0** | ✅ | CPU-only, 241MB |
| **pyannote-audio 4.0.4** | ✅ | 含 VAD 能力 |

## 性能基准（CPU, small 模型, int8）
- 模型加载：~6.8s
- 30s 音频转录：~4.9s
- wav2vec2 对齐：~1.4s
- 总流水线：~13s 处理 30s 音频

## 已知注意事项
1. **ffmpeg 需要 PATH**：`whisperx.load_audio()` 内部 subprocess 调用 ffmpeg，已拷贝 `ffmpeg.exe` 到 venv 的 `imageio_ffmpeg\binaries\` 并加入 PATH
2. **NLTK punkt_tab**：从 jsDelivr CDN 下载到 `C:\Python311\nltk_data\tokenizers\punkt_tab`，需要设置 `NLTK_DATA` 环境变量
3. **torchcodec 警告**：pyannote 报 torchcodec 不兼容，但不影响功能（whisperX 用 ffmpeg 解码）
4. **启动脚本要用 `.venv\Scripts\python.exe`**，不能是系统 Python 3.14

## 下一步
Phase 1: 实现 `SRT/VocalSeparator.py`（demucs 人声分离封装）
Phase 2: 实现 `SRT/VAD_Segmenter.py`（VAD 分段包装）
