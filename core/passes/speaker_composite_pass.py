"""
SpeakerCompositePass — Speaker Layer 完整流水线 (Chapter 4 §4.8)

编排 PyannoteAdapter + WordLevelRefiner + SpeakerEmbeddingExtractor
+ SpeakerClustering + SpeakerDriftDetector。

依赖: ["asr_composite"] (第三章)

执行顺序:
  1. PyannoteAdapter.run_diarization → speaker_timeline
  2. PyannoteAdapter.assign_speakers → ASSIGN_SPEAKER patches
  3. PyannoteAdapter.detect_boundaries → SPLIT_SEGMENT_BY_SPEAKER patches
  4. WordLevelRefiner → 5 步概率精炼 → state.speaker 槽位
  5. SpeakerEmbeddingExtractor → embedding + centroid → SpeakerNodeIR
  6. SpeakerClustering → MERGE_SPEAKERS (auto + gate)
  7. SpeakerDriftDetector → MERGE_SPEAKERS (drift fix)

迭代精炼循环 (§4.8.2): 最多 2 轮，每轮后重算 centroid。
"""
from __future__ import annotations
from core.engine.pass_base import TimelinePass
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch_engine import PatchEngine
from core.adapters.pyannote_adapter import PyannoteAdapter
from core.speaker.embedding import SpeakerEmbeddingExtractor
from core.speaker.clustering import SpeakerClustering
from core.speaker.drift import SpeakerDriftDetector


class SpeakerCompositePass(TimelinePass):
    """Speaker Layer 完整编排 — 依赖 ASR Composite Pass 的输出。"""

    name = "speaker_composite"
    depends_on = ["asr_composite"]

    def __init__(self, vocals_path: str, output_dir: str = "",
                 enable_clustering: bool = True,
                 enable_drift_detection: bool = True,
                 max_refinement_iterations: int = 2):
        self.vocals_path = vocals_path
        self.output_dir = output_dir
        self.enable_clustering = enable_clustering
        self.enable_drift_detection = enable_drift_detection
        self.max_refinement_iterations = max_refinement_iterations
        self._resolved_config: dict | None = None

    def configure(self, resolved_config: dict | None = None) -> None:
        """接收 ConfigResolver 解析后的 speaker 槽位配置。"""
        cfg = resolved_config or {}
        self._resolved_config = cfg
        if "clustering_threshold" in cfg:
            self.enable_clustering = cfg["clustering_threshold"] > 0

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        engine = PatchEngine()

        # Step 1: Diarization
        pyannote = PyannoteAdapter()
        speaker_timeline = pyannote.run_diarization(self.vocals_path)

        # Step 2-3: Assignment + boundary detection
        segments = self._collect_segments(state)
        assign_patches = pyannote.assign_speakers(segments, speaker_timeline)
        boundary_patches = pyannote.detect_boundaries(segments, speaker_timeline)

        for p in assign_patches:
            engine.apply(state, p)
        for p in boundary_patches:
            engine.apply(state, p)

        # Step 4: Word-level refinement
        self._run_refiner(state, speaker_timeline)

        # Step 5: Embedding extraction
        extractor = SpeakerEmbeddingExtractor(output_dir=self.output_dir)
        embeddings = extractor.extract(self.vocals_path, speaker_timeline)
        centroids = extractor.compute_centroid(embeddings)
        stability = extractor.compute_centroid_stability(embeddings)
        extractor.write_to_registry(centroids, stability, state.ir.speakers)

        # Step 6-7: Iterative refinement loop (§4.8.2)
        clustering = SpeakerClustering() if self.enable_clustering else None
        drift = SpeakerDriftDetector() if self.enable_drift_detection else None

        for _iteration in range(self.max_refinement_iterations):
            changed = False

            if clustering:
                results = clustering.cluster(centroids)
                for p in clustering.to_patches(results):
                    if engine.apply(state, p).get("status") == "applied":
                        changed = True

            if drift:
                candidates = drift.detect(centroids, speaker_timeline, state)
                for p in drift.repair(candidates):
                    if engine.apply(state, p).get("status") == "applied":
                        changed = True

            if not changed:
                break

            centroids = self._recompute_centroids(state, centroids)

        self._write_speaker_registry(state, speaker_timeline)
        return state

    # ── internal ──────────────────────────────────────────

    def _collect_segments(self, state: TimelineProjectState) -> list[dict]:
        segments = []
        for es in state.sorted_events():
            segments.append({
                "start": es.start,
                "end": es.end,
                "text": es.ir.text_ref,
            })
        return segments

    def _run_refiner(self, state: TimelineProjectState,
                     speaker_timeline: list[tuple]) -> None:
        try:
            from core.refiner import WordLevelRefiner
            all_words = []
            for es in state.sorted_events():
                for w in es.asr.get("words", []):
                    w_copy = dict(w)
                    w_copy["segment_id"] = es.id
                    all_words.append(w_copy)

            if all_words:
                refiner = WordLevelRefiner()
                refined = refiner.refine(all_words, speaker_timeline)
                for w in refined["words"]:
                    es = state.get_event(w.get("segment_id", ""))
                    if es and "speaker" in w:
                        es.speaker["speaker_id"] = w["speaker"]
                        es.speaker["confidence"] = w.get("speaker_confidence", 0.0)
        except ImportError:
            pass

    def _recompute_centroids(self, state: TimelineProjectState,
                             old_centroids: dict[str, list[float]]
                             ) -> dict[str, list[float]]:
        active_ids = set(state.ir.speakers.keys())
        return {k: v for k, v in old_centroids.items() if k in active_ids}

    def _write_speaker_registry(self, state: TimelineProjectState,
                                speaker_timeline: list[tuple]) -> None:
        for spk_id, spk_node in state.ir.speakers.items():
            turns = [t for t in speaker_timeline if t[0] == spk_id]
            if turns and spk_node.confidence is None:
                avg_conf = sum(t[3] for t in turns) / len(turns)
                object.__setattr__(spk_node, "confidence", avg_conf)
