"""
Speaker Diarization — pyannote.audio 3.1 + 3D-Speaker CAM++ 嵌入

独立于 ASR/VAD，吃整段 vocals.wav，输出说话人时间线。
不与 CTranslate2 并行 —— 走专用 CUDA 锁，跑完卸载。

用法:
    from pipeline.speaker_diarize import SpeakerDiarizer
    diarizer = SpeakerDiarizer()
    timeline = diarizer.run("vocals.wav")
    # → [(speaker, start, end, confidence), ...]
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import torch

logger = logging.getLogger("pipeline.speaker_diarize")

# 与 CTranslate2 串行的互斥锁
_DIARIZATION_LOCK = threading.Lock()

_MODELS_ROOT = Path(__file__).parent.parent / "models"
DEFAULT_MODEL = str(_MODELS_ROOT / "pyannote" / "speaker-diarization-3.1" / "config.yaml")
DEFAULT_MODEL_ID = "pyannote-diarization"  # ModelManager 注册 ID
MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
DIAR_CACHE_DIR = MODELS_DIR / "pyannote"


def _hash_file(path: str, n_bytes: int = 65536) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(n_bytes):
            h.update(chunk)
    return h.hexdigest()


class SpeakerDiarizer:
    """pyannote 说话人分离引擎。每次 run() 加载模型 → 推理 → 卸载。"""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str = "cuda",
        hf_token: Optional[str] = None,
    ):
        self._model_name = model_name
        self._device = device
        self._hf_token = hf_token or os.environ.get("HF_TOKEN", "")
        self._pipeline = None
        self._loaded = False

    @property
    def model_loaded(self) -> bool:
        return self._loaded

    def load_model(self) -> None:
        if self._loaded:
            return
        # numpy 2.x: np.NaN 被移除
        import numpy as np
        np.NaN = np.nan

        # hf_hub_download: use_auth_token -> token (pyannote 3.3.2 用旧 API)
        import huggingface_hub
        _orig_hf_hub = huggingface_hub.hf_hub_download
        def _patched_hf_hub(*args, **kwargs):
            if "use_auth_token" in kwargs:
                kwargs["token"] = kwargs.pop("use_auth_token")
            return _orig_hf_hub(*args, **kwargs)
        huggingface_hub.hf_hub_download = _patched_hf_hub

        from pyannote.audio import Pipeline

        # 走 ModelManager 取配置路径，fallback 到默认本地路径
        try:
            from pipeline.model_manager import ModelManager
            ModelManager.ensure_hf_env()
            config_path = str(ModelManager.get_path(DEFAULT_MODEL_ID) / "config.yaml")
        except Exception:
            config_path = self._model_name

        t0 = time.time()
        logger.info("加载 pyannote: %s", config_path)
        self._pipeline = Pipeline.from_pretrained(config_path)
        self._pipeline.to(torch.device(self._device))
        # 预热 CUDA JIT
        dummy = torch.randn(1, 16000, device=self._device)
        self._pipeline({"waveform": dummy, "sample_rate": 16000})
        self._loaded = True
        logger.info("pyannote 加载完成 (%.1fs)", time.time() - t0)

    def unload_model(self) -> None:
        if self._pipeline is not None:
            del self._pipeline
            self._pipeline = None
        self._loaded = False
        torch.cuda.empty_cache()

    def run(
        self, vocals_path: str, force: bool = False
    ) -> List[Tuple[str, float, float, float]]:
        """对音频执行说话人分离。

        Returns: [(speaker_id, start_s, end_s, confidence), ...] 按时间排序
        """
        if not os.path.isfile(vocals_path):
            raise FileNotFoundError(f"人声文件不存在: {vocals_path}")

        cache_path = self._cache_path(vocals_path)
        if not force and os.path.isfile(cache_path):
            logger.info("使用缓存: %s", cache_path)
            return self._load_cache(cache_path)

        with _DIARIZATION_LOCK:
            self.load_model()
            t0 = time.time()
            logger.info("说话人分离: %s", os.path.basename(vocals_path))
            output = self._pipeline(vocals_path)

            timeline = []
            for turn, _, speaker in output.itertracks(yield_label=True):
                timeline.append((speaker, turn.start, turn.end, 1.0))
            timeline.sort(key=lambda x: x[1])

            elapsed = time.time() - t0
            speakers = sorted(set(s[0] for s in timeline))
            logger.info(
                "分离完成: %d 段, %d 说话人 (%s), %.1fs",
                len(timeline), len(speakers), ", ".join(speakers), elapsed,
            )
            self.unload_model()

        self._save_cache(cache_path, timeline, speakers)
        return timeline

    def export_timeline_json(
        self, vocals_path: str, output_path: str, force: bool = False
    ) -> str:
        """导出 speaker_timeline.json 到指定路径。"""
        timeline = self.run(vocals_path, force=force)
        speakers = sorted(set(s[0] for s in timeline))
        data = {
            "model": self._model_name,
            "speakers": speakers,
            "turns": [
                {"speaker": spk, "start": s, "end": e, "confidence": c}
                for spk, s, e, c in timeline
            ],
        }
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("时间线已导出: %s (%d 段)", output_path, len(timeline))
        return output_path

    # ── cache ──────────────────────────────────────────────

    def _cache_path(self, vocals_path: str) -> str:
        file_hash = _hash_file(vocals_path)
        os.makedirs(str(DIAR_CACHE_DIR), exist_ok=True)
        return os.path.join(str(DIAR_CACHE_DIR), f"tl_{file_hash[:16]}.json")

    def _load_cache(self, path: str) -> list:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [
            (t["speaker"], t["start"], t["end"], t.get("confidence", 1.0))
            for t in data["turns"]
        ]

    def _save_cache(self, path: str, timeline: list, speakers: list) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "model": self._model_name,
                "speakers": speakers,
                "turns": [
                    {"speaker": s, "start": st, "end": en, "confidence": c}
                    for s, st, en, c in timeline
                ],
            }, f, ensure_ascii=False, indent=2)


def run_diarization(
    vocals_path: str, output_dir: str, force: bool = False,
    hf_token: Optional[str] = None,
) -> Tuple[str, List[Tuple[str, float, float, float]]]:
    """一键运行说话人分离并导出。Returns: (json_path, timeline)"""
    diarizer = SpeakerDiarizer(hf_token=hf_token)
    timeline = diarizer.run(vocals_path, force=force)
    json_path = os.path.join(output_dir, "speaker_timeline.json")
    diarizer.export_timeline_json(vocals_path, json_path, force=force)
    return json_path, timeline
