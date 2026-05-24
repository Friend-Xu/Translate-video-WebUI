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


def _ensure_hf_cache(repo_id: str, local_dir: Path) -> None:
    """将本地模型目录注入 HF 缓存结构，避免 huggingface_hub 在线下载。

    HF 缓存格式: {HF_HOME}/hub/models--{org}--{repo}/snapshots/{hash}/*
    """
    import shutil, hashlib
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    cache_name = "models--" + repo_id.replace("/", "--")
    snapshots_dir = hf_home / "hub" / cache_name / "snapshots"
    fnames = sorted(f.name for f in local_dir.glob("*") if f.is_file())
    h = hashlib.sha256("".join(fnames).encode()).hexdigest()[:40]
    target = snapshots_dir / h
    if not target.exists():
        target.mkdir(parents=True, exist_ok=True)
        for fn in fnames:
            src = local_dir / fn
            dst = target / fn
            if src.is_file() and not dst.exists():
                shutil.copy2(src, dst)
        refs_dir = hf_home / "hub" / cache_name / "refs"
        refs_dir.mkdir(parents=True, exist_ok=True)
        (refs_dir / "main").write_text(h)
        logger.info("HF 缓存注入: %s → %s", repo_id, target)


from contextlib import contextmanager

@contextmanager
def _pyannote_compat_context(model_dir: Path):
    """pyannote 兼容层：torch.load + hf_hub_download 本地缓存优先。
    通过 context manager 限定补丁生命周期，退出时自动恢复。
    """
    import torch, huggingface_hub

    _orig_load = torch.load
    _saved_modules = {}

    def _safe_load(*args, **kwargs):
        kwargs["weights_only"] = False
        return _orig_load(*args, **kwargs)

    def _safe_hf_hub(repo_id, filename, *args, **kwargs):
        kwargs.pop("use_auth_token", None)
        # 优先本地缓存
        if repo_id.startswith("pyannote/"):
            local = model_dir.parent / repo_id.split("/")[-1] / filename
            if local.is_file():
                return str(local)
        return huggingface_hub.hf_hub_download(repo_id, filename, *args, **kwargs)

    for mod_name in ("pyannote.audio.core.model", "pyannote.audio.pipelines.utils.getter"):
        try:
            mod = __import__(mod_name, fromlist=["hf_hub_download"])
            if hasattr(mod, "hf_hub_download"):
                _saved_modules[mod_name] = mod.hf_hub_download
                mod.hf_hub_download = _safe_hf_hub
        except ImportError:
            pass

    torch.load = _safe_load
    try:
        yield
    finally:
        torch.load = _orig_load
        for mod_name, orig_fn in _saved_modules.items():
            try:
                mod = __import__(mod_name, fromlist=["hf_hub_download"])
                mod.hf_hub_download = orig_fn
            except ImportError:
                pass


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
        # numpy 2.x 兼容: np.NaN 被移除
        import numpy as np
        if not hasattr(np, "NaN"):
            np.NaN = np.nan
            np.NAN = np.nan

        from pyannote.audio import Pipeline

        # 走 ModelManager 取配置路径，fallback 到默认本地路径
        try:
            from pipeline.model_manager import ModelManager
            ModelManager.ensure_hf_env()
            model_dir = ModelManager.get_path(DEFAULT_MODEL_ID)
            config_path = str(model_dir / "config.yaml")
        except Exception:
            model_dir = Path(self._model_name).parent
            config_path = self._model_name

        # 将本地 pyannote 子模型注入 HF 缓存
        import yaml
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        if not isinstance(cfg, dict) or "pipeline" not in cfg:
            raise ValueError(f"pyannote config.yaml 结构异常: {config_path}")
        params = cfg["pipeline"].get("params", {})
        for key in ("segmentation", "embedding"):
            repo_id = params.get(key, "")
            if repo_id and "/" in repo_id:
                _ensure_hf_cache(repo_id, model_dir.parent / repo_id.split("/")[-1])

        with _pyannote_compat_context(model_dir):
            t0 = time.time()
            logger.info("加载 pyannote: %s", config_path)
            self._pipeline = Pipeline.from_pretrained(config_path)
            self._pipeline.to(torch.device(self._device))

            # 优化默认参数（针对视频/游戏场景）
            # segmentation-3.0 只有 min_duration_off；clustering 可调 threshold
            self._pipeline.instantiate({
                "segmentation": {
                    "min_duration_off": 0.0,
                },
                "clustering": {
                    "threshold": 0.55,
                    "min_cluster_size": 8,
                },
            })
            logger.info("pyannote 参数: min_dur_off=0.0, cluster_threshold=0.55, min_cluster_size=8")

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
        self, vocals_path: str, force: bool = False,
        min_speakers: int = 1, max_speakers: int = 10,
    ) -> List[Tuple[str, float, float, float]]:
        """对音频执行说话人分离。

        Args:
            min_speakers: 最少说话人数（用于约束聚类）
            max_speakers: 最多说话人数（用于约束聚类）

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
            output = self._pipeline(
                vocals_path,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
            )

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
    min_speakers: int = 1, max_speakers: int = 10,
) -> Tuple[str, List[Tuple[str, float, float, float]]]:
    """一键运行说话人分离并导出。Returns: (json_path, timeline)"""
    diarizer = SpeakerDiarizer(hf_token=hf_token)
    timeline = diarizer.run(vocals_path, force=force,
                            min_speakers=min_speakers, max_speakers=max_speakers)
    json_path = os.path.join(output_dir, "speaker_timeline.json")
    diarizer.export_timeline_json(vocals_path, json_path, force=force)
    return json_path, timeline
