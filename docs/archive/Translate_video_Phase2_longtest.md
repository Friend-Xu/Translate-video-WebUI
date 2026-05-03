# Phase 2 — 长视频验证 (longTest.TS)

## 测试环境
- 输入: longTest.TS (1033 MB, 59.9 min)
- CPU: 纯 CPU 推理
- 模型: Demucs htdemucs + Silero VAD

## 人声分离结果
- 耗时: 21 分 14 秒
- 输出: vocals.wav (1210 MB) + no_vocals.wav
- 实时率: ~2.8x (处理1秒音频需2.8秒)

## VAD 分段结果
- 策略: 5min/块分块处理，1s 重叠
- 耗时: 132.2 秒 (13 块)
- 原始检测: 408 段
- 后处理后: **180 段**
- 总语音时长: 16.9 min
- 静音/音乐占比: **71.8%**
- 平均段长: 5.6s
- 段长范围: 1.2s ~ 32.6s

## 关键修复
- 长音频 VAD 内存溢出 → 实现分块处理（5min/块）
- logger 引用错误修复

## 性能估算
- 人声分离: ~21 min
- VAD 分段: ~2 min
- whisperX 转录: ~9 min (180段)
- wav2vec2 对齐: ~3 min
- **60分钟视频总耗时: ~35 min**
