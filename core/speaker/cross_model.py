"""
Cross-Model Speaker Verification — 交叉嵌入分歧检测

pyannote 聚类结果 vs WeSpeaker 独立嵌入聚类 → 分歧点标记为待审核。
两个不同模型的结论分歧处，就是最需要人工看的地方。

使用场景:
  pyannote 说: 段落 [0,3,5] = Speaker A, [1,2,4] = Speaker B
  WeSpeaker 说: 段落 [0,3,5] = Speaker A, [1,4] = Speaker B, [2] = Speaker C
                                ↑ 分歧点 → 标记为 ⚠️ 待审核
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np

# 延迟导入 SpeakerEmbeddingExtractor (避免循环依赖)
_SpeakerEmbeddingExtractor = None


def _get_extractor():
    global _SpeakerEmbeddingExtractor
    if _SpeakerEmbeddingExtractor is None:
        from core.speaker.embedding import SpeakerEmbeddingExtractor
        _SpeakerEmbeddingExtractor = SpeakerEmbeddingExtractor
    return _SpeakerEmbeddingExtractor


@dataclass
class DivergenceIssue:
    """单个交叉模型分歧。"""
    segment_id: str
    pyannote_label: str
    wespeaker_label: str
    start_sec: float
    end_sec: float
    confidence: float          # 到 WeSpeaker 质心的 cosine 相似度
    nearest_distance: float    # 到最近匹配质心的 cosine 距离
    message: str
    detail: dict = field(default_factory=dict)


class CrossModelVerifier:
    """用 WeSpeaker 独立嵌入验证 pyannote 的说话人分配。"""

    def __init__(self, similarity_threshold: float = 0.65):
        self.threshold = similarity_threshold
        self._extractor = None

    def verify(self, speaker_timeline: list[dict],
               vocals_path: str) -> list[DivergenceIssue]:
        """执行交叉验证，返回分歧列表。"""
        if self._extractor is None:
            self._extractor = _get_extractor()("")

        # 1. 提取所有有效段的 embedding
        embeddings: dict[str, np.ndarray] = {}
        valid_segs = []
        for seg in speaker_timeline:
            dur = seg.get("end", 0) - seg.get("start", 0)
            if dur < 1.2:
                continue
            emb = self._extractor._extract_segment_embedding(
                vocals_path, seg.get("start", 0), seg.get("end", 0))
            if emb:
                seg_id = seg.get("id", f"{seg.get('speaker')}_{seg.get('start')}")
                embeddings[seg_id] = np.asarray(emb, dtype=np.float32)
                valid_segs.append(seg)

        if len(valid_segs) < 2:
            return []

        # 2. WeSpeaker 独立聚类
        seg_ids = list(embeddings.keys())
        X = np.stack([embeddings[sid] for sid in seg_ids])
        norms = np.linalg.norm(X, axis=1, keepdims=True) + 1e-10
        cos_dist = 1.0 - np.clip((X / norms) @ (X / norms).T, -1, 1)

        from sklearn.cluster import AgglomerativeClustering
        clustering = AgglomerativeClustering(
            n_clusters=None, distance_threshold=self.threshold,
            metric="precomputed", linkage="average",
        )
        ws_labels = clustering.fit_predict(cos_dist)
        ws_label_map = {seg_ids[i]: f"WS_{ws_labels[i]}" for i in range(len(seg_ids))}

        # 3. 比较标签 → 找到分歧
        issues = []
        for seg in valid_segs:
            seg_id = seg.get("id", f"{seg.get('speaker')}_{seg.get('start')}")
            py_label = seg.get("speaker", "?")
            ws_label = ws_label_map.get(seg_id)

            if ws_label is not None and ws_label != py_label:
                same_ws_embs = [embeddings[sid] for sid, lbl in ws_label_map.items() if lbl == ws_label]
                centroid = np.mean(same_ws_embs, axis=0) if same_ws_embs else np.zeros(256)
                emb = embeddings[seg_id]
                cos_sim = float(np.dot(emb, centroid) / (np.linalg.norm(emb) * np.linalg.norm(centroid) + 1e-10))
                issues.append(DivergenceIssue(
                    segment_id=seg_id,
                    pyannote_label=py_label,
                    wespeaker_label=ws_label,
                    start_sec=seg.get("start", 0),
                    end_sec=seg.get("end", 0),
                    confidence=cos_sim,
                    nearest_distance=float(1.0 - cos_sim),
                    message=f"交叉模型分歧: pyannote→{py_label}, WeSpeaker→{ws_label} (cos={cos_sim:.3f})",
                    detail={"pyannote_label": py_label, "wespeaker_label": ws_label, "cosine_similarity": cos_sim},
                ))

        return issues


def cross_model_report(issues: list[DivergenceIssue]) -> dict:
    """将交叉验证分歧转为可序列化报告。"""
    return {
        "total_divergences": len(issues),
        "divergences": [
            {
                "segment_id": iss.segment_id,
                "start": iss.start_sec, "end": iss.end_sec,
                "pyannote_label": iss.pyannote_label,
                "wespeaker_label": iss.wespeaker_label,
                "confidence": iss.confidence,
                "nearest_distance": iss.nearest_distance,
                "message": iss.message,
                "detail": iss.detail,
            }
            for iss in issues
        ],
    }
