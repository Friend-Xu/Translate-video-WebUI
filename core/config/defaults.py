"""
Defaults — 各槽位默认值字典 (定稿 §1.4, §13.2)

从 GlobalConfig 提取的纯 dict 默认值，作为 ConfigResolver 的 Layer 1 输入。
所有 7 个槽位的默认参数集中于此。

与 GlobalConfig (dataclass) 的区别:
  - GlobalConfig: 类型安全的顶层配置容器，支持 YAML 加载/保存
  - defaults:   纯 dict，轻量级，ConfigResolver 的入参格式
"""
from __future__ import annotations

AUDIO_DEFAULTS: dict = {
    "skip_demucs": False,
    "validate_defect": True,
    "vad_threshold": 0.5,
    "silence_handling": "keep",
    "loudness_compensation": True,
    "target_loudness": -16.0,
    "high_pass_filter": False,
    "demucs_model": "htdemucs",
}

ASR_DEFAULTS: dict = {
    "model": "turbo",
    "device": "cuda",
    "compute_type": "float16",
    "language": "auto",
    "alignment_enabled": True,
    "num_workers": 1,
    "beam_size": 5,
    "word_timestamps": True,
}

SPEAKER_DEFAULTS: dict = {
    "clustering_threshold": 0.65,
    "min_speakers": None,
    "max_speakers": None,
    "clustering_method": "agglomerative",
    "gender": "auto",
    "embedding_model": "pyannote/embedding",
    "min_segment_duration": 0.5,
    "merge_similar_speakers_threshold": 0.85,
}

TRANSLATION_DEFAULTS: dict = {
    "lang": "zh",
    "backend": "deepseek",
    "glossary_mode": "OFF",
    "custom_prompt": "",
    "gate_mode": "logic_gate",
    "gate_threshold_accept": 0.80,
    "gate_threshold_reject": 0.60,
    "gate_beta": 0.6,
    "gate_gamma": 0.4,
    "gate_sim_drop_limit": 0.05,
}

TTS_DEFAULTS: dict = {
    "engine": "chattts",
    "voice_gender": "auto",
    "speed_factor": 1.0,
    "timing_adaptive": True,
    "timing_threshold": 0.15,
    "max_speed_adjustment": 1.0,
    "chattts_speaker_seed": 2,
    "chattts_temperature": 0.3,
    "chattts_top_k": 50,
    "chattts_top_p": 0.9,
    "chattts_emotion_injection": True,
    "cosy_version": "v2",
    "cosy_lang": "zh",
    "cosy_num_norm": True,
    "cosy_fp16": True,
    "edge_voice": "zh-CN-XiaoxiaoNeural",
    "edge_pitch": "+0Hz",
    "edge_volume": "+0%",
}

EMOTION_DEFAULTS: dict = {
    "enabled": True,
    "audio_model": "iic/emotion2vec_plus_large",
    "audio_context_window": 3,
    "energy_normalize": True,
    "text_model": "distiluse",
    "text_confidence_threshold": 0.5,
    "text_emotion_injection": True,
    "fusion_strategy": "weighted_average",
    "audio_weight": 0.7,
    "text_weight": 0.3,
    "fallback_threshold": 0.4,
    "gate_max_break": 1.5,
    "gate_min_confidence": 0.3,
    "gate_max_conflict": 1.0,
}

REVIEW_DEFAULTS: dict = {
    "force_accept": False,
}

SLOT_DEFAULTS: dict[str, dict] = {
    "audio": AUDIO_DEFAULTS,
    "asr": ASR_DEFAULTS,
    "speaker": SPEAKER_DEFAULTS,
    "semantic": {},
    "translation": TRANSLATION_DEFAULTS,
    "tts": TTS_DEFAULTS,
    "emotion": EMOTION_DEFAULTS,
    "review": REVIEW_DEFAULTS,
    "runtime": {},
    "provenance": {},
}
