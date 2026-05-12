"""
ChatTTS 离线引擎实现 — ChatTTSEngine

基于 ChatTTS（2noise/ChatTTS）的离线语音合成引擎。
一次加载模型，后续调用复用缓存。spk_emb 在首次合成时生成并缓存，
确保同一视频所有段落的音色一致。

用法:
    engine = ChatTTSEngine(speaker_seed=42)
    duration = engine.synthesize("你好世界", "output.wav")
    engine.reset_speaker(seed=99)  # 换一个声音
"""

from __future__ import annotations

import os
import random
import re
import threading
from typing import List, Optional

import numpy as np

from pipeline.logger import get_logger

logger = get_logger(__name__)

# 保护 ChatTTS 模型加载 + spk_emb 生成的全局锁
# _load_model() 修改 PyTorch/CUDA 状态，_ensure_spk_emb() 修改 np.random 全局状态
# 多线程并发调用会导致 C 级堆损坏 (STATUS_HEAP_CORRUPTION 0xC0000374)
_LOAD_LOCK = threading.Lock()

_DIGIT_MAP = {"0": "零", "1": "一", "2": "二", "3": "三", "4": "四",
              "5": "五", "6": "六", "7": "七", "8": "八", "9": "九"}
_UNITS = ["", "十", "百", "千"]
_BIG_UNITS = ["", "万", "亿"]


def _segment_to_chinese(seg: str) -> str:
    """Convert up to 4-digit segment to Chinese (e.g. '1234' → '一千二百三十四')."""
    if not seg:
        return ""
    n = len(seg)
    result = ""
    for i, ch in enumerate(seg):
        d = _DIGIT_MAP[ch]
        unit = _UNITS[n - i - 1] if n - i - 1 > 0 else ""
        if d == "零":
            if result and not result.endswith("零"):
                result += "零"
            continue
        result += d + unit
    result = result.rstrip("零")
    if not result and seg.startswith("0"):
        result = "零"
    return result


def _arabic_to_chinese(num_str: str) -> str:
    """Convert Arabic numeral string to Chinese reading. e.g. '123' → '一百二十三'."""
    if not num_str:
        return num_str
    num_str = num_str.lstrip("0") or "0"
    # Split into 4-digit groups from right
    groups = []
    s = num_str
    while s:
        groups.append(s[-4:])
        s = s[:-4]
    groups.reverse()

    result = ""
    for i, g in enumerate(groups):
        seg = _segment_to_chinese(g)
        if seg == "零":
            if result and not result.endswith("零"):
                result += "零"
            continue
        # Insert 零 when segment starts with zeros (e.g. 10001 → 一万零一)
        if i > 0 and g != "0" * len(g) and g.lstrip("0") != g:
            result += "零"
        big_idx = len(groups) - i - 1
        big = _BIG_UNITS[big_idx] if big_idx < len(_BIG_UNITS) else ""
        result += seg + big
    result = result.rstrip("零")
    # Clean up: "一十" → "十" at start
    if result.startswith("一十"):
        result = result[1:]
    return result or "零"


def _normalize_numbers(text: str) -> str:
    """Replace Arabic numerals with Chinese readings for ChatTTS compatibility."""
    return re.sub(r"\d+", lambda m: _arabic_to_chinese(m.group()), text)


def _apply_pronunciation(text: str, entries: dict) -> str:
    """Apply pronunciation dictionary entries (simple key → value replacement)."""
    for key, value in entries.items():
        text = text.replace(key, value)
    return text


