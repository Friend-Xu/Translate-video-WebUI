"""
ASR 适配器测试 (Chapter 3 实施验证)

测试 WhisperAdapter、Wav2Vec2Adapter、ASRCompositePass、ASRScorer。
使用 mock 数据避免 GPU/模型依赖。
"""
import pytest
from core.adapters.whisper_adapter import WhisperAdapter, EngineContext
from core.adapters.wav2vec2_adapter import Wav2Vec2Adapter
from core.runtime.patch import Patch, OpCode
from core.runtime.patch_engine import PatchEngine
from core.runtime.event_state import TimelineEventState
from core.runtime.project_state import TimelineProjectState
from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR
from core.ir.project import TimelineProjectIR
from core.scoring.asr_scorer import ASRScorer, ASRScore


class TestWhisperAdapter:
    """WhisperAdapter 输入/输出验证"""

    def test_engine_context_defaults(self):
        ctx = EngineContext(audio_path="/tmp/test.wav")
        assert ctx.device == "cuda"
        assert ctx.model_name == "small"
        assert ctx.compute_type == "float16"
        assert ctx.language is None
        assert ctx.num_workers == 1

    def test_engine_context_custom(self):
        ctx = EngineContext(
            audio_path="/tmp/test.wav", device="cpu",
            model_name="medium", language="ja", num_workers=2,
        )
        assert ctx.device == "cpu"
        assert ctx.model_name == "medium"
        assert ctx.language == "ja"

    def test_avg_word_confidence_empty(self):
        score = WhisperAdapter._avg_word_confidence([])
        assert score == 1.0

    def test_avg_word_confidence_normal(self):
        words = [
            {"word": "hello", "score": 0.95},
            {"word": "world", "score": 0.85},
        ]
        score = WhisperAdapter._avg_word_confidence(words)
        assert 0.89 < score < 0.91

    def test_result_to_patches_structure(self):
        """验证 _result_to_patches 输出的 patch 结构"""
        result = {
            "segments": [
                {"start": 0.0, "end": 2.5, "text": "Hello world",
                 "words": [{"word": "Hello", "start": 0.0, "end": 0.8, "score": 0.95}]},
                {"start": 3.0, "end": 5.0, "text": "How are you",
                 "words": [{"word": "How", "start": 3.0, "end": 3.5, "score": 0.90}]},
            ],
            "language": "en",
            "stats": {"total_words": 4, "segments_count": 2},
        }
        adapter = WhisperAdapter.__new__(WhisperAdapter)
        adapter.ctx = EngineContext(audio_path="/tmp/test.wav")
        patches = adapter._result_to_patches(result["segments"], result["language"], result["stats"])

        segment_patches = [p for p in patches if p.op == OpCode.SEGMENT_INSERT]
        meta_patches = [p for p in patches if p.op == OpCode.ANNOTATE]

        assert len(segment_patches) == 2
        assert len(meta_patches) == 1

        p0 = segment_patches[0]
        assert p0.target_id == "evt_001"
        assert p0.value["start"] == 0.0
        assert p0.value["end"] == 2.5
        assert p0.value["text"] == "Hello world"
        assert len(p0.value["words"]) == 1
        assert p0.author == "system"
        assert p0.confidence > 0

        m0 = meta_patches[0]
        assert m0.target_id == "timeline"
        assert m0.value["language"] == "en"


class TestWav2Vec2Adapter:
    """Wav2Vec2Adapter 测试（无子进程）"""

    def test_construct(self):
        adapter = Wav2Vec2Adapter(audio_path="/tmp/test.wav", language="en")
        assert adapter.audio_path == "/tmp/test.wav"
        assert adapter.language == "en"

    def test_refine_alignment_empty(self):
        adapter = Wav2Vec2Adapter(audio_path="/tmp/test.wav")
        patches = adapter.refine_alignment([])
        assert patches == []

    def test_extract_semantic_patches(self):
        adapter = Wav2Vec2Adapter(audio_path="/tmp/test.wav")
        patches = adapter.extract_semantic(["evt_001", "evt_002"], output_dir="/tmp/out")

        assert len(patches) == 2
        for p in patches:
            assert p.op == OpCode.ANNOTATE
            assert "semantic" in p.value
            assert "embedding_ref" in p.value["semantic"]

    def test_compute_delta(self):
        before = [{"score": 0.80}]
        after = [{"score": 0.90}]
        delta = Wav2Vec2Adapter._compute_delta(before, after)
        assert delta == 0.1


