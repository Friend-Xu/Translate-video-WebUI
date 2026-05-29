"""
CosyVoiceAdapter — CosyVoice → Patch 适配器 (Chapter 6 §6.2-6.3)

封装现有 CosyVoiceTTSEngine 子进程隔离协议，不做修改。
CosyVoice 定位为"可控的生产级主配音引擎"——零样本克隆 + 原生 speed + 跨语种。
"""
from __future__ import annotations
from dataclasses import dataclass
from core.runtime.patch import Patch, OpCode
from core.ir.speaker import SpeakerNodeIR


@dataclass
class CosyVoiceSegmentContext:
    """CosyVoice 结构化输入 — 零样本克隆 + 跨语种 segment 上下文。

    复用 ChatTTS TTSSegmentContext 的核心字段，
    扩展 prompt_audio、lang、speed、model_version 等 CosyVoice 特有字段。
    """
    segment_id: str
    translation_text: str
    source_text: str = ""
    speaker_id: str | None = None
    speaker_embedding_ref: str = ""     # prompt_audio 文件路径
    prompt_text: str = ""               # prompt_audio 对应的文本
    emotion_hint: str = "neutral"
    prosody_hint: dict | None = None
    duration_target: float = 0.0
    duration_tolerance: float = 0.15
    semantic_embedding_ref: str = ""
    prev_segment_id: str = ""
    next_segment_id: str = ""
    # CosyVoice 特有字段
    lang: str = ""                      # 目标语言标签 (zh/en/ja/ko/yue)
    model_version: str = "v2"           # v2 | v3
    speed: float = 1.0                 # 语速 0.5-2.0
    mode: str = "cross_lingual"        # cross_lingual | zero_shot


