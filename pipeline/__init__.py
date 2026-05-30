"""
pipeline/ — faster-whisper 直连流水线模块

数据流:
  video_info.py   → 视频元数据采集 (NODE 1)
  MediaValidator  → C2 缺陷诊断 (NODE 1.5)
  audio.py        → 音频提取 + aresample 修复 (NODE 2)
  transcriber.py  → VAD + faster-whisper 转录 + 词级分组 (NODE 3)
  Json_Convert_Srt → SRT 输出 (NODE 4)

每个模块保持单一职责，通过 dict/DataClass 传递结果。
"""