class TestASRScorer:
    """ASRScorer 联合评分验证"""

    def test_default_weights(self):
        scorer = ASRScorer()
        assert scorer.weights["asr"] == 0.40
        assert scorer.weights["alignment"] == 0.30
        assert sum(scorer.weights.values()) == 1.0

    def test_custom_weights(self):
        scorer = ASRScorer(weights={"asr": 0.5, "alignment": 0.3, "speaker_hint": 0.1, "semantic": 0.1})
        assert scorer.weights["asr"] == 0.5

    def test_score_segment_perfect(self):
        scorer = ASRScorer()
        es = TimelineEventState(TimelineEventIR(
            id="evt_001", start=0, end=1, text_ref="hello", speaker_ref=None,
        ))
        score = scorer.score_segment(es)
        assert score.composite == 1.0
        assert score.confidence_label == "high"

    def test_score_segment_with_data(self):
        scorer = ASRScorer()
        es = TimelineEventState(TimelineEventIR(
            id="evt_001", start=0, end=1, text_ref="hello", speaker_ref=None,
        ))
        es.asr.words = [
            {"word": "hello", "score": 0.85},
            {"word": "world", "score": 0.75},
        ]
        es.asr.confidence = 0.80
        es.speaker.confidence = 0.70

        score = scorer.score_segment(es)
        assert score.c_asr == 0.80
        assert score.c_speaker_hint == 0.70
        assert score.composite < 1.0

    def test_score_all_writes_runtime(self):
        scorer = ASRScorer()
        ir = TimelineProjectIR(
            events={
                "evt_001": TimelineEventIR(id="evt_001", start=0, end=1, text_ref="hi", speaker_ref=None),
                "evt_002": TimelineEventIR(id="evt_002", start=1.5, end=3, text_ref="bye", speaker_ref=None),
            },
        )
        state = TimelineProjectState(ir)
        scores = scorer.score_all(state)

        assert len(scores) == 2
        assert "evt_001" in scores
        assert "evt_002" in scores

        es1 = state.get_event("evt_001")
        assert "asr_score" in es1.runtime.engine_scores
        assert "score_components" in es1.provenance

    def test_confidence_labels(self):
        assert ASRScore("e1", composite=0.90).confidence_label == "high"
        assert ASRScore("e2", composite=0.70).confidence_label == "medium"
        assert ASRScore("e3", composite=0.50).confidence_label == "low"
        assert ASRScore("e4", composite=0.85).confidence_label == "high"
        assert ASRScore("e5", composite=0.60).confidence_label == "medium"


class TestLanguagePropagation:
    """检测到的源语言必须传播给对齐 (缺失时误用 en 模型对齐日语, 对齐结果截断)"""

    def test_detected_language_propagates_to_wav2vec2(self, monkeypatch):
        import core.passes.asr_composite_pass as mod
        from core.passes.asr_composite_pass import ASRCompositePass

        calls = {}

        class FakeWhisper:
            def __init__(self, ctx, workspace_dir=""):
                self.ctx = ctx

            def run(self):
                return [
                    Patch(id="asr_evt_001", target_id="evt_001", op=OpCode.SEGMENT_INSERT,
                          value={"start": 0.0, "end": 2.0, "text": "こんにちは",
                                 "words": [{"word": "こんにちは", "start": 0.0, "end": 2.0}],
                                 "language": "ja", "source": "faster-whisper"}),
                    Patch(id="asr_meta", target_id="timeline", op=OpCode.ANNOTATE,
                          value={"language": "ja"}, author="system"),
                ]

        class FakeWav2Vec2:
            def __init__(self, audio_path, language):
                calls["language"] = language

            def refine_alignment(self, segments):
                return []

            def extract_semantic(self, segment_ids, output_dir=""):
                return []

        monkeypatch.setattr(mod, "WhisperAdapter", FakeWhisper)
        monkeypatch.setattr(mod, "Wav2Vec2Adapter", FakeWav2Vec2)

        pass_ = ASRCompositePass(audio_path="/tmp/test.wav")
        pass_.apply()
        assert calls["language"] == "ja"


