"""
CosyVoice 2.0/3.0 离线 TTS 引擎 — CosyVoiceTTSEngine

基于 FunAudioLLM/CosyVoice 的 zero-shot 语音合成引擎。
一次加载模型，通过参考音频 + 提示文本指定说话人音色。
inference_zero_shot() 调用完整链路（LLM + Flow + HiFT-GAN），
产生清晰度远超 ChatTTS 的合成语音（中文 CER 0.81%）。

用法:
    engine = CosyVoiceTTSEngine(
        model_version="v3",
        prompt_audio="speaker.wav",
        prompt_text="参考音频的文字转录",
    )
    duration = engine.synthesize("你好世界", "output.wav")
    engine.reset_speaker(prompt_audio="new_speaker.wav", prompt_text="新转录")
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from typing import List, Optional

import torch
import torchaudio

from pipeline.logger import get_logger

logger = get_logger(__name__)

# CosyVoice C 扩展 / PyTorch CUDA 算子均非线程安全。
# 保护模型加载、prompt 准备和所有推理调用（inference_zero_shot）。
_COSYVOICE_TTS_LOCK = threading.Lock()

# CosyVoice 3.0 zero-shot 模式要求 prompt_text 以助手模板前缀开头
_CV3_PROMPT_PREFIX = "You are a helpful assistant.<|endofprompt|>"


class CosyVoiceTTSEngine:
    """CosyVoice 离线 TTS 引擎 — zero-shot 语音合成。

    模型懒加载：第一次 synthesize 调用或显式 warmup() 时加载，之后复用。
    音色由 prompt_audio + prompt_text 控制（zero-shot 说话人克隆）。

    用法:
        engine = CosyVoiceTTSEngine(
            model_version="v3",
            prompt_audio="reference.wav",
            prompt_text="参考音频中说话人的文字内容",
        )
        engine.warmup()
        engine.synthesize("要合成的文本", "output.wav")
        engine.cleanup()
    """

    _VERSION_PATH_MAP = {
        "v2": "./models/CosyVoice2-0.5B",
        "v3": "./models/CosyVoice3-0.5B",
    }

    def __init__(
        self,
        model_version: str = "v3",
        model_path: str = "",
        prompt_audio: Optional[str] = None,
        prompt_text: Optional[str] = None,
        fp16: bool = True,
        default_speed: float = 1.0,
    ):
        self._model_version = model_version
        self._model_path = model_path or self._VERSION_PATH_MAP.get(
            model_version, "./models/CosyVoice2-0.5B"
        )
        self._prompt_audio_path: Optional[str] = prompt_audio
        self._prompt_text: Optional[str] = prompt_text
        self._fp16 = fp16
        self._default_speed = max(0.5, min(2.0, default_speed))

        self._model: Optional[object] = None  # CosyVoice2/3 instance
        self._prompt_audio: Optional[torch.Tensor] = None  # 16 kHz mono
        self._prompt_wav_path: Optional[str] = None  # 处理后的临时 WAV 路径
        self._loaded = False

    @property
    def model_loaded(self) -> bool:
        return self._loaded

    # ------------------------------------------------------------------
    # BaseTTSEngine Protocol
    # ------------------------------------------------------------------

    def synthesize(
        self,
        text: str,
        output_path: str,
        rate: str = "+0%",
        emotion: Optional["EmotionStyle"] = None,  # type: ignore
    ) -> float:
        """合成语音，返回音频时长（秒）。

        rate 格式为 "+N%" 或 "-N%"，转换为 CosyVoice speed 参数
        （1.0=原速，>1 加速，<1 减速）。
        """
        self._load_model()
        self._ensure_prompt()
        assert self._model is not None

        speed = self._parse_rate(rate)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        # CosyVoice 3.0 需要助手模板前缀
        prompt_text = self._prompt_text or ""
        if self._model_version == "v3" and not prompt_text.startswith(_CV3_PROMPT_PREFIX):
            prompt_text = _CV3_PROMPT_PREFIX + prompt_text

        # inference_zero_shot 要求 prompt_wav 为文件路径（非 tensor）。
        # _ensure_prompt() 已将处理后的 16kHz mono 音频写入 self._prompt_wav_path。
        assert self._prompt_wav_path is not None

        try:
            with _COSYVOICE_TTS_LOCK:
                generator = self._model.inference_zero_shot(
                    text,
                    prompt_text,
                    self._prompt_wav_path,
                    stream=False,
                    speed=speed,
                )
                for _, result in enumerate(generator):
                    tts_speech = result["tts_speech"]
                    speech_cpu = tts_speech.cpu()
                    sample_rate = self._model.sample_rate
                    torchaudio.save(output_path, speech_cpu, sample_rate)
                    duration = float(speech_cpu.shape[1]) / sample_rate
                    del tts_speech, speech_cpu
                    break
                else:
                    raise RuntimeError("CosyVoice inference_zero_shot 返回空结果")

            # 每次推理后释放 CUDA 缓存碎片
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
            return duration

        except Exception as e:
            raise RuntimeError(f"CosyVoice 合成失败: {e}") from e

    def get_voices(self) -> List[str]:
        return []

    def supports_rate(self) -> bool:
        """CosyVoice 原生支持 speed 参数（mel spectrogram 线性插值）。"""
        return True

    def supports_emotion(self) -> bool:
        return False

    def emotion_modes(self) -> List[str]:
        return []

    # ------------------------------------------------------------------
    # Engine lifecycle
    # ------------------------------------------------------------------

    def warmup(self) -> None:
        """预加载模型并准备 prompt 音频。

        必须在 TtsPipeline 线程池创建前调用，避免多线程并发 CUDA 操作
        导致 C 级堆损坏。
        """
        self._load_model()
        self._ensure_prompt()
        logger.info("CosyVoice TTS 引擎预热完成")

    def cleanup(self) -> None:
        """释放 GPU 模型和临时文件，归还显存。"""
        if self._model is not None:
            del self._model
            self._model = None
        self._loaded = False
        self._prompt_audio = None
        # 删除 _ensure_prompt() 写入的处理后音频临时文件
        if self._prompt_wav_path and os.path.isfile(self._prompt_wav_path):
            try:
                os.unlink(self._prompt_wav_path)
            except OSError:
                pass
            self._prompt_wav_path = None
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass
        import gc
        gc.collect()

    def reset_speaker(
        self,
        prompt_audio: Optional[str] = None,
        prompt_text: Optional[str] = None,
    ) -> None:
        """更换参考说话人。

        prompt_audio=None 时保留原音频路径。
        prompt_text=None 时保留原提示文本。
        """
        if prompt_audio is not None:
            self._prompt_audio_path = prompt_audio
        if prompt_text is not None:
            self._prompt_text = prompt_text
        self._prompt_audio = None  # 强制重新加载 prompt
        # 清理旧的临时文件，下次 _ensure_prompt() 会重新生成
        if self._prompt_wav_path and os.path.isfile(self._prompt_wav_path):
            try:
                os.unlink(self._prompt_wav_path)
            except OSError:
                pass
            self._prompt_wav_path = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _parse_rate(self, rate_str: str) -> float:
        """'+40%' → 1.4, '-20%' → 0.8, '+0%' → 1.0"""
        s = rate_str.strip()
        if s.endswith("%"):
            try:
                pct = float(s[:-1].replace("+", "")) / 100.0
                speed = 1.0 + pct
                return max(0.5, min(2.0, speed))
            except ValueError:
                pass
        return 1.0

    def _load_model(self) -> None:
        """懒加载 CosyVoice 模型。"""
        if self._loaded and self._model is not None:
            return

        with _COSYVOICE_TTS_LOCK:
            if self._loaded and self._model is not None:
                return

            # Python version gate
            if sys.version_info >= (3, 11):
                msg = (
                    f"CosyVoice 需要 Python <= 3.10，当前 Python "
                    f"{sys.version_info.major}.{sys.version_info.minor}。"
                    f"请切换到 Python 3.10 环境。"
                )
                logger.error(msg)
                raise RuntimeError(msg)

            # Reuse the module-level pre-imports from vc_cosyvoice
            from pipeline.vc_cosyvoice import CosyVoice2, CosyVoice3

            if self._model_version == "v3" and CosyVoice3 is not None:
                self._model = CosyVoice3(self._model_path, fp16=self._fp16)
            elif self._model_version == "v2" and CosyVoice2 is not None:
                self._model = CosyVoice2(self._model_path, fp16=self._fp16)
            elif CosyVoice3 is not None:
                self._model = CosyVoice3(self._model_path, fp16=self._fp16)
            elif CosyVoice2 is not None:
                self._model = CosyVoice2(self._model_path, fp16=self._fp16)
            else:
                raise ImportError(
                    "CosyVoice 模型未安装。请克隆 FunAudioLLM/CosyVoice 仓库"
                    "并安装其依赖到 models/CosyVoice/。"
                )

            self._loaded = True
            logger.info(
                "CosyVoice %s 模型加载完成 (path=%s)",
                self._model_version,
                self._model_path,
            )

    def _ensure_prompt(self) -> None:
        """加载并缓存参考音频。"""
        if self._prompt_audio is not None:
            return

        if not self._prompt_audio_path or not os.path.isfile(self._prompt_audio_path):
            raise RuntimeError(
                f"CosyVoice TTS 参考音频不存在: {self._prompt_audio_path}"
            )

        with _COSYVOICE_TTS_LOCK:
            if self._prompt_audio is not None:
                return

            wav, sr = torchaudio.load(self._prompt_audio_path)
            if sr != 16000:
                wav = torchaudio.functional.resample(wav, sr, 16000)
            if wav.shape[0] > 1:
                wav = wav.mean(dim=0, keepdim=True)
            # 截取前 30 秒（CosyVoice speech token 提取限制）
            max_samples = 30 * 16000
            if wav.shape[1] > max_samples:
                wav = wav[:, :max_samples]
            self._prompt_audio = wav
            logger.info("CosyVoice TTS prompt 音频已加载: %s", self._prompt_audio_path)

            # inference_zero_shot() 要求 prompt_wav 为文件路径（非 tensor），
            # 将处理后的 16kHz mono ≤30s 音频写入持久临时文件，所有合成调用复用。
            tmp = tempfile.NamedTemporaryFile(
                prefix="cosyvoice_prompt_", suffix=".wav", delete=False
            )
            torchaudio.save(tmp.name, wav, 16000)
            self._prompt_wav_path = tmp.name


class CosyVoiceTTSEngineFactory:
    """CosyVoiceTTSEngine 工厂方法。"""

    @staticmethod
    def from_config(config) -> CosyVoiceTTSEngine:
        return CosyVoiceTTSEngine(
            model_version=getattr(config, "cosyvoice_tts_model_version", "v3"),
            model_path=getattr(
                config, "cosyvoice_tts_model_path", "./models/CosyVoice2-0.5B"
            ),
            prompt_audio=getattr(config, "cosyvoice_tts_prompt_audio", None),
            prompt_text=getattr(config, "cosyvoice_tts_prompt_text", None),
            fp16=getattr(config, "cosyvoice_tts_fp16", True),
            default_speed=getattr(config, "cosyvoice_tts_speed", 1.0),
        )
