"""
LLMTranslationPass — 标签化纯文本 LLM 翻译 + 质量元数据 (v2, Ch14)

translate_fn 可返回 dict 携带质量元数据，结果写入 provenance 槽位。
"""
from __future__ import annotations
import re
from core.engine.pass_base import TimelinePass
from core.runtime import TimelineProjectState, Patch, PatchEngine, SynthesisEngine, OpCode


class LLMTranslationPass(TimelinePass):
    """标签化纯文本翻译 Pass。

    translate_fn 签名:
      - str: 向后兼容（纯文本）
      - dict: {"text": "...", "similarity": 0.85, "ppl": 45.2, ...}
    """

    name = "llm_translation"
    depends_on: list[str] = []

    def __init__(self, translate_fn=None, quality_gate_enabled: bool = False):
        self._translate_fn = translate_fn or self._mock_translate
        self.quality_gate_enabled = quality_gate_enabled
        self._resolved_config: dict | None = None

    def configure(self, resolved_config: dict | None = None) -> None:
        cfg = resolved_config or {}
        self._resolved_config = cfg
        if cfg.get("gate_mode", "OFF") != "OFF":
            self.quality_gate_enabled = True

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
            result = self._translate_fn(tagged_text)
        except Exception:
            return state

        if isinstance(result, dict):
            translated_text = result.get("text", "")
            quality_meta = {k: v for k, v in result.items() if k != "text"}
        else:
            translated_text = result
            quality_meta = {}

        translations = self._parse_tagged_response(translated_text)
        engine = PatchEngine()
        for event_id, trans_text in translations.items():
            engine.apply(state, Patch(
                id=f"trans_{event_id}", target_id=event_id,
                op=OpCode.UPDATE_TRANSLATION,
                value={"translation": trans_text}, author="ai",
            ))
            if quality_meta:
                es = state.get_event(event_id)
                if es:
                    es.provenance["translation_engine"] = quality_meta.get("engine", "llm")
                    trans = es.translation
                    if isinstance(trans, str):
                        trans = {"text": trans}
                    for k in ("similarity", "ppl", "gate_decision"):
                        if k in quality_meta:
                            trans[k] = quality_meta[k]
                    es._data["translation"] = trans

        return state

    def _parse_tagged_response(self, response: str) -> dict[str, str]:
        result = {}
        pattern = re.compile(r'\[(evt_\d+)\]\s*(.+?)(?=\[evt_|$)', re.DOTALL)
        for match in pattern.finditer(response):
            result[match.group(1)] = match.group(2).strip()
        return result

    @staticmethod
    def _mock_translate(tagged_text: str) -> str:
        lines = tagged_text.split("\n")
        translated = []
        for line in lines:
            if line.startswith("[evt_"):
                bracket_end = line.index("] ")
                eid = line[:bracket_end + 1]
                translated.append(f"{eid} [TR] {line[bracket_end + 2:]}")
            else:
                translated.append(line)
        return "\n".join(translated)