class CosyVoiceAdapter:
    """将 CosyVoice 输出转为 UPDATE_TTS_AUDIO patch。

    封装现有 CosyVoiceTTSEngine 子进程协议，不做修改。
    支持零样本克隆（prompt_audio）、原生 speed 控制、跨语种配音。
    """

    _VALID_LANGS = {"zh", "en", "ja", "ko", "yue"}

    def __init__(self, model_version: str = "v2",
                 prompt_audio: str | None = None,
                 prompt_text: str | None = None,
                 output_dir: str = "",
                 fp16: bool = True,
                 default_speed: float = 1.0,
                 lang: str = ""):
        self._model_version = model_version
        self._prompt_audio = prompt_audio
        self._prompt_text = prompt_text
        self._output_dir = output_dir
        self._fp16 = fp16
        self._default_speed = max(0.5, min(2.0, default_speed))
        self._lang = self._normalize_lang(lang)
        self._engine = None

    def configure(self, event_config = None):
        if not event_config: return
        if "lang" in event_config: self._lang = event_config["lang"]
        if "cosy_lang" in event_config: self._lang = event_config["cosy_lang"]
        if "speed" in event_config: self._speed = event_config["speed"]
        if "speed_factor" in event_config: self._speed = event_config["speed_factor"]
        if "cosy_version" in event_config: self._version = event_config["cosy_version"]
        if "cosy_num_norm" in event_config: self._num_norm = event_config["cosy_num_norm"]
        if "cosy_fp16" in event_config: self._fp16 = event_config["cosy_fp16"]

    def synthesize(self, ctx: CosyVoiceSegmentContext) -> Patch:
        """对单个 segment 合成语音，返回 UPDATE_TTS_AUDIO patch。

        流程:
          1. 从 ctx 构建 speed/language/mode 参数
          2. 调用 CosyVoiceTTSEngine.synthesize(text, output_path, rate=speed_str)
          3. 计算各项评分
          4. 返回 Patch
        """
        from pipeline.tts_cosyvoice import CosyVoiceTTSEngine

        engine = self._get_or_create_engine(ctx)
        output_path = self._make_output_path(ctx.segment_id)

        speed = ctx.speed if ctx.speed > 0 else self._default_speed
        rate_str = self._speed_to_rate_str(speed)

        lang = self._normalize_lang(ctx.lang) or self._lang
        if lang:
            engine._lang = lang
        if ctx.mode:
            engine._tts_mode = ctx.mode

        duration = engine.synthesize(
            text=ctx.translation_text,
            output_path=output_path,
            rate=rate_str,
        )

        duration_fit = self._calc_duration_fit(duration, ctx.duration_target)
        quality = self._estimate_quality(duration_fit)

        return Patch(
            id=f"tts_cv_{ctx.segment_id}",
            target_id=ctx.segment_id,
            op=OpCode.UPDATE_TTS_AUDIO,
            value={
                "audio_ref": output_path,
                "duration": round(duration, 3),
                "duration_target": ctx.duration_target,
                "duration_fit_score": duration_fit,
                "speaker_match_score": 0.90,
                "language_naturalness_score": 0.88,
                "quality_score": quality,
                "engine": "cosyvoice",
                "model_version": ctx.model_version or self._model_version,
                "lang": lang or ctx.lang,
                "speed": speed,
                "mode": ctx.mode,
                "prompt_audio": self._prompt_audio,
            },
            author="system",
            confidence=quality,
        )

    def bind_speaker(self, speaker_node: SpeakerNodeIR) -> None:
        """通过 prompt_audio 绑定 speaker identity。

        从 SpeakerNodeIR.embedding_ref 读取 prompt 音频路径。
        若 embedding_ref 为空则使用 voice_style 作为 prompt_text。
        """
        if speaker_node.embedding_ref:
            import os
            if os.path.isfile(speaker_node.embedding_ref):
                self._prompt_audio = speaker_node.embedding_ref
        if speaker_node.voice_style:
            self._prompt_text = speaker_node.voice_style

    def reset_speaker(self, prompt_audio: str, prompt_text: str = "") -> None:
        """切换 prompt 音频（用于多角色场景）。"""
        self._prompt_audio = prompt_audio
        self._prompt_text = prompt_text
        if self._engine is not None:
            self._engine.reset_speaker(
                prompt_audio=prompt_audio,
                prompt_text=prompt_text,
            )

    @staticmethod
    def _normalize_lang(lang: str) -> str:
        if not lang:
            return ""
        raw = lang.lower().replace("-", "").replace("_", "")
        if raw in CosyVoiceAdapter._VALID_LANGS:
            return raw
        for valid in ("zh", "yue", "ja", "ko", "en"):
            if raw.startswith(valid) or valid in raw:
                return valid
        if len(raw) >= 2 and raw[:2] in CosyVoiceAdapter._VALID_LANGS:
            return raw[:2]
        return ""

    def _get_or_create_engine(self, ctx: CosyVoiceSegmentContext):
        if self._engine is None:
            from pipeline.tts_cosyvoice import CosyVoiceTTSEngine
            mv = ctx.model_version or self._model_version
            self._engine = CosyVoiceTTSEngine(
                model_version=mv,
                prompt_audio=self._prompt_audio,
                prompt_text=self._prompt_text,
                fp16=self._fp16,
                default_speed=self._default_speed,
                tts_mode=ctx.mode,
                lang=ctx.lang or self._lang,
            )
            self._engine.warmup()
        return self._engine

    def _make_output_path(self, segment_id: str) -> str:
        import os
        d = self._output_dir or "."
        return os.path.join(d, "03_tts", f"{segment_id}_cosyvoice.wav")

    @staticmethod
    def _speed_to_rate_str(speed: float) -> str:
        """将 speed 倍率 (0.5-2.0) 转为 CosyVoice rate 百分比字符串。"""
        pct = round((speed - 1.0) * 100)
        if pct >= 0:
            return f"+{pct}%"
        return f"{pct}%"

    @staticmethod
    def _calc_duration_fit(actual: float, target: float) -> float:
        if target <= 0:
            return 1.0
        dev = abs(actual - target) / target
        return round(max(0.0, 1.0 - dev / 0.5), 4)

    @staticmethod
    def _estimate_quality(duration_fit: float) -> float:
        """综合质量估算 — duration_fit 占主导，其他维度 placeholder。"""
        return round(0.75 + 0.25 * duration_fit, 4)
