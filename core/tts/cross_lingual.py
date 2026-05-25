"""
CrossLingualProcessor — 跨语种配音语言标签管理 (Chapter 6 §6.6)

管理 CosyVoice 的 language tag 注入、v2/v3 prompt 格式差异、
和跨语种文本预处理。
"""
from __future__ import annotations


class CrossLingualProcessor:
    """跨语种配音处理器 — language tag 注入和文本预处理。

    职责:
      1. 标准化语言代码为 CosyVoice 5 个有效标签之一
      2. 为 v2/v3 构建正确的带 language tag 推理文本
      3. 根据语言对提供节奏参数建议
    """

    VALID_LANGS = {"zh", "en", "ja", "ko", "yue"}

    # 语言对 → 推荐 speed 范围
    LANG_PAIR_SPEED = {
        ("zh", "en"): (0.85, 0.95),
        ("en", "zh"): (1.05, 1.15),
        ("ja", "zh"): (1.0, 1.1),
        ("zh", "ja"): (0.95, 1.05),
        ("zh", "ko"): (0.95, 1.05),
        ("ko", "zh"): (0.95, 1.05),
        ("en", "ja"): (0.9, 1.0),
        ("ja", "en"): (0.9, 1.0),
        ("zh", "yue"): (1.0, 1.1),
        ("yue", "zh"): (0.95, 1.05),
    }

    V3_PREFIX = "You are a helpful assistant."
    V3_SEPARATOR = "<|endofprompt|>"

    def normalize_lang(self, lang: str) -> str:
        """标准化语言代码为 CosyVoice 5 个有效标签之一。

        例如: "zh-CN" → "zh", "en-US" → "en", "ja-JP" → "ja"
        """
        if not lang:
            return ""
        raw = lang.lower().replace("-", "").replace("_", "")
        if raw in self.VALID_LANGS:
            return raw
        for valid in ("zh", "yue", "ja", "ko", "en"):
            if raw.startswith(valid) or valid in raw:
                return valid
        if len(raw) >= 2 and raw[:2] in self.VALID_LANGS:
            return raw[:2]
        return ""

    def build_tagged_text(self, text: str, lang: str,
                          model_version: str = "v3") -> str:
        """构建带 language tag 的推理文本。

        v2: "<|zh|>今天天气不错"
        v3: "You are a helpful assistant.<|zh|><|endofprompt|>今天天气不错"
        """
        normalized = self.normalize_lang(lang)
        tag = f"<|{normalized}|>" if normalized else ""
        if model_version == "v3":
            return f"{self.V3_PREFIX}{tag}{self.V3_SEPARATOR}{text}"
        return f"{tag}{text}"

    def get_language_pair_constraints(self, source_lang: str,
                                      target_lang: str) -> dict:
        """根据语言对返回节奏参数建议。

        Returns: {"speed_min": float, "speed_max": float, "speed_default": float}
        """
        src = self.normalize_lang(source_lang)
        tgt = self.normalize_lang(target_lang)
        if src == tgt:
            return {"speed_min": 0.95, "speed_max": 1.05, "speed_default": 1.0}
        key = (src, tgt)
        if key in self.LANG_PAIR_SPEED:
            lo, hi = self.LANG_PAIR_SPEED[key]
            return {"speed_min": lo, "speed_max": hi,
                    "speed_default": round((lo + hi) / 2, 2)}
        return {"speed_min": 0.9, "speed_max": 1.1, "speed_default": 1.0}

    def is_valid_lang(self, lang: str) -> bool:
        """检查语言代码是否在 CosyVoice 支持的范围内。"""
        return bool(self.normalize_lang(lang))
