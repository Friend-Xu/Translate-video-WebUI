"""
EmotionTTSRouter — 情感驱动 TTS 引擎路由 (Chapter 15 §15.9)
"""
from __future__ import annotations
from dataclasses import dataclass
from core.emotion.emotion_space import EmotionVector


@dataclass
class TTSRoute:
    engine: str; priority: int; reason: str
    prosody_override: dict | None = None


class EmotionTTSRouter:
    ENGINE_CAPABILITY = {
        "chattts": {"max_arousal": 1.0, "emotion_fidelity": 0.9},
        "cosyvoice": {"max_arousal": 0.6, "emotion_fidelity": 0.5},
        "indextts": {"max_arousal": 0.4, "emotion_fidelity": 0.3},
        "openvoice": {"max_arousal": 0.3, "emotion_fidelity": 0.2},
        "edge_tts": {"max_arousal": 0.2, "emotion_fidelity": 0.1},
    }

    def route(self, emo: EmotionVector) -> TTSRoute:
        a, c, i = emo.arousal, emo.confidence, emo.intensity
        if a > 0.7:
            return TTSRoute("chattts", 1, "high_arousal", self._prosody(emo))
        if a < -0.3 and emo.dominance > 0.5:
            return TTSRoute("cosyvoice", 1, "calm_dominant", self._prosody(emo))
        if c < 0.3:
            return TTSRoute("edge_tts", 3, "low_confidence_fallback")
        if i < 0.2:
            return TTSRoute("edge_tts", 3, "low_intensity")
        if c > 0.8 and abs(emo.valence) < 0.3:
            return TTSRoute("indextts", 1, "neutral_stable", self._prosody(emo))
        return TTSRoute("cosyvoice", 1, "default", self._prosody(emo))

    def _prosody(self, emo: EmotionVector) -> dict:
        return {
            "speed": round(1.0 + emo.arousal * 0.3, 2),
            "energy": round(0.5 + abs(emo.arousal) * 0.5, 2),
            "pitch": round(0.5 + emo.valence * 0.3, 2),
        }