class ChatTTSEngine:
    """ChatTTS 离线 TTS 引擎。

    模型懒加载：第一次 synthesize 调用时加载，之后复用。
    spk_emb 缓存：首次合成时生成说话人嵌入，后续段落复用，
    确保同一视频所有字幕段落音色一致。

    用法:
        engine = ChatTTSEngine(speaker_seed=42)
        engine.synthesize("你好", "output.wav")
        engine.reset_speaker(seed=None)  # 随机换音色
    """

    def __init__(
        self,
        speaker_seed: Optional[int] = None,
        model_source: str = "local",
        model_path: Optional[str] = None,
        use_decoder: bool = True,
        sample_rate: int = 24000,
        pronunciation_entries: Optional[dict] = None,
    ):
        self._speaker_seed = speaker_seed
        self._model_source = model_source
        self._model_path = model_path
        self._use_decoder = use_decoder
        self._sample_rate = sample_rate
        self._pronunciation_entries = pronunciation_entries or {}

        self._chat: Optional["ChatTTS.Chat"] = None  # type: ignore
        self._loaded = False
        self._spk_emb = None  # 缓存的说话人嵌入

    @property
    def model_loaded(self) -> bool:
        return self._loaded

    @property
    def speaker_seed(self) -> Optional[int]:
        return self._speaker_seed

    def reset_speaker(self, seed: Optional[int] = None) -> None:
        """更换说话人：清除缓存嵌入并重新生成。

        seed=None 时随机生成新音色；不需重新加载模型。
        """
        self._speaker_seed = seed
        self._spk_emb = None

    def _load_model(self) -> None:
        """懒加载 ChatTTS 模型（不含 speaker 初始化）。

        使用全局锁串行化加载：多线程并发 load() 会触发 PyTorch/CUDA
        C 扩展竞争，在 Windows 上导致堆损坏 (STATUS_HEAP_CORRUPTION)。
        """
        if self._loaded and self._chat is not None:
            return

        with _LOAD_LOCK:
            if self._loaded and self._chat is not None:
                return

            from pipeline.model_manager import ModelManager

            import ChatTTS
            from ChatTTS import Chat

            chat = Chat()
            load_kwargs = {"source": self._model_source, "compile": False}

            if self._model_source == "custom" and self._model_path:
                load_kwargs["custom_path"] = self._model_path
            elif self._model_source == "local":
                status = ModelManager.check("chattts")
                if status.exists:
                    load_kwargs["custom_path"] = status.path

            chat.load(**load_kwargs)
            self._chat = chat
            self._loaded = True
            logger.info("ChatTTS 模型加载完成")

    def _ensure_spk_emb(self):
        """生成并缓存说话人嵌入。首次调用时执行。

        指定 seed → np.random.seed() 固定 → 确定性音色
        seed=None → 系统随机 seed → 随机但同视频一致的音色

        使用全局锁：np.random.seed() 修改全局 numpy 随机状态，
        多线程并发调用会导致竞态条件。
        """
        if self._spk_emb is not None:
            return
        assert self._chat is not None

        with _LOAD_LOCK:
            if self._spk_emb is not None:
                return

            if self._speaker_seed is not None:
                np.random.seed(self._speaker_seed)
            else:
                self._speaker_seed = random.randint(0, 2 ** 31 - 1)
                np.random.seed(self._speaker_seed)

            self._spk_emb = self._chat.sample_random_speaker()

    def warmup(self) -> None:
        """预加载模型并生成说话人嵌入（线程安全，主线程调用）。

        在 TtsPipeline 线程池创建前调用，避免多线程并发
        _load_model() 导致的 C 级堆损坏。
        """
        self._load_model()
        self._ensure_spk_emb()
        logger.info("ChatTTS 引擎预热完成")

    def synthesize(
        self,
        text: str,
        output_path: str,
        rate: str = "+0%",
        emotion: Optional["EmotionStyle"] = None,  # type: ignore
    ) -> float:
        """合成语音，返回音频时长（秒）。

        rate 参数接受但忽略（ChatTTS 不支持语速调节）。
        语速对齐由下游视频变速（slow_down_video_to_file）处理。
        """
        import ChatTTS
        import soundfile as sf
        from ChatTTS import Chat

        self._load_model()
        self._ensure_spk_emb()
        assert self._chat is not None
        assert self._spk_emb is not None

        # 发音术语表替换 → 数字归一化 → ChatTTS 推理
        if self._pronunciation_entries:
            text = _apply_pronunciation(text, self._pronunciation_entries)
        text = _normalize_numbers(text)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        try:
            params_infer_code = Chat.InferCodeParams()
            params_infer_code.spk_emb = self._spk_emb

            wavs = self._chat.infer(
                text,
                skip_refine_text=False,
                use_decoder=self._use_decoder,
                do_text_normalization=True,
                split_text=False,
                params_infer_code=params_infer_code,
            )

            if not wavs or len(wavs) == 0:
                raise RuntimeError("ChatTTS 推理返回空结果")

            audio_data = wavs[0]
            sf.write(output_path, audio_data, self._sample_rate)
            return float(len(audio_data) / self._sample_rate)

        except Exception as e:
            raise RuntimeError(f"ChatTTS 合成失败: {e}") from e

    def cleanup(self) -> None:
        """释放 GPU 模型，归还显存。"""
        if self._chat is not None:
            del self._chat
            self._chat = None
        self._loaded = False
        self._spk_emb = None
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass
        import gc
        gc.collect()

    def get_voices(self) -> List[str]:
        return []

    def supports_rate(self) -> bool:
        return False

    def supports_emotion(self) -> bool:
        return False

    def emotion_modes(self) -> List[str]:
        return []


class ChatTTSEngineFactory:
    """ChatTTSEngine 工厂方法。"""

    @staticmethod
    def from_config(config) -> ChatTTSEngine:
        return ChatTTSEngine(
            speaker_seed=getattr(config, "chattts_speaker_seed", None),
            model_source=getattr(config, "chattts_model_source", "local"),
            model_path=getattr(config, "chattts_model_path", None),
            pronunciation_entries=getattr(config, "tts_pronunciation", {}),
        )
