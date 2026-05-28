"""
EmotionCompositePass — 情感智能层编排 (Chapter 15 §15.7)
"""
from __future__ import annotations
from core.engine.pass_base import TimelinePass
from core.runtime import TimelineProjectState, PatchEngine


class EmotionCompositePass(TimelinePass):

    name = "emotion_composite"
    depends_on: list[str] = []

    def __init__(self, skip_emotion: bool = False, skip_alignment: bool = False,
                 gate_mode: str = "strict", workspace_dir: str = ""):
        self.skip_emotion = skip_emotion; self.skip_alignment = skip_alignment
        self.gate_mode = gate_mode
        self._workspace_dir = workspace_dir
        self._resolved_config: dict | None = None

    def configure(self, resolved_config: dict | None = None) -> None:
        cfg = resolved_config or {}
        self._resolved_config = cfg
        if "enabled" in cfg:
            self.skip_emotion = not cfg["enabled"]
        if "gate_mode" in cfg:
            self.gate_mode = cfg["gate_mode"]

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        if self.skip_emotion:
            return state
        from core.adapters.emotion_recognizer_adapter import (
            EmotionRecognizerAdapter, EmotionRecognizerContext)
        from core.emotion.alignment_checker import EmotionAlignmentChecker
        from core.emotion.tts_router import EmotionTTSRouter
        from core.scoring.emotion_scorer import EmotionScorer
        from core.gates.emotion_gate import EmotionGate
        from core.emotion.emotion_space import EmotionVector

        engine = PatchEngine()
        recognizer = EmotionRecognizerAdapter(output_dir=self._workspace_dir)
        scorer = EmotionScorer(); gate = EmotionGate(mode=self.gate_mode)
        router = EmotionTTSRouter(); prev = None

        for es in state.sorted_events():
            text = es.ir.text_ref or ""
            trans_raw = es.translation
            trans = (trans_raw.get("text", "") if isinstance(trans_raw, dict) else str(trans_raw or "")) or es.derivatives.get("translation", "")

            ctx = EmotionRecognizerContext(text=text, segment_id=es.id,
                                           start=es.start, end=es.end)
            engine.apply(state, recognizer.recognize(ctx))

            ed = es.emotion
            ev = EmotionVector(**{k: ed.get(k, 0.0) for k in
                   ("emotion","valence","arousal","dominance","confidence","intensity")})

            if not self.skip_alignment and trans:
                ar = EmotionAlignmentChecker().check(ev, trans)
                es.emotion["translation_aligned"] = ar.aligned
                if ar.drift_type:
                    es.emotion["drift_type"] = ar.drift_type

            es.emotion["emotion_score"] = scorer.score(ev, prev).composite
            gr = gate.decide(ev, prev)
            es.emotion["gate_decision"] = gr.decision
            # WorkflowOrchestrator 读取: E1=accept, E2=downgrade, E3=repair
            emap = {"accept": "E1", "downgrade": "E2", "repair": "E3"}
            es.provenance["gate_decision"] = emap.get(gr.decision, "E1")

            route = router.route(ev)
            es.provenance["emotion_route"] = {
                "engine": route.engine, "priority": route.priority,
                "reason": route.reason}

            prev = ev

        return state
