"""
EmotionVectorMapper — IndexTTS 24 类情绪向量映射 (Chapter 7 §7.1)

将 emotion_hint 字符串映射为 IndexTTS 的 emo_vector（24 维）+ emo_alpha。
与 ChatTTS 的 refine_prompt 字符串 (Ch5) 和 CosyVoice 的无情绪支持 (Ch6) 完全不同。
"""
from __future__ import annotations


class EmotionVectorMapper:
    """将 emotion_hint 映射为 IndexTTS 的 emo_vector + emo_alpha。

    IndexTTS 使用 24 类情绪向量 (基于 feat2.pt 情绪矩阵)，
    每个 emotion_hint 映射到 24 维 one-hot 风格的向量，
    emo_alpha 控制情绪强度。
    """

    # 24 类情绪索引（基于 IndexTTS feat2.pt emo_num 定义）
    EMOTION_INDEX = {
        "neutral":   0,  "angry": 1,    "excited": 2,   "sad": 3,
        "serious":   4,  "gentle": 5,   "urgent": 6,    "whisper": 7,
        "question":  8,  "surprised": 9,"disgusted": 10, "fearful": 11,
        "happy":     12, "confused": 13,"bored": 14,    "confident": 15,
        "curious":   16, "disappointed": 17, "relieved": 18, "anxious": 19,
        "encouraging": 20, "sarcastic": 21, "authoritative": 22, "warm": 23,
    }

    VECTOR_DIM = 24

    def to_emo_vector(self, emotion_hint: str,
                      intensity: float = 1.0) -> list[float]:
        """将 emotion_hint 映射为 24 维情绪向量。

        intensity ∈ [0, 2] 控制向量幅度。
        neutral → 全零向量（无情绪偏向）。
        """
        if not emotion_hint or emotion_hint == "neutral":
            return [0.0] * self.VECTOR_DIM

        idx = self.EMOTION_INDEX.get(emotion_hint)
        if idx is None:
            # 模糊匹配：检查部分匹配
            for key, val in self.EMOTION_INDEX.items():
                if key in emotion_hint or emotion_hint in key:
                    idx = val
                    break
        if idx is None:
            return [0.0] * self.VECTOR_DIM

        vec = [0.0] * self.VECTOR_DIM
        vec[idx] = round(min(1.0, intensity), 4)
        return vec

    def blend_emotions(self, primary: str, secondary: str,
                       ratio: float = 0.7) -> list[float]:
        """混合两种情绪向量。

        ratio=0.7 → 70% primary + 30% secondary。
        """
        p_vec = self.to_emo_vector(primary)
        s_vec = self.to_emo_vector(secondary)
        ratio = max(0.0, min(1.0, ratio))
        return [
            round(ratio * p + (1 - ratio) * s, 4)
            for p, s in zip(p_vec, s_vec)
        ]

    def get_emotion_name(self, index: int) -> str:
        """根据向量索引返回情绪名称。"""
        for name, idx in self.EMOTION_INDEX.items():
            if idx == index:
                return name
        return "unknown"
