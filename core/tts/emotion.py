"""
EmotionModeler — 三信号情绪推断 + refine_prompt 生成 (Chapter 5 §5.4)

信号1: 语义线索 — 关键词句式检测
信号2: 声学线索 — wav2vec2 energy/pitch (placeholder)
信号3: 说话人线索 — speaker history 情绪基线

输出 ChatTTS refine_prompt: [oral_N][laugh_M][break_K]
"""
from __future__ import annotations
from core.adapters.chattts_adapter import TTSSegmentContext


EMOTION_MAP = {
    "angry":    (7, 0, 2),
    "excited":  (7, 2, 3),
    "sad":      (1, 0, 7),
    "neutral":  (3, 1, 5),
    "serious":  (2, 0, 5),
    "question": (4, 0, 4),
    "happy":    (6, 2, 4),
    "calm":     (2, 1, 6),
}

SENTIMENT_KEYWORDS = {
    "angry":    ["可恶", "混蛋", "该死", "气死", "dammit", "angry"],
    "excited":  ["太好了", "太棒", "哇", "amazing", "wow"],
    "sad":      ["难过", "可惜", "遗憾", "伤心", "sorry"],
    "question": ["?", "？", "为什么", "怎么", "why", "how"],
    "serious":  ["必须", "一定", "注意", "must", "important"],
}


class EmotionModeler:
    """三信号情绪推断 — 语义优先，声学+历史作为 fallback。"""

    def infer_emotion(self, ctx: TTSSegmentContext,
                      speaker_history: list[dict] | None = None) -> dict:
        semantic = self._detect_sentiment(ctx.translation_text or ctx.source_text)
        history = self._get_history_baseline(ctx.speaker_id, speaker_history)
        emotion_hint = semantic or history or "neutral"
        return {
            "emotion_hint": emotion_hint,
            "prosody": self._emotion_to_prosody(emotion_hint),
        }

    def to_refine_prompt(self, emotion: dict) -> str:
        hint = emotion.get("emotion_hint", "neutral")
        oral, laugh, brk = EMOTION_MAP.get(hint, (3, 1, 5))
        prosody = emotion.get("prosody", {})
        if prosody:
            oral = max(0, min(9, int(prosody.get("energy", 0.5) * 9)))
            brk = max(0, min(9, int((2.0 - prosody.get("speed", 1.0)) * 4)))
        return f"[oral_{oral}][laugh_{laugh}][break_{brk}]"

    @staticmethod
    def _detect_sentiment(text: str) -> str | None:
        if not text:
            return None
        text_lower = text.lower()
        scores = {e: sum(1 for kw in kws if kw in text_lower)
                  for e, kws in SENTIMENT_KEYWORDS.items()}
        best = max(scores, key=lambda k: scores[k])
        return best if scores[best] > 0 else None

    @staticmethod
    def _get_history_baseline(speaker_id: str | None,
                              history: list[dict] | None) -> str | None:
        if not speaker_id or not history:
            return None
        emotions = [h.get("emotion_hint") for h in history
                    if h.get("speaker_id") == speaker_id and h.get("emotion_hint")]
        return max(set(emotions), key=emotions.count) if emotions else None

    @staticmethod
    def _emotion_to_prosody(emotion: str) -> dict:
        defaults = {
            "angry":    {"speed": 1.2, "energy": 0.9, "pitch": 0.7},
            "excited":  {"speed": 1.3, "energy": 0.9, "pitch": 0.8},
            "sad":      {"speed": 0.7, "energy": 0.2, "pitch": 0.3},
            "neutral":  {"speed": 1.0, "energy": 0.5, "pitch": 0.5},
            "serious":  {"speed": 0.9, "energy": 0.5, "pitch": 0.4},
            "question": {"speed": 1.1, "energy": 0.5, "pitch": 0.6},
            "calm":     {"speed": 0.8, "energy": 0.3, "pitch": 0.4},
            "happy":    {"speed": 1.2, "energy": 0.7, "pitch": 0.6},
        }
        return defaults.get(emotion, defaults["neutral"])
