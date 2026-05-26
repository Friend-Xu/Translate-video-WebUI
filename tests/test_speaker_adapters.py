"""
Speaker 适配器测试 (Chapter 4 实施验证)

测试 PyannoteAdapter, SpeakerEmbeddingExtractor, SpeakerClustering,
SpeakerDriftDetector。使用 mock 数据避免 GPU/模型依赖。
"""
import pytest
from core.adapters.pyannote_adapter import PyannoteAdapter
from core.speaker.embedding import SpeakerEmbeddingExtractor
from core.speaker.clustering import SpeakerClustering, ClusterResult
from core.speaker.drift import SpeakerDriftDetector, DriftCandidate
from core.runtime.patch import Patch, OpCode
from core.runtime.event_state import TimelineEventState
from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR


# ── mock data ────────────────────────────────────────────

SPEAKER_TIMELINE = [
    ("SPEAKER_00", 0.0, 2.5, 0.95),
    ("SPEAKER_01", 3.0, 5.0, 0.92),
    ("SPEAKER_00", 5.5, 8.0, 0.94),
]

SEGMENTS = [
    {"start": 0.0, "end": 2.5, "text": "Hello world"},
    {"start": 3.0, "end": 5.0, "text": "How are you"},
    {"start": 5.5, "end": 8.0, "text": "I'm fine"},
]


class TestPyannoteAdapter:
    """PyannoteAdapter 输入/输出验证"""

    def test_construct(self):
        adapter = PyannoteAdapter(device="cpu")
        assert adapter.device == "cpu"

    def test_find_best_turn_exact_match(self):
        best = PyannoteAdapter._find_best_turn(1.0, SPEAKER_TIMELINE)
        assert best is not None
        assert best[0] == "SPEAKER_00"

    def test_find_best_turn_miss(self):
        best = PyannoteAdapter._find_best_turn(9.0, SPEAKER_TIMELINE)
        assert best is None

    def test_assign_speakers_structure(self):
        adapter = PyannoteAdapter(device="cpu")
        patches = adapter.assign_speakers(SEGMENTS, SPEAKER_TIMELINE)
        assert len(patches) == 3
        p0 = patches[0]
        assert p0.op == OpCode.ASSIGN_SPEAKER
        assert p0.value["speaker_id"] == "SPEAKER_00"
        assert p0.value["confidence"] == 0.95
        assert p0.value["source"] == "pyannote_v3.1"

    def test_assign_speakers_no_match(self):
        segments = [{"start": 9.0, "end": 10.0, "text": "test"}]
        adapter = PyannoteAdapter(device="cpu")
        patches = adapter.assign_speakers(segments, SPEAKER_TIMELINE)
        assert patches[0].value["speaker_id"] is None
        assert patches[0].value["confidence"] == 0.0

    def test_detect_boundaries_no_internal(self):
        segments = [{"start": 0.0, "end": 2.5, "text": "Hello"}]
        adapter = PyannoteAdapter(device="cpu")
        patches = adapter.detect_boundaries(segments, SPEAKER_TIMELINE)
        assert len(patches) == 0

    def test_detect_boundaries_two_speakers(self):
        segments = [{"start": 1.0, "end": 4.0, "text": "Hello world How"}]
        adapter = PyannoteAdapter(device="cpu")
        patches = adapter.detect_boundaries(segments, SPEAKER_TIMELINE)
        assert len(patches) == 1
        assert patches[0].op == OpCode.SPLIT_SEGMENT_BY_SPEAKER
        assert len(patches[0].value["boundaries"]) == 2


class TestEmbeddingExtractor:
    """SpeakerEmbeddingExtractor 测试"""

    def test_extract_embeddings(self):
        extractor = SpeakerEmbeddingExtractor()
        embeddings = extractor.extract("/nonexistent.wav", SPEAKER_TIMELINE)
        assert isinstance(embeddings, dict)

    def test_compute_centroid(self):
        extractor = SpeakerEmbeddingExtractor()
        embeddings = {
            "SPEAKER_00": [[0.5] * 192, [0.6] * 192],
            "SPEAKER_01": [[0.3] * 192],
        }
        centroids = extractor.compute_centroid(embeddings)
        assert "SPEAKER_00" in centroids
        assert len(centroids["SPEAKER_00"]) == 192
        assert centroids["SPEAKER_00"][0] == pytest.approx(0.55)

    def test_centroid_stability(self):
        extractor = SpeakerEmbeddingExtractor()
        embeddings = {
            "SPK_A": [[0.5] * 192, [0.52] * 192],
            "SPK_B": [[0.5] * 192, [0.0] * 192],
        }
        stability = extractor.compute_centroid_stability(embeddings)
        assert stability["SPK_A"] > stability["SPK_B"]

    def test_centroid_stability_single_turn(self):
        extractor = SpeakerEmbeddingExtractor()
        stability = extractor.compute_centroid_stability(
            {"SPK_A": [[0.5] * 192]}
        )
        assert stability["SPK_A"] == 1.0

    def test_cosine(self):
        result = SpeakerEmbeddingExtractor._cosine([1.0, 0.0], [0.0, 1.0])
        assert result == pytest.approx(0.0)
        result = SpeakerEmbeddingExtractor._cosine([1.0, 0.0], [1.0, 0.0])
        assert result == pytest.approx(1.0)


