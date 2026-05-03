# Phase 2 — VAD_Segmenter 完成

## 完成的工作

### 文件
- **新增** `SRT/VAD_Segmenter.py` — Silero VAD 语音活动检测封装
- **新增** `models/vad/` 目录 — Silero VAD 模型本地缓存
  - `silero_vad.jit` (1.4MB)
  - `silero_vad.onnx` (1.8MB)
  - `utils_vad.py` (工具函数)

### 设计决策
- **使用 Silero VAD** 替代 ModelScope fsmn_vad
  - whisperX 底层同款，生态一致
  - 模型仅 1.4MB，CPU 推理极快 (~200x 实时)
  - 安装零依赖（仅 torch）
- **模型本地化管理**
  - 优先从 `models/vad/` 加载（项目自包含）
  - 缺失时自动从 torch.hub 下载并保存到项目目录
- **后处理管道**
  1. 合并间隔 < 3s 的段（默认）
  2. 过滤 < 0.5s 的短语音
  3. 前后 padding 0.3s
  4. 强制切割 > 15min 的段
- **JSON 缓存**
  - 缓存路径：`{audio_name}_vad_segments.json`
  - 参数匹配校验，参数变更自动重新推理

### 性能基准
- 模型加载：~0.5s（本地）
- VAD 推理：~2s（41s 音频）
- 缓存加载：<0.01s
- 输出：1 段 (0~41.4s) — 测试视频为连续说话，符合预期

### API
```python
from SRT.VAD_Segmenter import VAD_Segmenter

seg = VAD_Segmenter("audio.wav")
segments = seg.get_segments()  # [(0.0, 41.38), ...]
```

### 后续适配注意
- whisperX 转录时，每段需要偏移 VAD 段的起始时间
- 建议转录前先用 `VAD_Segmenter` 分段，再逐段调用 whisperX

## 下一步
Phase 3: SRT_Extract.py 重构（新增 `extract_with_whisperx()` 方法）
