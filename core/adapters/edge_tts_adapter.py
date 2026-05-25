"""
EdgeTTSAdapter — Edge TTS → Patch 适配器 (Chapter 9 §9.3-9.4)

封装现有 EdgeTTSEngine，不做修改。
Edge TTS 定位为"通用兜底语音引擎"——最后一道保险。
不需要 GPU、不需要 speaker、不需要 emotion、不需要 warmup。

与 Ch5-8 适配器的根本差异:
  - 最简适配器 — 只需 text + lang/voice + rate
  - 云 API，无本地模型，无子进程
  - 不支持 speaker 绑定、不支持 emotion
  - 输出标记 generation_mode=fallback
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode


@dataclass
class EdgeTTSSegmentContext:
    """Edge TTS 结构化输入 — 最简 context，只需文本 + 语言。"""
    segment_id: str
    translation_text: str
    lang: str = ""
    voice: str = ""
    duration_target: float = 0.0
    rate: str = "+0%"
    fallback_reason: str = ""


class EdgeTTSAdapter:
    """将 Edge TTS 输出转为 UPDATE_TTS_AUDIO patch。

    封装现有 EdgeTTSEngine，不做修改。
    Edge TTS 定位为"通用兜底语音引擎"——最后一道保险。
    """

    # EDGE_VOICE_MAP 本地副本（避免跨模块依赖）
    _VOICE_MAP = {
        "zh": "zh-CN-XiaoxiaoNeural",
        "zh-CN": "zh-CN-XiaoxiaoNeural",
        "zh-TW": "zh-TW-HsiaoChenNeural",
        "ja": "ja-JP-NanamiNeural",
        "en": "en-US-AriaNeural",
        "ko": "ko-KR-SunHiNeural",
        "fr": "fr-FR-DeniseNeural",
        "de": "de-DE-KatjaNeural",
        "es": "es-ES-ElviraNeural",
        "pt": "pt-BR-FranciscaNeural",
        "ru": "ru-RU-SvetlanaNeural",
        "ar": "ar-SA-ZariyahNeural",
        "th": "th-TH-PremwadeeNeural",
        "vi": "vi-VN-HoaiMyNeural",
        "id": "id-ID-GadisNeural",
        "it": "it-IT-ElsaNeural",
    }

    def __init__(self, voice: str = "", output_dir: str = ""):
        self._voice = voice
        self._output_dir = output_dir
        self._engine = None

    def synthesize(self, ctx: EdgeTTSSegmentContext) -> Patch:
        """对单个 segment 合成语音，返回 UPDATE_TTS_AUDIO patch。

        流程:
          1. 确定 voice（优先 ctx.voice，其次 ctx.lang→VOICE_MAP，最后 self._voice）
          2. 确定 rate
          3. 调用 EdgeTTSEngine.synthesize(text, output_path, rate=rate)
          4. 返回 Patch（标记 generation_mode=fallback）
        """
        voice = ctx.voice or self._resolve_voice(ctx.lang) or self._voice
        engine = self._get_or_create_engine(voice)
        output_path = self._make_output_path(ctx.segment_id)

        duration = engine.synthesize(
            text=ctx.translation_text,
            output_path=output_path,
            rate=ctx.rate,
        )

        duration_fit = self._calc_duration_fit(duration, ctx.duration_target)

        return Patch(
            id=f"tts_edge_{ctx.segment_id}",
            target_id=ctx.segment_id,
            op=OpCode.UPDATE_TTS_AUDIO,
            value={
                "audio_ref": output_path,
                "duration": round(duration, 3),
                "duration_target": ctx.duration_target,
                "duration_fit_score": duration_fit,
                "availability_score": 0.99,
                "language_coverage_score": 0.99 if voice else 0.80,
                "quality_score": round(0.60 + 0.15 * duration_fit, 4),
                "engine": "edge_tts",
                "voice": voice,
                "rate": ctx.rate,
                "generation_mode": "fallback",
                "fallback_reason": ctx.fallback_reason or "last_resort",
            },
            author="system",
            confidence=round(0.60 + 0.10 * duration_fit, 4),
        )

    def _get_or_create_engine(self, voice: str):
        if self._engine is not None:
            return self._engine
        from pipeline.tts_edge import EdgeTTSEngine
        self._engine = EdgeTTSEngine(voice=voice or "zh-CN-XiaoxiaoNeural")
        return self._engine

    def _make_output_path(self, segment_id: str) -> str:
        import os
        d = self._output_dir or "."
        return os.path.join(d, "tts", f"{segment_id}_edge.wav")

    @classmethod
    def _resolve_voice(cls, lang: str) -> str:
        """从 lang 自动匹配 EDGE_VOICE_MAP。"""
        if not lang:
            return ""
        for key in (lang, lang.lower().replace("-", ""), lang[:2]):
            if key in cls._VOICE_MAP:
                return cls._VOICE_MAP[key]
        return ""

    @staticmethod
    def _calc_duration_fit(actual: float, target: float) -> float:
        if target <= 0:
            return 1.0
        dev = abs(actual - target) / target
        return round(max(0.0, 1.0 - dev / 0.5), 4)
