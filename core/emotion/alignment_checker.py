"""
EmotionAlignmentChecker — 翻译-情感一致性 (Chapter 15 §15.8)
amplification / suppression / drift
"""
from __future__ import annotations
from dataclasses import dataclass
from core.emotion.emotion_space import EmotionVector


@dataclass
class EmotionAlignmentResult:
    aligned: bool; drift_type: str | None; drift_magnitude: float
    source_emotion: EmotionVector; translation_emotion: EmotionVector
    suggestion: str = ""


class EmotionAlignmentChecker:

    def __init__(self, max_drift: float = 0.8):
        self.max_drift = max_drift

    def check(self, src: EmotionVector, trans_text: str) -> EmotionAlignmentResult:
        tev = self._infer(trans_text)
        d = src.distance(tev)
        if d <= self.max_drift:
            return EmotionAlignmentResult(True, None, round(d, 4), src, tev)
        if tev.arousal > src.arousal + 0.5:
            return EmotionAlignmentResult(False, "amplification", round(d, 4), src, tev,
                                          "tone down translation emotion")
        if tev.arousal < src.arousal - 0.5:
            return EmotionAlignmentResult(False, "suppression", round(d, 4), src, tev,
                                          "restore source emotion intensity")
        return EmotionAlignmentResult(False, "drift", round(d, 4), src, tev,
                                      "review translation emotional tone")

    def _infer(self, text: str) -> EmotionVector:
        try:
            from core.tts.emotion import EmotionModeler
            return EmotionVector.from_label(
                EmotionModeler().infer_emotion(text).get("emotion_hint", "neutral"))
        except Exception:
            return EmotionVector()
