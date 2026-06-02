"""core/tts — TTS 共享模块

- DurationController / duration_fit_score: ChatTTS 时长控制 (Ch5)
- EmotionModeler: ChatTTS 情绪推断 (Ch5)
- CosyVoiceDurationController / estimate_tts_duration: CosyVoice 时长控制 (Ch6)
- CrossLingualProcessor: 跨语种语言标签管理 (Ch6)
- EmotionVectorMapper: IndexTTS 24 类情绪向量映射 (Ch7)
- FallbackDecider: 降级决策器 (Ch8)
"""
from core.tts.duration_control import DurationController, SpeedDecision, duration_fit_score
from core.tts.emotion import EmotionModeler
from core.tts.cosyvoice_duration import CosyVoiceDurationController, estimate_tts_duration
from core.tts.cross_lingual import CrossLingualProcessor
from core.tts.index_emotion import EmotionVectorMapper
from core.tts.fallback_decider import FallbackDecider, FallbackDecision

__all__ = [
    "DurationController", "SpeedDecision", "duration_fit_score", "EmotionModeler",
    "CosyVoiceDurationController", "estimate_tts_duration",
    "CrossLingualProcessor", "EmotionVectorMapper",
    "FallbackDecider", "FallbackDecision",
]
