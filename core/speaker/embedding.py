"""
SpeakerEmbeddingExtractor — embedding 提取与质心计算 (Chapter 4 §4.4)

从 pyannote diarization 结果提取 speaker embedding 向量。
embedding 是 clustering、drift detection、TTS voice binding 的基础。
"""
from __future__ import annotations
import os
import numpy as np
from pathlib import Path

# 模块级 embedding 模型缓存（避免重复加载 200MB 权重）
_embedding_model: object | None = None
_embedding_model_lock = __import__("threading").Lock()
_MODELS_ROOT = Path(__file__).resolve().parent.parent.parent / "models"
_DIAR_MODEL_DIR = _MODELS_ROOT / "pyannote" / "speaker-diarization-3.1"


def _get_embedding_model():
    """懒加载 WeSpeaker ResNet34-LM embedding 模型（模块级单例）。"""
    global _embedding_model
    if _embedding_model is not None:
        return _embedding_model

    with _embedding_model_lock:
        if _embedding_model is not None:
            return _embedding_model
        import torch
        from pyannote.audio import Inference
        from pipeline.speaker_diarize import _pyannote_compat_context

        with _pyannote_compat_context(_DIAR_MODEL_DIR):
            model = Inference(
                "pyannote/wespeaker-voxceleb-resnet34-LM",
                device=torch.device("cuda"),
                use_auth_token=False,
            )
        _embedding_model = model
        return model


class SpeakerEmbeddingExtractor:
    """从 pyannote diarization 结果提取 speaker embedding。

    当前 pyannote 内部使用 embedding 做聚类但丢弃结果。
    本模块在 diarization 完成后提取 embedding 用于:
      - SpeakerClustering: 发现同一人的多个 label
      - SpeakerDriftDetector: 检测身份漂移
      - TTS voice binding: 基于声纹匹配声线
    """

    def __init__(self, output_dir: str = ""):
        self.output_dir = output_dir

    def extract(self, vocals_path: str,
                speaker_timeline: list[tuple]) -> dict[str, list[list[float]]]:
        """对每个 speaker turn 提取 embedding。

        Returns:
            {speaker_id: [embedding_turn1, embedding_turn2, ...]}
            每个 embedding 为 192-dim float list
        """
        embeddings: dict[str, list[list[float]]] = {}

        for spk_id, start, end, conf in speaker_timeline:
            emb = self._extract_segment_embedding(vocals_path, start, end)
            if emb:
                embeddings.setdefault(spk_id, []).append(emb)

        return embeddings

    def compute_centroid(self, embeddings: dict[str, list[list[float]]]
                         ) -> dict[str, list[float]]:
        """计算每个 speaker 的 embedding 质心（各 turn 的均值）。"""
        centroids: dict[str, list[float]] = {}
        for spk_id, emb_list in embeddings.items():
            if emb_list:
                arr = np.array(emb_list)
                centroids[spk_id] = arr.mean(axis=0).tolist()
        return centroids

    def compute_centroid_stability(self, embeddings: dict[str, list[list[float]]]
                                   ) -> dict[str, float]:
        """计算质心稳定性 — 各 turn embedding 的 pairwise cosine 均值。

        稳定性高 → speaker label 可信
        稳定性低 → 可能是多个 speaker 被标为同一 label
        """
        stability: dict[str, float] = {}
        for spk_id, emb_list in embeddings.items():
            if len(emb_list) < 2:
                stability[spk_id] = 1.0
            else:
                sims = []
                for i in range(len(emb_list)):
                    for j in range(i + 1, len(emb_list)):
                        sims.append(self._cosine(emb_list[i], emb_list[j]))
                stability[spk_id] = float(np.mean(sims)) if sims else 1.0
        return stability

    def write_to_registry(self, centroids: dict[str, list[float]],
                          stability: dict[str, float],
                          speakers: dict) -> None:
        """将 centoid 和 stability 写入 SpeakerNodeIR。

        SpeakerNodeIR.embedding_ref → "_embeddings/speaker_{id}.npy"
        SpeakerNodeIR.confidence → centroid_stability
        """
        emb_dir = os.path.join(self.output_dir, "_embeddings") if self.output_dir else ""
        if emb_dir:
            os.makedirs(emb_dir, exist_ok=True)

        for spk_id, centroid in centroids.items():
            if emb_dir:
                path = os.path.join(emb_dir, f"speaker_{spk_id}.npy")
                np.save(path, np.array(centroid, dtype=np.float32))

            if spk_id in speakers:
                spk = speakers[spk_id]
                object.__setattr__(spk, "embedding_ref",
                                   os.path.join(emb_dir, f"speaker_{spk_id}.npy") if emb_dir else "")
                object.__setattr__(spk, "confidence",
                                   stability.get(spk_id, 1.0))

    # ── internal ──────────────────────────────────────────

    def _extract_segment_embedding(self, vocals_path: str,
                                   start: float, end: float
                                   ) -> list[float] | None:
        """对单个音频片段提取 speaker embedding (WeSpeaker ResNet34-LM, 256-dim)。"""
        try:
            from pyannote.core import Segment
            dur = end - start
            if dur < 1.2:
                return None  # WeSpeaker 需要至少 1.2s 的音频才能可靠提取
            model = _get_embedding_model()
            emb = model.crop(vocals_path, Segment(start, end))
            # SlidingWindowFeature → mean over windows → 256-dim vector
            vec = np.mean(emb.data, axis=0).astype(np.float32)
            return vec.tolist()
        except Exception:
            return None

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        a_arr, b_arr = np.asarray(a), np.asarray(b)
        norm = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
        return float(np.dot(a_arr, b_arr) / norm) if norm > 0 else 0.0
