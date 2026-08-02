"""
SRT Package — 执行层协作模块 (架构收束后)

仅保留被 core/adapters 包装的引擎模块:
├── VAD_Segmenter.py          — Silero VAD 音频分割 (← whisper_adapter / vad_boundary_adapter)
├── MediaValidator.py         — 视频时长缺陷检测 + aresample 修复 (← media_validator_adapter)
├── TranslationVerifier.py    — 跨语言语义相似度核验 (← minilm_adapter → logic_gate)
├── Json_Convert_Srt_EN.py    — JSON 转 SRT (英语, 仅供 tests/test_tts 验证, 待退役)
├── Json_Convert_Srt_JP.py    — JSON 转 SRT (日语, 同上)
├── Json_Convert_Srt.py       — 主入口 (加载 Config.yaml, 调度 EN/JP 处理器)
└── Config.yaml               — 多语言预设参数

已退役 (架构收束 P3): SRT_Translator / glossary_injector / TermReplacer /
translation_agents / mqm_scorer / TargetedRecognizer / VocalSeparator /
Wav2Vec2Aligner / LANGUAGE_PRESETS 及备份文件。
翻译统一走 core (LLMTranslationPass 链 + xCOMET 质量闭环)。
"""
