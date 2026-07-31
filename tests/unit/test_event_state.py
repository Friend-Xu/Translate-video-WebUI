"""
TimelineEventState 九槽位 + Patch 排序测试 (批次10)
"""
import pytest
from core.runtime.patch import Patch
from core.ir.timeline_event import TimelineEventIR
from core.runtime.event_state import TimelineEventState


@pytest.mark.unit
class TestEventStateSlots:

    def _make_es(self):
        return TimelineEventState(TimelineEventIR(id="e1", start=0.0, end=1.0, speaker_ref="S1", text_ref="hello"))

    def test_slot_lazy_init(self):
        es = self._make_es()
        # Phase 3A: 类型化对象, 读缺失槽位返回空对象 (不产生幽灵 dict)
        assert isinstance(es.tts, object)
        assert es.tts.audio_ref == ""
        assert es.tts.config == {}

    def test_slot_isolation(self):
        es = self._make_es()
        es.tts.engine = "chattts"
        es.asr.config["model"] = "turbo"
        assert es.tts.engine == "chattts"
        assert es.tts.duration == 0.0          # 类型化字段隔离
        assert es.asr.config["model"] == "turbo"
        assert es.asr.language == ""

    def test_review_runtime_isolation(self):
        es = self._make_es()
        es.review.flags = ["flagged"]
        es.runtime.status = "ready"
        assert es.review.flags == ["flagged"]
        assert es.runtime.tts_status == ""

    def test_all_nine_slots(self):
        es = self._make_es()
        slots = [es.asr, es.speaker, es.semantic, es.translation,
                 es.tts, es.emotion, es.review, es.runtime, es.provenance]
        assert all(s is not None for s in slots)

    def test_patch_sorting(self):
        es = self._make_es()
        es.add_patch(Patch(id="p_new", target_id="e1", op="replace", value={"v": 2}, timestamp=200.0))
        es.add_patch(Patch(id="p_old", target_id="e1", op="replace", value={"v": 1}, timestamp=100.0))
        assert es.patches[0].id == "p_old"

    def test_ir_readonly(self):
        ir = TimelineEventIR(id="e1", start=0.0, end=1.0, speaker_ref="S1", text_ref="hello")
        es = TimelineEventState(ir)
        assert es.ir is ir
        assert es.start == 0.0

    def test_derivatives_compat(self):
        es = self._make_es()
        es.derivatives["custom"] = 42
        assert es.derivatives["custom"] == 42
