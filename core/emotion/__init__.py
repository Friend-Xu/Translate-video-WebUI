"""core/emotion — 情感智能层 (Chapter 15)"""
from core.emotion.emotion_space import EmotionVector, LABEL_TO_VAD
from core.emotion.tts_router import EmotionTTSRouter, TTSRoute
from core.emotion.alignment_checker import EmotionAlignmentChecker, EmotionAlignmentResult

__all__ = [
    "EmotionVector", "LABEL_TO_VAD",
    "EmotionTTSRouter", "TTSRoute",
    "EmotionAlignmentChecker", "EmotionAlignmentResult",
]
