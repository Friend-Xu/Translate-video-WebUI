"""
PyannoteAdapter — pyannote → Patch 适配器 (Chapter 4 §4.3)

封装现有 SpeakerDiarizer，将其输出转换为 ASSIGN_SPEAKER +
SPLIT_SEGMENT_BY_SPEAKER patch。

三种模式对应 Speaker Identity State Manager 的三个核心职责:
  1. Boundary Generator — diarization + speaker change point 检测
  2. Identity Clusterer — segment → speaker assignment
  3. Continuity Maintainer — boundary correction (split at speaker changes)
"""
from __future__ import annotations
from core.runtime.patch import Patch, OpCode


class PyannoteAdapter:
    """将 pyannote diarization 转为 Patch。

    封装现有 SpeakerDiarizer，不做任何修改。
    复用 _DIARIZATION_LOCK 和文件哈希缓存机制。
    """

    def __init__(self, model_name: str | None = None, device: str = "cuda",
                 hf_token: str | None = None):
        self.model_name = model_name
        self.device = device
        self.hf_token = hf_token

    # ── Boundary Generator (§4.1.1.1) ────────────────────

    def configure(self, event_config = None):
        if not event_config: return
        if "clustering_threshold" in event_config: self._threshold = event_config["clustering_threshold"]
        if "min_speakers" in event_config: self._min_speakers = event_config["min_speakers"]
        if "max_speakers" in event_config: self._max_speakers = event_config["max_speakers"]
        if "clustering_method" in event_config: self._method = event_config["clustering_method"]
        if "embedding_model" in event_config: self._embedding_model = event_config["embedding_model"]
    def run_diarization(self, vocals_path: str, force: bool = False,
                        min_speakers: int = 1, max_speakers: int = 10
                        ) -> list[tuple]:
        """执行 pyannote diarization，返回 speaker_timeline。

        Returns:
            [(speaker_id, start_s, end_s, confidence), ...]
        """
        from pipeline.speaker_diarize import SpeakerDiarizer

        diarizer = SpeakerDiarizer(
            model_name=self.model_name,
            device=self.device,
            hf_token=self.hf_token,
        )
        return diarizer.run(
            vocals_path, force=force,
            min_speakers=min_speakers, max_speakers=max_speakers,
        )

    # ── Identity Clusterer (§4.1.1.2) ─────────────────────

    def assign_speakers(self, segments: list[dict],
                        speaker_timeline: list[tuple]) -> list[Patch]:
        """对每个 ASR segment 分配 speaker_id，输出 ASSIGN_SPEAKER patch。

        通过中点匹配：segment 的 (start+end)/2 落在哪个 pyannote turn 区间内，
        就分配该 turn 的 speaker_id。
        """
        patches: list[Patch] = []

        for i, seg in enumerate(segments):
            seg_mid = (seg.get("start", 0) + seg.get("end", 0)) / 2
            best = self._find_best_turn(seg_mid, speaker_timeline)

            if best:
                spk_id, _, _, confidence = best
                patches.append(Patch(
                    id=f"spk_evt_{i + 1:03d}",
                    target_id=f"evt_{i + 1:03d}",
                    op=OpCode.ASSIGN_SPEAKER,
                    value={
                        "speaker_id": spk_id,
                        "confidence": confidence,
                        "source": "pyannote_v3.1",
                    },
                    author="system",
                    confidence=confidence,
                ))
            else:
                patches.append(Patch(
                    id=f"spk_evt_{i + 1:03d}",
                    target_id=f"evt_{i + 1:03d}",
                    op=OpCode.ASSIGN_SPEAKER,
                    value={
                        "speaker_id": None,
                        "confidence": 0.0,
                        "source": "pyannote_v3.1",
                    },
                    author="system",
                    confidence=0.0,
                ))

        return patches

    # ── Continuity Maintainer (§4.1.1.3) ──────────────────

    def detect_boundaries(self, segments: list[dict],
                          speaker_timeline: list[tuple]) -> list[Patch]:
        """检测 ASR segment 内部的 speaker change point。

        当 pyannote speaker turn 边界落在 ASR segment 中间时，
        输出 SPLIT_SEGMENT_BY_SPEAKER patch 用于后续 segment 拆分。
        """
        patches: list[Patch] = []

        for i, seg in enumerate(segments):
            seg_start = seg.get("start", 0)
            seg_end = seg.get("end", 0)
            boundaries = self._find_internal_boundaries(
                seg_start, seg_end, speaker_timeline,
            )
            if len(boundaries) > 1:
                patches.append(Patch(
                    id=f"boundary_evt_{i + 1:03d}",
                    target_id=f"evt_{i + 1:03d}",
                    op=OpCode.SPLIT_SEGMENT_BY_SPEAKER,
                    value={"boundaries": boundaries},
                    author="system",
                ))

        return patches

    # ── internal ──────────────────────────────────────────

    @staticmethod
    def _find_best_turn(seg_mid: float,
                        speaker_timeline: list[tuple]) -> tuple | None:
        """在 speaker_timeline 中找包含 seg_mid 的 turn。"""
        for turn in speaker_timeline:
            spk_id, start, end, conf = turn
            if start <= seg_mid <= end:
                return turn
        return None

    @staticmethod
    def _find_internal_boundaries(seg_start: float, seg_end: float,
                                  speaker_timeline: list[tuple]) -> list[dict]:
        """找 segment 时间范围内的 speaker 变更点。"""
        speakers_seen: dict[str, dict] = {}
        for spk_id, start, end, conf in speaker_timeline:
            if end <= seg_start or start >= seg_end:
                continue
            clamped_start = max(start, seg_start)
            clamped_end = min(end, seg_end)
            if spk_id not in speakers_seen:
                speakers_seen[spk_id] = {
                    "speaker": spk_id,
                    "time": clamped_start,
                    "confidence": conf,
                }
            else:
                speakers_seen[spk_id]["time"] = min(
                    speakers_seen[spk_id]["time"], clamped_start,
                )

        return sorted(speakers_seen.values(), key=lambda x: x["time"])
