"""
ASRToIRPass — 将 ASR segments + speaker_timeline 转换为 TimelineProjectState

与旧 timeline/fusion.py 的 from_extract_result() 行为等价。
"""
from __future__ import annotations
from core.engine.pass_base import TimelinePass
from core.ir import TimelineEventIR, SpeakerNodeIR, TimelineProjectIR
from core.runtime import TimelineProjectState


class ASRToIRPass(TimelinePass):
    """ASR raw segments → TimelineProjectState"""

    name = "asr_to_ir"

    def __init__(
        self,
        segments: list[dict],
        speaker_timeline: list | None = None,
        audio_id: str = "",
    ):
        self.segments = segments
        self.speaker_timeline = speaker_timeline
        self.audio_id = audio_id

    def apply(self, state: TimelineProjectState | None = None) -> TimelineProjectState:
        speakers: dict[str, SpeakerNodeIR] = {}
        speaker_assignments = self._assign_speakers()
        events: dict[str, TimelineEventIR] = {}

        for i, seg in enumerate(self.segments):
            eid = f"evt_{i + 1:03d}"
            spk = speaker_assignments.get(i) or seg.get("speaker")
            if spk and spk not in speakers:
                speakers[spk] = SpeakerNodeIR(id=spk)

            events[eid] = TimelineEventIR(
                id=eid,
                start=seg.get("start", 0.0),
                end=seg.get("end", 0.0),
                speaker_ref=spk,
                text_ref=seg.get("text", "").strip(),
                source="asr",
            )

        ir = TimelineProjectIR(events=events, speakers=speakers)
        return TimelineProjectState(ir)

    def _assign_speakers(self) -> dict[int, str]:
        mapping: dict[int, str] = {}
        if not self.speaker_timeline:
            return mapping
        for i, seg in enumerate(self.segments):
            seg_mid = (seg.get("start", 0) + seg.get("end", 0)) / 2
            for spk_id, s_start, s_end, _ in self.speaker_timeline:
                if s_start <= seg_mid <= s_end:
                    mapping[i] = spk_id
                    break
        return mapping
