"""
SRTExportPass — 使用 SynthesisEngine 渲染并输出 SRT 文件
"""
from __future__ import annotations
import os
from core.engine.pass_base import TimelinePass
from core.runtime import TimelineProjectState, SynthesisEngine


class SRTExportPass(TimelinePass):
    """SynthesisEngine.render_all() → .srt 文件"""

    name = "srt_export"
    depends_on: list[str] = []

    def __init__(self, output_path: str = ""):
        self.output_path = output_path

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        synth = SynthesisEngine()
        rendered = synth.render_all(state)
        srt_content = self._format_srt(rendered)

        if self.output_path:
            os.makedirs(os.path.dirname(self.output_path) or ".", exist_ok=True)
            with open(self.output_path, "w", encoding="utf-8") as f:
                f.write(srt_content)

        return state

    def _format_srt(self, rendered: list[dict]) -> str:
        lines = []
        index = 1
        for r in rendered:
            text = r.get("translation") or r.get("text", "")
            if not text.strip():
                continue
            lines.append(str(index))
            lines.append(f"{self._to_srt_time(r['start'])} --> {self._to_srt_time(r['end'])}")
            lines.append(text.strip())
            lines.append("")
            index += 1
        return "\n".join(lines)

    @staticmethod
    def _to_srt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
