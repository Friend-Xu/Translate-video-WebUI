"""
CosyVoiceDurationController — CosyVoice 专用时长控制 (Chapter 6 §6.5)

与 ChatTTS DurationController (Ch5) 的核心差异:
  CosyVoice 原生支持 speed 参数 (0.5-2.0)，应优先使用引擎能力而非后处理。

四级策略:
  Level 0 — 预计算 speed: 在合成前根据文本长度估算最佳 speed 参数
  Level 1 — 预检通过: deviation ≤ tolerance → "accept"
  Level 2 — 调速重试: tolerance < deviation ≤ 30% → "retry_with_speed"
  Level 3 — 分段重生成: deviation > 30% → "split"
"""
from __future__ import annotations

# 跨语种每秒字符数估算
LANG_CPS = {
    "zh": 4.0,    # 中文 ~4 chars/sec
    "en": 10.0,   # 英文 ~10 chars/sec
    "ja": 5.0,    # 日文 ~5 chars/sec
    "ko": 5.0,    # 韩文 ~5 chars/sec
    "yue": 4.5,   # 粤语 ~4.5 chars/sec
}


class CosyVoiceDurationController:
    """CosyVoice 专用时长控制器 — 优先使用原生 speed 参数。

    与 Ch5 DurationController 策略差异:
      Level 2 用 engine speed (pre-generation) 而非 RubberBand (post-hoc)
    """

    MAX_SPEED = 2.0
    MIN_SPEED = 0.5
    LEVEL3_FACTOR = 0.30

    def compute_speed(self, estimated_duration: float,
                      target_duration: float) -> float:
        """根据估算时长与目标时长计算最佳 speed 参数。

        speed = target / estimated，限制在 [0.5, 2.0]。
        """
        if estimated_duration <= 0 or target_duration <= 0:
            return 1.0
        ratio = target_duration / estimated_duration
        return max(self.MIN_SPEED, min(self.MAX_SPEED, round(ratio, 3)))

    def check(self, actual_duration: float, target_duration: float,
              tolerance: float = 0.15) -> str:
        """判定时长处理策略。

        Returns: "accept" | "retry_with_speed" | "split"

        与 Ch5 DurationController 差异:
          "stretch" 替换为 "retry_with_speed"（重新合成而非音频后处理）
        """
        if target_duration <= 0:
            return "accept"
        deviation = abs(actual_duration - target_duration) / target_duration
        if deviation <= tolerance:
            return "accept"
        if deviation <= self.LEVEL3_FACTOR:
            ratio = target_duration / actual_duration
            if self.MIN_SPEED <= ratio <= self.MAX_SPEED:
                return "retry_with_speed"
        return "split"

    def compute_retry_speed(self, actual_duration: float,
                            target_duration: float) -> float:
        """基于上次合成结果计算重试 speed。"""
        if actual_duration <= 0:
            return 1.0
        ratio = target_duration / actual_duration
        return max(self.MIN_SPEED, min(self.MAX_SPEED, round(ratio, 3)))

    def estimate_duration(self, text: str, speed: float = 1.0,
                          lang: str = "") -> float:
        """基于文本长度和语言估算预期时长。

        speed 参数已纳入计算: estimated = char_count / cps / speed
        """
        if not text:
            return 0.0
        cps = LANG_CPS.get(lang, 5.0)
        base = len(text) / cps
        if speed <= 0:
            speed = 1.0
        return round(base / speed, 3)


def estimate_tts_duration(text: str, lang: str,
                          speed: float = 1.0) -> float:
    """跨语种 TTS 时长预估算。"""
    if not text:
        return 0.0
    cps = LANG_CPS.get(lang, 5.0)
    if speed <= 0:
        speed = 1.0
    return round(len(text) / cps / speed, 3)
