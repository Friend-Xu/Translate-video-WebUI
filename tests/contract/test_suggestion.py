"""
suggestion 契约测试 (架构收束 P5) — timeline/ 旧系统迁移到 core/suggestion

覆盖: signal 提取 / scorer / planner / model / opcode / api 字段形状。
输出契约 = 旧 TimelinePatch.to_dict 字段形状 (前端/patch_adapter 零改动)。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest

from core.suggestion.signal import extract_signals, extract_segment_signals
from core.suggestion.scorer import score_signals, score_all, confidence_label
from core.suggestion.planner import plan
from core.suggestion.opcode import SuggestionOpCode as OpCode, is_valid_opcode
from core.suggestion.model import SuggestionPatch
from core.suggestion.api import generate_candidate_patches


def _segs():
    return [
        {"id": "seg_001", "start": 0, "end": 2, "text": "Hello.",
         "speaker": "S1", "words": []},
        {"id": "seg_002", "start": 2, "end": 4, "text": "World.",
         "speaker": "S1", "words": []},
        {"id": "seg_003", "start": 5, "end": 6, "text": "Bye.",
         "speaker": "S2", "words": []},
    ]


class TestExtractSignals:
    """extract_signals — 相邻 segment pair 信号提取"""

    def test_same_speaker(self):
        signals = extract_signals(_segs()[:2])
        assert signals[0]["same_speaker"] is True

    def test_different_speaker(self):
        signals = extract_signals(_segs()[1:])
        assert signals[0]["same_speaker"] is False

    def test_segment_signals(self):
        seg = _segs()[0]
        sig = extract_segment_signals(seg)
        assert sig["duration"] == 2
        assert sig["char_count"] == 6
        assert sig["sentence_enders"] == 1

    def test_short_input(self):
        assert extract_signals([]) == []
        assert extract_signals([_segs()[0]]) == []


class TestScorer:
    """加权评分 + 置信度标签"""

    def test_confidence_labels(self):
        assert confidence_label(0.95) == "high"
        assert confidence_label(0.75) == "medium"
        assert confidence_label(0.5) == "low"
        assert confidence_label(0.91) == "high"
        assert confidence_label(0.70) == "medium"

    def test_score_all_len(self):
        segs = _segs()
        pair = extract_signals(segs)
        sseg = [extract_segment_signals(s) for s in segs]
        scores = score_all(pair, sseg)
        assert len(scores) == 2


class TestPlanner:
    """plan — 确定性决策"""

    def test_plan_empty_without_signals(self):
        segs = _segs()
        assert plan(segs, [], []) == []

    def test_plan_merge_candidate(self):
        segs = [
            {"id": "a", "start": 0, "end": 1, "text": "hi", "speaker": "S1", "words": []},
            {"id": "b", "start": 1.1, "end": 2, "text": "but still", "speaker": "S1", "words": []},
        ]
        signals = extract_signals(segs)
        scores = score_all(signals)
        patches = plan(segs, signals, scores, min_confidence=0.3)
        assert patches, "same_speaker + 短间隔 + 承接词应产出 MERGE 建议"
        assert patches[0].opcode == OpCode.MERGE
        assert patches[0].targets == ["a", "b"]


class TestOpCode:
    def test_all_seven_values(self):
        values = {o.value for o in OpCode}
        assert values == {"MERGE", "SPLIT", "RETAG_SPEAKER", "SET_TRANSLATION",
                          "RELINK_WORDS", "ANNOTATE", "RESIZE"}

    def test_is_valid_opcode(self):
        assert is_valid_opcode("MERGE") is True
        assert is_valid_opcode("UNKNOWN") is False


class TestSuggestionPatch:
    """SuggestionPatch — 字段形状 = 旧 TimelinePatch 契约"""

    def test_to_dict_shape(self):
        p = SuggestionPatch(
            patch_id="patch_001", opcode=OpCode.MERGE,
            targets=["seg_001", "seg_002"],
        )
        d = p.to_dict()
        assert set(d.keys()) == {
            "patch_id", "opcode", "targets", "payload", "reason",
            "score", "confidence", "parent_version", "idempotency_key",
            "author", "timestamp",
        }
        assert d["opcode"] == "MERGE"
        assert d["author"] == "system"

    def test_defaults_auto_filled(self):
        p = SuggestionPatch(patch_id="p1", opcode=OpCode.MERGE, targets=["s1", "s2"])
        assert p.timestamp != ""
        assert p.idempotency_key != ""

    def test_confidence_labels(self):
        assert SuggestionPatch(patch_id="p", opcode=OpCode.MERGE, targets=["a"],
                               confidence=0.95).confidence_label == "high"
        assert SuggestionPatch(patch_id="p", opcode=OpCode.MERGE, targets=["a"],
                               confidence=0.75).confidence_label == "medium"
        assert SuggestionPatch(patch_id="p", opcode=OpCode.MERGE, targets=["a"],
                               confidence=0.5).confidence_label == "low"


class TestGenerateCandidatePatches:
    """api — 字段形状契约 + v1 显式报错 (禁止兜底)"""

    def _mk_v2(self, tmp_path, segs=None):
        path = tmp_path / "timeline.json"
        data = {
            "schema_version": "2.0",
            "events": segs or _segs(),
            "speakers": {},
        }
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def test_result_shape(self, tmp_path):
        result = generate_candidate_patches(self._mk_v2(tmp_path))
        assert set(result.keys()) == {"patches", "high", "medium", "low"}
        for p in result["patches"]:
            assert set(p.keys()) == {
                "patch_id", "opcode", "targets", "payload", "reason",
                "score", "confidence", "parent_version", "idempotency_key",
                "author", "timestamp",
            }

    def test_v1_raises(self, tmp_path):
        path = tmp_path / "timeline.json"
        path.write_text(json.dumps({"version": "1.0", "timeline": []}),
                        encoding="utf-8")
        with pytest.raises(ValueError, match="v2"):
            generate_candidate_patches(str(path))

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            generate_candidate_patches(str(tmp_path / "nope.json"))

    def test_deterministic(self, tmp_path):
        p = self._mk_v2(tmp_path)
        r1 = generate_candidate_patches(p)
        r2 = generate_candidate_patches(p)
        assert r1 == r2
