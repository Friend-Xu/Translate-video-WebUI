"""
LLMTranslationPass — 标签化纯文本 LLM 翻译

提取事件的 [id] text_ref 拼成标签化纯文本发送给 LLM，
通过正则匹配返回结果，将翻译写入 derivatives["translation"]。
"""
from __future__ import annotations
import re
from core.engine.pass_base import TimelinePass
from core.runtime import TimelineProjectState, Patch, PatchEngine, SynthesisEngine


class LLMTranslationPass(TimelinePass):
    """标签化纯文本翻译 Pass。

    发送格式: [evt_001] 原文\\n[evt_002] 原文\\n...
    LLM 返回相同格式，正则匹配后写入 derivatives["translation"]。
    """

    name = "llm_translation"
    depends_on = ["asr_to_ir"]

    def __init__(self, translate_fn=None):
        self._translate_fn = translate_fn or self._mock_translate

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        synth = SynthesisEngine()
        rendered = synth.render_all(state)

        tagged_lines = []
        for r in rendered:
            text = r.get("text", "").strip()
            if text:
                tagged_lines.append(f"[{r['id']}] {text}")
        tagged_text = "\n".join(tagged_lines)

        if not tagged_text.strip():
            return state

        try:
            translated_text = self._translate_fn(tagged_text)
        except Exception:
            return state

        translations = self._parse_tagged_response(translated_text)
        engine = PatchEngine()
        for event_id, trans_text in translations.items():
            patch = Patch(
                id=f"trans_{event_id}",
                target_id=event_id,
                op="replace",
                value={"translation": trans_text},
                author="ai",
            )
            engine.apply(state, patch)

        return state

    def _parse_tagged_response(self, response: str) -> dict[str, str]:
        result = {}
        pattern = re.compile(r'\[(evt_\d+)\]\s*(.+?)(?=\[evt_|$)', re.DOTALL)
        for match in pattern.finditer(response):
            eid = match.group(1)
            text = match.group(2).strip()
            result[eid] = text
        return result

    @staticmethod
    def _mock_translate(tagged_text: str) -> str:
        lines = tagged_text.split("\n")
        translated = []
        for line in lines:
            if line.startswith("[evt_"):
                bracket_end = line.index("] ")
                eid = line[:bracket_end + 1]
                text = line[bracket_end + 2:]
                translated.append(f"{eid} [TR] {text}")
            else:
                translated.append(line)
        return "\n".join(translated)
