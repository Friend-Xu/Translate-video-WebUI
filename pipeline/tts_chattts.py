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

import logging
import os
import random
import re
import threading
from typing import List, Optional

import numpy as np

from pipeline.logger import get_logger

logger = get_logger(__name__)

# ChatTTS 全局锁：保护模型加载、spk_emb 生成、以及推理调用。
# _load_model() / _ensure_spk_emb() 修改 PyTorch/CUDA/np.random 全局状态，
# _chat.infer() 也涉及非线程安全的 CUDA 算子。
# 多线程并发任意 ChatTTS 操作（包括不同 Chat 实例）均可能在 Windows 上
# 导致 C 级堆损坏 (STATUS_HEAP_CORRUPTION 0xC0000374)。
_CHATTS_LOCK = threading.Lock()

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


_wetext_normalizer = None


def _get_wetext_normalizer():
    """Lazy-load wetext Normalizer (WeTextProcessing without pynini, works on Windows)."""
    global _wetext_normalizer
    if _wetext_normalizer is None:
        try:
            from wetext import Normalizer
            _wetext_normalizer = Normalizer(lang="zh", operator="tn", remove_erhua=True)
            logger.info("wetext 文本规范化器已加载（零外部依赖）")
        except ImportError:
            logger.warning("wetext 未安装，回退到正则规范化")
            _wetext_normalizer = False
    return _wetext_normalizer


_PUNCT_MAP = {
    "？": "?",
    "！": "!",
    "：": ":",
    "；": ";",
    "…": "...",
    "～": "~",
    "、": ",",
    "“": "\"",  # "
    "”": "\"",  # "
    "‘": "'",   # '
    "’": "'",   # '
    "《": "",    # 《
    "》": "",    # 》
    "【": "",    # 【
    "】": "",    # 】
    "（": "(",   # （
    "）": ")",   # ）
}


def _clean_punctuation(text: str) -> str:
    """Convert Chinese punctuation to ASCII that ChatTTS handles safely.

    Applied after text normalization to prevent ChatTTS from misreading
    fullwidth punctuation as control tokens or producing artifacts.
    """
    text = text.replace("——", "，")  # —— → ，
    text = text.replace("—", "，")         # — → ，
    for ch, repl in _PUNCT_MAP.items():
        text = text.replace(ch, repl)
    return text


def _normalize_text(text: str) -> str:
    """Normalize text for ChatTTS using wetext (pynini-free WeTextProcessing).

    Pipeline: wetext normalization (dates/numbers) → punctuation cleaning.
    Falls back to regex-based normalization if wetext is unavailable.
    """
    norm = _get_wetext_normalizer()
    if norm:
        text = norm.normalize(text)
        return _clean_punctuation(text)

    # Fallback: regex-based normalization for core number patterns
    text = re.sub(r"(\d+(?:\.\d+)?)%",
                  lambda m: "百分之" + _arabic_to_chinese(m.group(1).split(".")[0])
                  + ("点" + _decimal_to_chinese(m.group(1).split(".")[1]) if "." in m.group(1) else ""), text)
    text = re.sub(r"(\d+)\.(\d+)",
                  lambda m: _arabic_to_chinese(m.group(1)) + "点" + _decimal_to_chinese(m.group(2)), text)
    text = re.sub(r"\d+", lambda m: _arabic_to_chinese(m.group()), text)
    return _clean_punctuation(text)


def _decimal_to_chinese(num_str: str) -> str:
    """Convert decimal fraction part to digit-by-digit Chinese reading. e.g. '19' → '一九'."""
    return "".join(_DIGIT_MAP.get(ch, ch) for ch in num_str)


def _apply_pronunciation(text: str, entries: dict) -> str:
    """Apply pronunciation dictionary entries (simple key → value replacement)."""
    for key, value in entries.items():
        text = text.replace(key, value)
    return text