class TestMatchByOverlap:
    """时间重叠匹配 — whisperx 拆分/截断下不把词错植到错误 event"""

    @staticmethod
    def _mk_words(*pairs):
        return [{"word": f"w{i}", "start": s, "end": e, "score": 0.9}
                for i, (s, e) in enumerate(pairs)]

    def test_split_aligned_segments_union_onto_event(self):
        """whisperx 拆分会改变输出数量 — 索引映射会错位, 重叠匹配必须按时间归位"""
        adapter = Wav2Vec2Adapter(audio_path="/tmp/test.wav")
        segments = [
            {"start": 0.0, "end": 10.0, "text": "a b", "words": self._mk_words((0, 2), (3, 5))},
            {"start": 12.0, "end": 20.0, "text": "c d", "words": self._mk_words((12, 14), (15, 18))},
        ]
        # whisperx 把 seg[0] 拆成两段, seg[1] 原样 — 3 个输出 vs 2 个输入
        aligned = [
            {"start": 0.0, "end": 4.0, "text": "a b", "words": self._mk_words((0.1, 2.0))},
            {"start": 4.5, "end": 9.5, "text": "a b", "words": self._mk_words((5.0, 9.0))},
            {"start": 12.0, "end": 20.0, "text": "c d", "words": self._mk_words((12.5, 18.0))},
        ]
        patches = adapter._match_by_overlap(segments, aligned)
        by_target = {p.target_id: p for p in patches}
        assert set(by_target) == {"evt_001", "evt_002"}
        ev1 = by_target["evt_001"].value["word_timestamps"]
        ev2 = by_target["evt_002"].value["word_timestamps"]
        assert len(ev1) == 2 and len(ev2) == 1
        assert ev1 == sorted(ev1, key=lambda w: w["start"])
        assert ev2[0]["start"] == 12.5

    def test_truncated_alignment_uncovered_events_get_no_patch(self):
        """对齐截断时未覆盖的 event 不产出 patch — 保留 whisper 原始词"""
        adapter = Wav2Vec2Adapter(audio_path="/tmp/test.wav")
        segments = [
            {"start": 0.0, "end": 10.0, "text": "a", "words": self._mk_words((0, 10))},
            {"start": 12.0, "end": 20.0, "text": "b", "words": self._mk_words((12, 20))},
            {"start": 30.0, "end": 40.0, "text": "c", "words": self._mk_words((30, 40))},
        ]
        aligned = [
            {"start": 0.0, "end": 10.0, "text": "a", "words": self._mk_words((0.1, 9.9))},
            {"start": 12.0, "end": 20.0, "text": "b", "words": self._mk_words((12.1, 19.9))},
        ]  # 尾部截断 — evt_003 无 patch
        patches = adapter._match_by_overlap(segments, aligned)
        assert [p.target_id for p in patches] == ["evt_001", "evt_002"]

    def test_bad_words_filtered(self):
        """缺失/倒置/零长时间戳的词不进入 patch (adapter 边界清洗)"""
        adapter = Wav2Vec2Adapter(audio_path="/tmp/test.wav")
        segments = [{"start": 0.0, "end": 10.0, "text": "a", "words": []}]
        aligned = [{
            "start": 0.0, "end": 10.0, "text": "a",
            "words": [
                {"word": "ok", "start": 1.0, "end": 2.0},
                {"word": "none_start", "start": None, "end": 3.0},
                {"word": "none_end", "start": 4.0, "end": None},
                {"word": "inverted", "start": 5.0, "end": 4.0},
                {"word": "zero", "start": 0.0, "end": 0.0},
            ],
        }]
        patches = adapter._match_by_overlap(segments, aligned)
        assert len(patches) == 1
        words = patches[0].value["word_timestamps"]
        assert [w["word"] for w in words] == ["ok"]

    def test_no_overlap_segment_skipped(self):
        adapter = Wav2Vec2Adapter(audio_path="/tmp/test.wav")
        segments = [{"start": 0.0, "end": 10.0, "text": "a", "words": []}]
        aligned = [
            {"start": 0.0, "end": 10.0, "text": "a", "words": self._mk_words((0.1, 9.9))},
            {"start": 50.0, "end": 60.0, "text": "junk", "words": self._mk_words((50, 60))},
        ]
        patches = adapter._match_by_overlap(segments, aligned)
        assert [p.target_id for p in patches] == ["evt_001"]

    def test_invalid_aligned_boundary_skipped(self):
        adapter = Wav2Vec2Adapter(audio_path="/tmp/test.wav")
        segments = [{"start": 0.0, "end": 10.0, "text": "a", "words": []}]
        aligned = [
            {"start": None, "end": 10.0, "text": "a", "words": self._mk_words((0.1, 9.9))},
        ]
        patches = adapter._match_by_overlap(segments, aligned)
        assert patches == []


class TestPatchIdempotency:
    """Patch 幂等性验证"""

    def test_segment_insert_patch_structure(self):
        p = Patch(
            id="asr_evt_001", target_id="evt_001",
            op=OpCode.SEGMENT_INSERT,
            value={"start": 0.0, "end": 2.5, "text": "Hello", "words": [],
                   "language": "en", "source": "faster-whisper"},
            author="system", confidence=0.95,
        )
        assert p.op == OpCode.SEGMENT_INSERT
        assert p.op == "segment_insert"

    def test_refine_alignment_patch_structure(self):
        p = Patch(
            id="align_001", target_id="evt_001",
            op=OpCode.REFINE_ALIGNMENT,
            value={"word_timestamps": [
                {"word": "Hello", "start": 0.1, "end": 0.4, "score": 0.95},
            ], "confidence_delta": 0.03},
            author="system", confidence=0.95,
        )
        assert p.op == OpCode.REFINE_ALIGNMENT

    def test_same_input_same_output(self):
        """验证同一输入产生相同 patch 结构"""
        result1 = {
            "segments": [{"start": 0.0, "end": 1.0, "text": "Hi", "words": []}],
            "language": "en", "stats": {},
        }
        result2 = {
            "segments": [{"start": 0.0, "end": 1.0, "text": "Hi", "words": []}],
            "language": "en", "stats": {},
        }
        adapter = WhisperAdapter.__new__(WhisperAdapter)
        adapter.ctx = EngineContext(audio_path="/tmp/test.wav")
        p1 = adapter._result_to_patches(result1["segments"], result1["language"], result1["stats"])
        p2 = adapter._result_to_patches(result2["segments"], result2["language"], result2["stats"])
        assert len(p1) == len(p2)
        assert p1[0].value["text"] == p2[0].value["text"]
