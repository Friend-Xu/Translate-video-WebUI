"""
EmotionVector — VAD 三维情感空间 (Chapter 15 §15.4)

Valence/Arousal/Dominance, 连续插值, 双向标签转换
"""
from __future__ import annotations
from dataclasses import dataclass
import math

LABEL_TO_VAD: dict[str, tuple[float, float, float]] = {
    "angry": (-0.7, 0.85, 0.7), "disgusted": (-0.6, 0.4, 0.3),
    "fearful": (-0.65, 0.7, -0.5), "happy": (0.85, 0.75, 0.6),
    "neutral": (0.0, -0.1, 0.0), "other": (0.0, 0.0, 0.0),
    "sad": (-0.8, -0.5, -0.6), "surprised": (0.3, 0.9, -0.1),
    "excited": (0.8, 0.95, 0.55), "serious": (-0.1, -0.2, 0.5),
    "calm": (0.4, -0.7, 0.1), "question": (0.1, 0.5, -0.1),
    "gentle": (0.5, -0.5, -0.2), "urgent": (-0.2, 0.8, 0.4),
    "whisper": (0.0, -0.3, -0.4), "confused": (-0.2, 0.4, -0.3),
    "bored": (-0.3, -0.7, -0.3), "confident": (0.6, 0.3, 0.7),
    "curious": (0.3, 0.6, 0.1), "disappointed": (-0.55, -0.3, -0.3),
    "relieved": (0.5, -0.4, 0.1), "anxious": (-0.5, 0.65, -0.4),
    "encouraging": (0.65, 0.35, 0.35), "sarcastic": (0.1, 0.3, 0.25),
    "authoritative": (0.2, 0.15, 0.85), "warm": (0.7, -0.1, 0.15),
}

EMOTION2VEC_LABELS = [
    "angry", "disgusted", "fearful", "happy",
    "neutral", "other", "sad", "surprised", "<unk>",
]


@dataclass
class EmotionVector:
    emotion: str = "neutral"
    valence: float = 0.0
    arousal: float = 0.0
    dominance: float = 0.0
    confidence: float = 0.0
    intensity: float = 0.0

    def __post_init__(self):
        if self.intensity is None or abs(self.intensity) < 1e-9:
            self.intensity = round(math.sqrt(
                self.valence**2 + self.arousal**2 + self.dominance**2
            ) / math.sqrt(3), 4)

    @classmethod
    def from_label(cls, label: str, confidence: float = 0.8) -> "EmotionVector":
        v, a, d = LABEL_TO_VAD.get(label, (0.0, -0.1, 0.0))
        return cls(emotion=label, valence=v, arousal=a, dominance=d, confidence=confidence)

    @classmethod
    def from_9class_scores(cls, scores: dict[str, float]) -> "EmotionVector":
        tv, ta, td, tw = 0.0, 0.0, 0.0, 0.0
        best_label, best_score = "neutral", 0.0
        for label, score in scores.items():
            if label in ("<unk>", "other"):
                continue
            v, a, d = LABEL_TO_VAD.get(label, (0.0, 0.0, 0.0))
            tv += score * v; ta += score * a; td += score * d; tw += score
            if score > best_score:
                best_score = score; best_label = label
        if tw > 0:
            tv /= tw; ta /= tw; td /= tw
        return cls(emotion=best_label, valence=round(tv, 4),
                   arousal=round(ta, 4), dominance=round(td, 4),
                   confidence=round(best_score, 4))

    def distance(self, other: "EmotionVector") -> float:
        return math.sqrt(
            (self.valence - other.valence)**2
            + (self.arousal - other.arousal)**2
            + (self.dominance - other.dominance)**2
        )

    def interpolate(self, other: "EmotionVector", t: float) -> "EmotionVector":
        t = max(0.0, min(1.0, t))
        return EmotionVector(
            emotion=self.emotion if t < 0.5 else other.emotion,
            valence=self.valence + t * (other.valence - self.valence),
            arousal=self.arousal + t * (other.arousal - self.arousal),
            dominance=self.dominance + t * (other.dominance - self.dominance),
            confidence=self.confidence * (1 - t) + other.confidence * t,
        )

    def to_label(self) -> str:
        best, best_d = "neutral", float("inf")
        for label, (v, a, d) in LABEL_TO_VAD.items():
            dist = (self.valence - v)**2 + (self.arousal - a)**2 + (self.dominance - d)**2
            if dist < best_d:
                best_d = dist; best = label
        return best

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in
                ("emotion", "valence", "arousal", "dominance", "confidence", "intensity")}
