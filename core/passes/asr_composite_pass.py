"""
ASRCompositePass — ASR 域三引擎编排 (Chapter 3 §3.1-3.4)

执行顺序:
  1. WhisperAdapter → SEGMENT_INSERT patches → 初始化 TimelineProjectState
  2. Wav2Vec2Adapter.refine_alignment → REFINE_ALIGNMENT patches → 精炼词级时间戳
  3. Wav2Vec2Adapter.extract_semantic → ANNOTATE patches → 写入 semantic 槽位
  4. [可选] WordLevelRefiner → speaker probability → 写入 speaker 槽位

这是整个 Timeline IR 的入口 Pass，将原始音频转换为结构化的 IR 状态。
"""
from __future__ import annotations
from core.engine.pass_base import TimelinePass
from core.ir.timeline_event import TimelineEventIR
from core.ir.speaker import SpeakerNodeIR
from core.ir.project import TimelineProjectIR
from core.runtime.project_state import TimelineProjectState
from core.runtime.patch import Patch, OpCode
from core.runtime.patch_engine import PatchEngine
from core.adapters.whisper_adapter import WhisperAdapter, EngineContext
from core.adapters.wav2vec2_adapter import Wav2Vec2Adapter


class ASRCompositePass(TimelinePass):
    """ASR 复合 Pass — 将音频转换为带对齐和语义信息的 TimelineProjectState。

    依赖: [] (无依赖，这是入口 Pass)
    """

    name = "asr_composite"
    depends_on: list[str] = []

    def __init__(self, audio_path: str = "", context: EngineContext | None = None,
                 enable_speaker_refine: bool = False,
                 speaker_timeline: list | None = None):
        self.audio_path = audio_path
        self.ctx = context or EngineContext(audio_path=audio_path)
        self.enable_speaker_refine = enable_speaker_refine
        self.speaker_timeline = speaker_timeline

    def apply(self, state: TimelineProjectState | None = None) -> TimelineProjectState:
        """执行完整 ASR 流程，返回填充了 asr/semantic 槽位的 ProjectState。"""
        engine = PatchEngine()

        # Step 1: Whisper → SEGMENT_INSERT patches
        whisper = WhisperAdapter(self.ctx)
        asr_patches = whisper.run()
        segment_patches = [p for p in asr_patches if p.op == OpCode.SEGMENT_INSERT]
        meta_patches = [p for p in asr_patches if p.op == OpCode.ANNOTATE]

        state = self._bootstrap_state(segment_patches)

        for p in meta_patches:
            state.add_global_patch(p)

        # Step 2: Wav2Vec2 对齐精炼
        wav2vec = Wav2Vec2Adapter(
            audio_path=self.audio_path, language=self.ctx.language or "en",
        )
        segments_for_align = self._collect_segments(state)
        if segments_for_align:
            align_patches = wav2vec.refine_alignment(segments_for_align)
            for p in align_patches:
                engine.apply(state, p)

        # Step 3: Wav2Vec2 semantic embedding
        seg_ids = [es.id for es in state.sorted_events()]
        sem_patches = wav2vec.extract_semantic(seg_ids)
        for p in sem_patches:
            engine.apply(state, p)

        # Step 4: Speaker refine (optional)
        if self.enable_speaker_refine and self.speaker_timeline:
            self._refine_speakers(state)

        return state

    # ── internal ──────────────────────────────────────────

    def _bootstrap_state(self, patches: list[Patch]) -> TimelineProjectState:
        """从 SEGMENT_INSERT patches 构建初始 TimelineProjectState。"""
        events: dict[str, TimelineEventIR] = {}
        speakers: dict[str, SpeakerNodeIR] = {}

        for p in patches:
            v = p.value
            evt = TimelineEventIR(
                id=p.target_id,
                start=v.get("start", 0.0),
                end=v.get("end", 0.0),
                text_ref=v.get("text", ""),
                speaker_ref=None,
                source="asr",
            )
            events[p.target_id] = evt

        ir = TimelineProjectIR(events=events, speakers=speakers)
        state = TimelineProjectState(ir)

        for p in patches:
            es = state.get_event(p.target_id)
            if es:
                es.asr.update({
                    "words": p.value.get("words", []),
                    "confidence": p.confidence,
                    "language": p.value.get("language", ""),
                })
                es.provenance.update({
                    "engine": p.value.get("source", "faster-whisper"),
                    "confidence": p.confidence,
                })

        return state

    def _collect_segments(self, state: TimelineProjectState) -> list[dict]:
        """收集 state 中的 segments 用于 wav2vec2 对齐。"""
        segments = []
        for es in state.sorted_events():
            words = es.asr.get("words", [])
            segments.append({
                "text": es.ir.text_ref,
                "start": es.start,
                "end": es.end,
                "words": [{"word": w.get("word", ""), "start": w.get("start", 0),
                           "end": w.get("end", 0)} for w in words],
            })
        return segments

    def _refine_speakers(self, state: TimelineProjectState) -> None:
        """运行 WordLevelRefiner 进行说话人概率精炼。"""
        try:
            from core.refiner import WordLevelRefiner
            all_words = []
            for es in state.sorted_events():
                for w in es.asr.get("words", []):
                    w_copy = dict(w)
                    w_copy["segment_id"] = es.id
                    all_words.append(w_copy)

            refiner = WordLevelRefiner()
            refined = refiner.refine(all_words, self.speaker_timeline)

            for w in refined["words"]:
                es = state.get_event(w.get("segment_id", ""))
                if es and "speaker" in w:
                    es.speaker["speaker_id"] = w["speaker"]
                    es.speaker["confidence"] = w.get("speaker_confidence", 0.0)
        except ImportError:
            pass