class ChatTTSEngine:
    """ChatTTS 离线 TTS 引擎。

    模型懒加载：第一次 synthesize 调用时加载，之后复用。
    spk_emb 缓存：可传入预存的 spk_emb 直接复用音色，跳过随机生成。
    未提供则根据 speaker_seed 生成，确保同一视频所有字幕段落音色一致。

    用法:
        engine = ChatTTSEngine(speaker_seed=42)
        engine.synthesize("你好", "output.wav")
        engine.reset_speaker(seed=None)  # 随机换音色

        # 持久化复用音色
        emb = engine.spk_emb           # 保存到配置
        engine2 = ChatTTSEngine(spk_emb=emb)  # 下次直接用
    """

    def __init__(
        self,
        speaker_seed: Optional[int] = None,
        model_source: str = "local",
        model_path: Optional[str] = None,
        use_decoder: bool = True,
        sample_rate: int = 24000,
        pronunciation_entries: Optional[dict] = None,
        spk_emb: Optional[str] = None,
        speaker_pt: Optional[str] = None,
    ):
        self._speaker_seed = speaker_seed
        self._model_source = model_source
        self._model_path = model_path
        self._use_decoder = use_decoder
        self._sample_rate = sample_rate
        self._pronunciation_entries = pronunciation_entries or {}

        self._chat: Optional["ChatTTS.Chat"] = None  # type: ignore
        self._loaded = False

        # PT 文件加载 > 预存 spk_emb > seed 随机生成
        if speaker_pt and os.path.isfile(speaker_pt):
            import torch
            self._spk_emb = torch.load(speaker_pt, map_location="cpu", weights_only=True)
            logger.info("从 PT 文件加载音色: %s", speaker_pt)
        else:
            self._spk_emb = spk_emb  # 预存的说话人嵌入（持久化恢复）

    @property
    def model_loaded(self) -> bool:
        return self._loaded

    @property
    def speaker_seed(self) -> Optional[int]:
        return self._speaker_seed

    @property
    def spk_emb(self) -> Optional[str]:
        """缓存的说话人嵌入字符串，可持久化到配置以跨会话复用音色。"""
        return self._spk_emb

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

        with _CHATTS_LOCK:
            if self._loaded and self._chat is not None:
                return

            from pipeline.model_manager import ModelManager

            import ChatTTS
            from ChatTTS import Chat

            # 静默 ChatTTS 库内部 DEBUG 日志（每段推理 ~20 条重复 start/finis xxx）
            logging.getLogger("ChatTTS").setLevel(logging.WARNING)

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

        with _CHATTS_LOCK:
            if self._spk_emb is not None:
                return

            if self._speaker_seed is not None:
                np.random.seed(self._speaker_seed)
            else:
                self._speaker_seed = random.randint(0, 2 ** 31 - 1)
                np.random.seed(self._speaker_seed)

            self._spk_emb = self._chat.sample_random_speaker()

    def warmup(self) -> None:
        """预加载模型并生成说话人嵌入（主线程调用）。

        必须在 TtsPipeline 线程池创建前调用，避免多线程并发
        ChatTTS PyTorch/CUDA 操作导致 C 级堆损坏。
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

        # 发音术语表替换 → 文本规范化 → ChatTTS 推理
        if self._pronunciation_entries:
            text = _apply_pronunciation(text, self._pronunciation_entries)
        text = _normalize_text(text)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        try:
            params_infer_code = Chat.InferCodeParams(
                spk_emb=self._spk_emb,
                temperature=0.3,
                top_P=0.7,
                top_K=20,
            )
            params_refine_text = Chat.RefineTextParams(
                prompt="[oral_0][break_5]",
            )

            with _CHATTS_LOCK:
                wavs = self._chat.infer(
                    text,
                    skip_refine_text=False,
                    use_decoder=self._use_decoder,
                    do_text_normalization=False,  # done externally via _normalize_text()
                    split_text=False,
                    params_infer_code=params_infer_code,
                    params_refine_text=params_refine_text,
                )

            if not wavs or len(wavs) == 0:
                raise RuntimeError("ChatTTS 推理返回空结果")

            wav = wavs[0]
            if hasattr(wav, "detach"):
                wav = wav.detach().cpu().numpy()
            audio_data = np.asarray(wav, dtype=np.float32).copy()
            del wavs, wav
            sf.write(output_path, audio_data, self._sample_rate)
            duration = float(len(audio_data) / self._sample_rate)
            del audio_data
            # 每次推理后立即释放 CUDA 缓存碎片，防止逐段累积导致 OOM
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass
            return duration

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
            speaker_pt=getattr(config, "chattts_speaker_pt", None),
        )
