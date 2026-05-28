"""core/scoring — 评分引擎 (Chapter 3 §3.6, Chapter 5 §5.8, Chapter 6 §6.8, Chapter 7 §7.8)

各引擎域的联合评分公式，为 Logic Gate 提供决策依据。
"""
from core.scoring.asr_scorer import ASRScorer, ASRScore
from core.scoring.tts_scorer import TTSScorer, TTSScore
from core.scoring.cosyvoice_scorer import CosyVoiceScorer, CosyVoiceScore
from core.scoring.indextts_scorer import IndexTTSScorer, IndexTTSScore
from core.scoring.openvoice_scorer import OpenVoiceScorer, OpenVoiceScore
from core.scoring.edge_tts_scorer import EdgeTTSScorer, EdgeTTSScore
from core.scoring.translation_scorer import TranslationScorer, TranslationScore
from core.scoring.emotion_scorer import EmotionScorer, EmotionScore

__all__ = [
    "ASRScorer", "ASRScore",
    "TTSScorer", "TTSScore",
    "CosyVoiceScorer", "CosyVoiceScore",
    "IndexTTSScorer", "IndexTTSScore",
    "OpenVoiceScorer", "OpenVoiceScore",
    "EdgeTTSScorer", "EdgeTTSScore",
    "TranslationScorer", "TranslationScore",
    "EmotionScorer", "EmotionScore",
]
