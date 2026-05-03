"""
Wav2Vec2Aligner — 基于 whisperX 的 wav2vec2 强制对齐器

使用 whisperx_local.alignment （从 whisperX 剥离的 alignment.py）进行
音频-文本强制对齐，获得精准的词级时间戳。

这不是我的原始实现，而是 whisperX 的 load_align_model + align 的封装。

用法:
    aligner = Wav2Vec2Aligner(language="ja", device="cpu")
    aligned = aligner.align(segments, audio_array)
    # aligned["segments"] -> [{text, start, end, words: [{word, start, end}]}]

依赖:
    pip install transformers torch numpy nltk
    # whisperx_local/ 已内置（从 whisperX 剥离，无需安装完整 whisperX）

对比 faster-whisper 的词级时间戳:
    faster-whisper 的 word_timestamps 是根据注意力权重估算的，精度一般。
    wav2vec2 CTC 强制对齐是在给定文本的前提下精确对齐音频帧，
    时间戳精度更高（帧级别，~20ms），且不会出现漂移。
"""

import os
import gc
import time
import logging
from typing import List, Dict, Optional

import numpy as np

logger = logging.getLogger("Wav2Vec2Aligner")


class Wav2Vec2Aligner:
    """Wav2Vec2 CTC 强制对齐器（基于 whisperx_local.alignment）"""

    def __init__(
        self,
        language: str = "ja",
        device: str = "cpu",
    ):
        self.language = language
        self.device = device
        self._model = None
        self._metadata = None

    def _load(self):
        """懒加载 wav2vec2 对齐模型"""
        if self._model is not None:
            return

        from whisperx_local.alignment import load_align_model

        if not os.environ.get("HF_ENDPOINT"):
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
        if not os.environ.get("HF_HUB_DISABLE_SYMLINKS_WARNING"):
            os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"

        logger.info(f"加载 wav2vec2 对齐模型 (lang={self.language}, device={self.device})...")
        t0 = time.time()
        self._model, self._metadata = load_align_model(
            language_code=self.language, device=self.device,
        )
        logger.info(f"  加载完成，耗时: {time.time()-t0:.1f}s")

    def align(self, segments: List[Dict], audio: np.ndarray,
              sample_rate: int = 16000) -> Dict:
        """执行 wav2vec2 强制对齐

        Args:
            segments: [{text, start, end}, ...]
            audio: 完整音频数组 (float32, mono, 16kHz)
            sample_rate: 采样率（必须是 16000）

        Returns:
            {"segments": [{text, start, end, words: [...]}]}
        """
        from whisperx_local.alignment import align

        self._load()

        # 确保 float32
        if audio.dtype != np.float32:
            audio = audio.astype(np.float32)

        return align(
            segments, self._model, self._metadata,
            audio, device=self.device,
            return_char_alignments=False,
        )

    def __del__(self):
        for attr in ("_model", "_metadata"):
            if hasattr(self, attr):
                try:
                    delattr(self, attr)
                except Exception:
                    pass
        gc.collect()


# ── 便捷函数 ──────────────────────────────────────

_ALIGNER_CACHE = {}


def get_aligner(language: str = "ja", device: str = "cpu") -> Wav2Vec2Aligner:
    """获取（并缓存）对齐器"""
    key = f"{language}_{device}"
    if key not in _ALIGNER_CACHE:
        _ALIGNER_CACHE[key] = Wav2Vec2Aligner(language=language, device=device)
        _ALIGNER_CACHE[key]._load()
    return _ALIGNER_CACHE[key]


def align_segments(segments: List[Dict], audio: np.ndarray,
                   language: str = "ja", device: str = "cpu",
                   sample_rate: int = 16000) -> Dict:
    """一键对齐 segments"""
    aligner = get_aligner(language, device)
    return aligner.align(segments, audio, sample_rate=sample_rate)


def clear_cache():
    """清理全局对齐器缓存"""
    for k, v in list(_ALIGNER_CACHE.items()):
        v.__del__()
    _ALIGNER_CACHE.clear()
