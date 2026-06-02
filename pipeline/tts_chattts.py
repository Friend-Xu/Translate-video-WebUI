"""
ChatTTS 离线引擎实现 — ChatTTSEngine

基于 ChatTTS（2noise/ChatTTS）的离线语音合成引擎。
通过持久子进程隔离 CUDA 上下文，防止与 CTranslate2 / MiniLM
的 PyTorch 分配器冲突导致 STATUS_HEAP_CORRUPTION。

用法:
    engine = ChatTTSEngine(speaker_seed=42)
    duration = engine.synthesize("你好世界", "output.wav")
    engine.reset_speaker(seed=99)  # 换一个声音
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
from typing import List, Optional

import numpy as np

from pipeline.logger import get_logger

logger = get_logger(__name__)

_DIGIT_MAP = {"0": "零", "1": "一", "2": "二", "3": "三", "4": "四",
              "5": "五", "6": "六", "7": "七", "8": "八", "9": "九"}
_UNITS = ["", "十", "百", "千"]
_BIG_UNITS = ["", "万", "亿"]


def _segment_to_chinese(seg: str) -> str:
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
    if not num_str:
        return num_str
    num_str = num_str.lstrip("0") or "0"
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
        if i > 0 and g != "0" * len(g) and g.lstrip("0") != g:
            result += "零"
        big_idx = len(groups) - i - 1
        big = _BIG_UNITS[big_idx] if big_idx < len(_BIG_UNITS) else ""
        result += seg + big
    result = result.rstrip("零")
    if result.startswith("一十"):
        result = result[1:]
    return result or "零"


def _normalize_numbers(text: str) -> str:
    return re.sub(r"\d+", lambda m: _arabic_to_chinese(m.group()), text)


_wetext_normalizer = None


def _get_wetext_normalizer():
    global _wetext_normalizer
    if _wetext_normalizer is None:
        try:
            from wetext import Normalizer
            _wetext_normalizer = Normalizer(lang="zh", operator="tn", remove_erhua=True)
            logger.info("wetext text normalizer loaded")
        except ImportError:
            logger.warning("wetext not installed, fallback to regex normalization")
            _wetext_normalizer = False
    return _wetext_normalizer


_PUNCT_MAP = {
    "？": "?", "！": "!", "：": ":", "；": ";",
    "…": "...", "～": "~", "、": ",",
    "“": "\"", "”": "\"", "‘": "'", "’": "'",
    "《": "", "》": "", "【": "", "】": "",
    "（": "(", "）": ")",
}


def _clean_punctuation(text: str) -> str:
    text = text.replace("——", "，")
    text = text.replace("—", "，")
    for ch, repl in _PUNCT_MAP.items():
        text = text.replace(ch, repl)
    return text


def _normalize_text(text: str) -> str:
    # 归一化小数格式：修复 whisperX 空格 artifact ("1 .19") 和全角句点 ("1．19")
    text = re.sub(r'(?<=\d)\s*[.．]\s*(\d)', r'.\1', text)
    text = re.sub(r'(\d)\s*[.．]\s*(?=\d)', r'\1.', text)
    norm = _get_wetext_normalizer()
    if norm:
        text = norm.normalize(text)
    # 兜底：wetext 版本差异可能导致部分阿拉伯数字残留
    # 先处理 "digit.digit" (如 1.19)，再处理 ".digit" (如 .2)，最后处理剩余整数
    text = re.sub(r"(\d+(?:\.\d+)?)%",
                  lambda m: "百分之" + _arabic_to_chinese(m.group(1).split(".")[0])
                  + ("点" + _decimal_to_chinese(m.group(1).split(".")[1]) if "." in m.group(1) else ""), text)
    text = re.sub(r"(\d+)\.(\d+)",
                  lambda m: _arabic_to_chinese(m.group(1)) + "点" + _decimal_to_chinese(m.group(2)), text)
    text = re.sub(r"\.(\d+)",
                  lambda m: "点" + _decimal_to_chinese(m.group(1)), text)
    text = re.sub(r"\d+", lambda m: _arabic_to_chinese(m.group()), text)
    return _clean_punctuation(text)


def _decimal_to_chinese(num_str: str) -> str:
    return "".join(_DIGIT_MAP.get(ch, ch) for ch in num_str)


def _apply_pronunciation(text: str, entries: dict) -> str:
    for key, value in entries.items():
        text = text.replace(key, value)
    return text


# -- ChatTTSEngine (subprocess-managed) --

class ChatTTSEngine:
    """ChatTTS TTS engine -- persistent subprocess for CUDA isolation.

    The subprocess chattts_worker.py runs ChatTTS in an independent
    CUDA context, preventing STATUS_HEAP_CORRUPTION from PyTorch
    allocator conflicts with CTranslate2 / MiniLM on Windows.
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
        self._lock = threading.Lock()
        self._speaker_seed = speaker_seed
        self._model_source = model_source
        self._model_path = model_path
        self._use_decoder = use_decoder
        self._sample_rate = sample_rate
        self._pronunciation_entries = pronunciation_entries or {}
        self._speaker_pt = speaker_pt
        self._spk_emb = spk_emb

        self._proc = None          # subprocess.Popen
        self._loaded = False
        self._stderr_log = None
        self._worker_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "chattts_worker.py"
        )

    @property
    def model_loaded(self) -> bool:
        return self._loaded

    @property
    def healthy(self) -> bool:
        return self._proc is not None and self._proc.poll() is None and self._loaded

    @property
    def speaker_seed(self) -> Optional[int]:
        return self._speaker_seed

    @property
    def spk_emb(self) -> Optional[str]:
        return self._spk_emb

    def reset_speaker(self, seed: Optional[int] = None) -> None:
        self._speaker_seed = seed
        self._spk_emb = None
        if self._proc is not None:
            self._shutdown_worker()
            self._loaded = False

    # -- subprocess management --

    def _send_command(self, req: dict, timeout: int = 120) -> dict:
        if self._proc is None or self._proc.poll() is not None:
            raise RuntimeError("ChatTTS worker has exited")

        line = json.dumps(req, ensure_ascii=False) + "\n"
        try:
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise RuntimeError(f"Failed to send command to worker: {e}")

        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp_line = self._proc.stdout.readline()
            if resp_line:
                return json.loads(resp_line.strip())
            time.sleep(0.1)

        raise RuntimeError(f"Worker response timeout ({timeout}s)")

    def _dump_stderr_log(self):
        if self._stderr_log is None:
            return
        try:
            self._stderr_log.flush()
            with open(self._stderr_log.name, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            if content.strip():
                logger.warning("ChatTTS worker stderr:\n%s", content[-4000:])
        except Exception:
            pass

    def _shutdown_worker(self):
        if self._proc is None:
            return
        try:
            resp = self._send_command({"action": "shutdown"}, timeout=5)
            if resp.get("status") == "ok":
                self._proc.wait(timeout=5)
        except Exception:
            pass
        if self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
        self._proc = None
        self._loaded = False
        if self._stderr_log is not None:
            try:
                self._stderr_log.close()
                os.remove(self._stderr_log.name)
            except OSError:
                pass
            self._stderr_log = None

    def _restart_worker(self) -> bool:
        self._loaded = False
        self._proc = None
        try:
            logger.info("ChatTTS worker auto-restart...")
            self.warmup()
            return self._loaded
        except Exception as e:
            logger.error("ChatTTS worker auto-restart failed: %s", e)
            return False

    # -- public API --

    def warmup(self) -> None:
        if self._loaded and self._proc is not None:
            return
        if not os.path.isfile(self._worker_script):
            logger.warning("Worker script not found: %s", self._worker_script)
            return

        logger.info("Starting ChatTTS persistent worker...")

        self._stderr_log = tempfile.NamedTemporaryFile(
            prefix="chattts_stderr_", suffix=".log",
            delete=False, mode="w", encoding="utf-8",
        )

        worker_env = os.environ.copy()
        worker_env.pop("PYTHONUNBUFFERED", None)
        worker_env["PYTHONIOENCODING"] = "utf-8"

        try:
            self._proc = subprocess.Popen(
                [sys.executable, str(self._worker_script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr_log,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                env=worker_env,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as e:
            logger.warning("Failed to start ChatTTS worker: %s", e)
            self._proc = None
            return

        warmup_req = {
            "action": "warmup",
            "speaker_seed": self._speaker_seed,
            "model_source": self._model_source,
            "use_decoder": self._use_decoder,
        }
        if self._model_path:
            warmup_req["model_path"] = self._model_path
        if self._speaker_pt and os.path.isfile(self._speaker_pt):
            warmup_req["speaker_pt"] = self._speaker_pt

        try:
            resp = self._send_command(warmup_req, timeout=120)
        except Exception as e:
            logger.error("ChatTTS worker warmup failed: %s", e)
            self._dump_stderr_log()
            self._shutdown_worker()
            return

        if resp.get("status") != "ok":
            logger.error("ChatTTS worker warmup failed: %s",
                         resp.get("message", "Unknown"))
            self._shutdown_worker()
            return

        self._loaded = True
        self._speaker_seed = resp.get("speaker_seed", self._speaker_seed)
        logger.info("ChatTTS worker ready (seed=%s)", self._speaker_seed)

    def synthesize(
        self,
        text: str,
        output_path: str,
        rate: str = "+0%",
        emotion=None,
    ) -> float:
        # CPU-only text preprocessing outside the lock (each engine has its
        # own subprocess pipe, so no contention on shared state here).
        if self._pronunciation_entries:
            text = _apply_pronunciation(text, self._pronunciation_entries)
        text = _normalize_text(text)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        with self._lock:
            if self._proc is None:
                if not self._restart_worker():
                    raise RuntimeError("ChatTTS worker not started; call warmup() first")

            if self._proc.poll() is not None:
                logger.warning("ChatTTS worker exited unexpectedly (code=%s), auto-restart",
                              self._proc.returncode)
                self._dump_stderr_log()
                self._shutdown_worker()
                if not self._restart_worker():
                    raise RuntimeError("ChatTTS worker restart failed")

            req = {"action": "synthesize", "text": text, "output_path": output_path}
            if emotion is not None:
                prompt = emotion if isinstance(emotion, str) else emotion.get("prompt", "")
                if prompt:
                    req["refine_prompt"] = prompt
            try:
                resp = self._send_command(req, timeout=120)
            except Exception as e:
                self._dump_stderr_log()
                raise RuntimeError(f"ChatTTS synthesis failed: {e}") from e

        if resp.get("status") != "ok":
            self._dump_stderr_log()
            raise RuntimeError(resp.get("message", "Unknown error"))
        return float(resp.get("duration_s", 0))

    def cleanup(self) -> None:
        self._shutdown_worker()

    def get_voices(self) -> List[str]:
        return []

    def supports_rate(self) -> bool:
        return False

    def supports_emotion(self) -> bool:
        return False

    def emotion_modes(self) -> List[str]:
        return []


# -- Factory --

class ChatTTSEngineFactory:
    """ChatTTSEngine factory method."""

    @staticmethod
    def from_config(config) -> ChatTTSEngine:
        return ChatTTSEngine(
            speaker_seed=getattr(config, "chattts_speaker_seed", None),
            model_source=getattr(config, "chattts_model_source", "local"),
            model_path=getattr(config, "chattts_model_path", None),
            pronunciation_entries=getattr(config, "tts_pronunciation", {}),
            speaker_pt=getattr(config, "chattts_speaker_pt", None),
        )
