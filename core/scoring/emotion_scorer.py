"""
EmotionScorer — 情感质量评分器 (Chapter 15 §15.6)
"""
from __future__ import annotations
from dataclasses import dataclass
from core.emotion.emotion_space import EmotionVector


@dataclass
class EmotionScore:
    emotion_consistency: float = 0.5
    emotion_intensity_match: float = 0.5
    speaker_emotion_fit: float = 0.5
    translation_emotion_alignment: float = 0.5
    accepted: bool = False
    composite: float = 0.0
    gate_decision: str = ""


class EmotionScorer:
    DEFAULT_WEIGHTS = {"consistency": 0.30, "intensity": 0.25,
                       "speaker_fit": 0.25, "translation_alignment": 0.20}
    ACCEPT_THRESHOLD = 0.60
    MAX_VAD_BREAK = 1.5
    MAX_INTENSITY_JUMP = 0.7
    MIN_CONFIDENCE = 0.3

    def __init__(self, weights: dict | None = None):
        self.weights = weights or dict(self.DEFAULT_WEIGHTS)

    def score(self, current: EmotionVector,
              previous: EmotionVector | None = None,
              speaker_baseline: EmotionVector | None = None,
              translation_emotion: EmotionVector | None = None) -> EmotionScore:
        s = EmotionScore()

        if previous is not None:
            s.emotion_consistency = round(
                max(0.0, 1.0 - current.distance(previous) / self.MAX_VAD_BREAK), 4)
            s.emotion_intensity_match = round(
                max(0.0, 1.0 - abs(current.intensity - previous.intensity) / self.MAX_INTENSITY_JUMP), 4)

        if speaker_baseline is not None:
            s.speaker_emotion_fit = round(
                max(0.0, 1.0 - current.distance(speaker_baseline) / 2.0), 4)

        if translation_emotion is not None:
            s.translation_emotion_alignment = round(
                max(0.0, 1.0 - current.distance(translation_emotion) / 1.5), 4)

        if current.confidence < self.MIN_CONFIDENCE:
            s.composite = 0.0; s.gate_decision = "review"; return s

        s.composite = round(
            self.weights["consistency"] * s.emotion_consistency
            + self.weights["intensity"] * s.emotion_intensity_match
            + self.weights["speaker_fit"] * s.speaker_emotion_fit
            + self.weights["translation_alignment"] * s.translation_emotion_alignment, 4)
        s.accepted = s.composite >= self.ACCEPT_THRESHOLD
        s.gate_decision = "accept" if s.accepted else "repair"
        return s
