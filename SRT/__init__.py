"""
SRT Package — 执行层协作模块 (架构收束后)

仅保留被 core/adapters 包装的引擎模块:
├── VAD_Segmenter.py          — Silero VAD 音频分割 (← whisper_adapter / vad_boundary_adapter)
├── MediaValidator.py         — 视频时长缺陷检测 + aresample 修复 (← media_validator_adapter)
└── TranslationVerifier.py    — 跨语言语义相似度核验 (← minilm_adapter → logic_gate)

翻译与字幕生成统一走 core (LLMTranslationPass 链 + SRTExportPass)。
"""
