"""
UIMapper — runtime state → WebUI JSON 格式

纯转换层，无业务逻辑，无副作用。
将 core/ 数据结构映射为现有 WebUI 期望的 speaker_lanes 格式。
"""
from __future__ import annotations
from core.runtime.project_state import TimelineProjectState
from core.runtime.synthesis import SynthesisEngine

SPEAKER_COLORS = [
    "#4CAF50", "#2196F3", "#FF9800", "#E91E63",
    "#9C27B0", "#00BCD4", "#FF5722", "#607D8B",
    "#795548", "#3F51B5", "#009688", "#CDDC39",
]


class UIMapper:
    """runtime state ↔ WebUI JSON 格式转换"""

    def __init__(self):
        self._synth = SynthesisEngine()

    def to_speaker_lanes(self, state: TimelineProjectState) -> list[dict]:
        """转换为 WebUI speaker_lanes 格式。

        Returns:
            [{"speaker": "SPEAKER_00", "display_name": "Speaker 00",
              "color": "#4CAF50", "segments": [...]}, ...]
        """
        rendered = self._synth.render_all(state)
        speaker_segments: dict[str, list[dict]] = {}

        for r in rendered:
            spk = r.get("speaker") or "UNKNOWN"
            speaker_segments.setdefault(spk, []).append({
                "id": r["id"],
                "start": r["start"],
                "end": r["end"],
                "text": r.get("text", ""),
                "translation": r.get("translation", ""),
            })

        lanes = []
        for i, (spk_id, segs) in enumerate(sorted(speaker_segments.items())):
            spk_ir = state.ir.speakers.get(spk_id)
            name = spk_ir.name if spk_ir and spk_ir.name else spk_id
            lanes.append({
                "speaker": spk_id,
                "display_name": name,
                "color": SPEAKER_COLORS[i % len(SPEAKER_COLORS)],
                "segments": segs,
            })

        return lanes

    def to_patch_log(self, state: TimelineProjectState) -> list[dict]:
        """提取所有 patches 为 WebUI patch_log 格式"""
        patches = list(state.global_patches)
        for es in state.event_states.values():
            patches.extend(es.patches)
        patches.sort(key=lambda p: p.timestamp)

        return [
            {
                "patch_id": p.id,
                "opcode": p.op,
                "targets": [p.target_id],
                "payload": p.value,
                "reason": [],
                "score": 0.0,
                "confidence": 1.0,
                "author": p.author,
                "timestamp": p.timestamp,
            }
            for p in patches
        ]