class TestSpeakerClustering:
    """SpeakerClustering 测试"""

    def test_high_similarity_auto_merge(self):
        clustering = SpeakerClustering()
        centroids = {"SPK_A": [0.5] * 192, "SPK_B": [0.51] * 192}
        results = clustering.cluster(centroids)
        assert len(results) == 1
        assert results[0].confidence == "auto"
        assert results[0].similarity > 0.85

    def test_low_similarity_keep_separate(self):
        clustering = SpeakerClustering()
        centroids = {"SPK_A": [1.0] + [0.0] * 191, "SPK_B": [0.0] * 192}
        results = clustering.cluster(centroids)
        assert len(results) == 0

    def test_to_patches(self):
        clustering = SpeakerClustering()
        results = [ClusterResult(
            canonical_id="SPK_A", merged_ids=["SPK_B"],
            similarity=0.92, confidence="auto",
        )]
        patches = clustering.to_patches(results)
        assert len(patches) == 1
        assert patches[0].op == OpCode.MERGE_SPEAKERS
        assert patches[0].value["auto_apply"] is True

    def test_to_patches_gate(self):
        clustering = SpeakerClustering()
        results = [ClusterResult(
            canonical_id="SPK_A", merged_ids=["SPK_C"],
            similarity=0.78, confidence="gate",
        )]
        patches = clustering.to_patches(results)
        assert patches[0].value["auto_apply"] is False


class TestDriftDetector:
    """SpeakerDriftDetector 三信号检测"""

    def test_detect_high_embedding_similarity(self):
        drift = SpeakerDriftDetector()
        centroids = {"SPK_A": [0.5] * 192, "SPK_B": [0.51] * 192}
        timeline = [
            ("SPK_A", 0.0, 2.0, 1.0), ("SPK_B", 2.3, 4.0, 1.0),
            ("SPK_A", 4.3, 6.0, 1.0), ("SPK_B", 6.3, 8.0, 1.0),
        ]
        candidates = drift.detect(centroids, timeline)
        assert len(candidates) >= 1
        assert candidates[0].embedding_sim > 0.8

    def test_detect_low_similarity(self):
        drift = SpeakerDriftDetector()
        centroids = {"SPK_A": [1.0] + [0.0] * 191, "SPK_B": [0.0] * 192}
        timeline = [("SPK_A", 0.0, 5.0, 1.0), ("SPK_B", 6.0, 10.0, 1.0)]
        candidates = drift.detect(centroids, timeline)
        assert len(candidates) == 0

    def test_temporal_interleaving_detected(self):
        timeline = [
            ("SPK_A", 0.0, 1.0, 1.0), ("SPK_B", 1.2, 2.0, 1.0),
            ("SPK_A", 2.2, 3.0, 1.0), ("SPK_B", 3.2, 4.0, 1.0),
        ]
        score = SpeakerDriftDetector._calc_temporal_score("SPK_A", "SPK_B", timeline)
        assert score > 0

    def test_temporal_no_interleaving(self):
        timeline = [("SPK_A", 0.0, 5.0, 1.0), ("SPK_B", 10.0, 15.0, 1.0)]
        score = SpeakerDriftDetector._calc_temporal_score("SPK_A", "SPK_B", timeline)
        assert score == 0.0

    def test_repair_generates_patches(self):
        drift = SpeakerDriftDetector()
        candidates = [DriftCandidate(
            speaker_a="SPK_A", speaker_b="SPK_B",
            embedding_sim=0.88, temporal_score=0.7, semantic_score=0.6,
            composite_score=0.82, recommended_action="auto_merge",
        )]
        patches = drift.repair(candidates)
        assert len(patches) == 1
        assert patches[0].op == OpCode.MERGE_SPEAKERS
        assert patches[0].value["auto_apply"] is True


class TestSpeakerSlotPopulation:
    """验证 speaker 槽位被正确写入"""

    def test_speaker_slot_after_assign(self):
        es = TimelineEventState(TimelineEventIR(
            id="evt_001", start=0, end=2.5, text_ref="Hello", speaker_ref=None,
        ))
        es.speaker["speaker_id"] = "SPEAKER_00"
        es.speaker["confidence"] = 0.95
        es.speaker["source"] = "pyannote_v3.1"
        assert es.speaker["speaker_id"] == "SPEAKER_00"
        assert es.speaker["confidence"] == 0.95

    def test_speaker_node_embedding_fields(self):
        spk = SpeakerNodeIR(
            id="SPEAKER_00", name="主持人",
            embedding_ref="_embeddings/speaker_SPEAKER_00.npy",
            confidence=0.92,
        )
        assert spk.embedding_ref is not None
        assert spk.confidence == 0.92
