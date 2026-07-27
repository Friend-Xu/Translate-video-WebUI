"""
RefineTranslationPass — 低分译文重翻闭环 (翻译引擎重构 Step 4)

移植旧 SRT_Translator Tier-1 的"低分→对比重翻→验证采纳"思路到新架构:
  quality_check 判 B/C 的句子, 带"原文+初译+低分提示"重翻一轮,
  重评分后改善则采纳, 未改善则回退初译并 flag 人工 (refine_rejected)。

与旧实现的差异:
  - 重翻粒度天然是单句 (逐句架构), 无需旧代码的 group bookkeeping
  - system prompt 复用翻译圣经 (术语/风格/说话人档案约束同样生效)
  - 只重翻一轮, 不循环 — 仍低分交人工, 不在机器里空转

生产者 pass, 直写 translation slot; 重评分走注入的 QualityStrategy。
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from core.engine.pass_base import TimelinePass
from core.runtime import TimelineProjectState, SynthesisEngine
from pipeline.translation_bible import render_system_prompt, render_transcript

logger = logging.getLogger(__name__)

_REFINE_NOTE = (
    "初译: {old}\n"
    "质量评估初译得分 {score:.2f} 偏低。请重新翻译: 更准确传达原意、"
    "更自然流畅, 严格遵守术语表与说话人语域。"
)


class RefineTranslationPass(TimelinePass):
    """低分重翻闭环 — quality_check 之后运行。"""

    name = "refine_translation"
    depends_on = ["translation_quality"]

    def __init__(
        self,
        translate_fn=None,
        quality_strategy=None,
        target_lang: str = "zh",
        window: int = 1,
        concurrency: int | None = None,
    ):
        self._translate_fn = translate_fn
        self._strategy = quality_strategy
        self.target_lang = target_lang
        self.window = max(0, window)
        self.concurrency = concurrency
        self._engine_name = "llm"

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        if self._strategy is None:
            logger.warning("无 quality_strategy, 重翻闭环跳过 (响亮记录)")
            return state

        candidates = []
        for es in state.sorted_events():
            trans = es.translation
            old_text = trans.get("text", "")
            gate = es.review.get("gate_decision", "")
            if old_text.strip() and gate in ("B", "C"):
                candidates.append(es)

        if not candidates:
            return state

        rendered = {r["id"]: r for r in SynthesisEngine().render_all(state)}
        items = [rendered[es.id] for es in candidates if es.id in rendered]
        bible = self._bible_from_state(state)
        source_lang = self._resolve_source_lang(state)
        transcript = render_transcript(
            [r for r in rendered.values() if r.get("text", "").strip()]
        )

        speakers_present = {it.get("speaker") for it in items}
        system_by_speaker = {
            spk: render_system_prompt(
                bible, source_lang, self.target_lang,
                transcript=transcript,
                current_speaker=spk if spk in bible.speakers else None,
            )
            for spk in speakers_present
        }

        fn = self._resolve_translate_fn()
        concurrency = self.concurrency or 8

        def _work(es):
            old = es.translation["text"]
            score = es.translation.get("quality_score", 0.0)
            user = (f"[待译] {rendered[es.id]['text']}\n"
                    + _REFINE_NOTE.format(old=old, score=score))
            return fn(user, system_by_speaker[rendered[es.id].get("speaker")])

        refined: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = {pool.submit(_work, es): es for es in candidates}
            for fut, es in futures.items():
                try:
                    refined[es.id] = fut.result()
                except Exception as e:
                    logger.warning("重翻调用失败 (%s), 保留初译: %s", es.id, e)

        # 暂写新译 → 全量重评分 → 按新旧分裁决采纳/回退
        old_texts = {}
        old_scores = {}
        for eid, new_text in refined.items():
            es = state.get_event(eid)
            old_texts[eid] = es.translation["text"]
            old_scores[eid] = float(es.translation.get("quality_score", 0.0))
            es.translation["text"] = new_text
            es.translation["engine"] = self._engine_name + "_refine"

        verdicts = self._strategy.score_batch(state)

        accepted = 0
        for eid in refined:
            es = state.get_event(eid)
            v = verdicts.get(eid)
            new_score = v.score if v else 0.0
            if v is not None and new_score > old_scores[eid]:
                es.translation["quality_score"] = new_score
                es.review["gate_decision"] = v.gate_decision
                if v.gate_decision == "A" and not es.review.get("flags"):
                    es.review["needs_human_review"] = False
                accepted += 1
            else:
                es.translation["text"] = old_texts[eid]
                es.translation["quality_score"] = old_scores[eid]
                flags = es.review.setdefault("flags", [])
                if "refine_rejected" not in flags:
                    flags.append("refine_rejected")
                es.review["needs_human_review"] = True

        logger.info("重翻闭环: %d 候选, %d 采纳, %d 回退",
                    len(candidates), accepted, len(refined) - accepted)
        return state

    # ── internal ──────────────────────────────────────────

    def _resolve_translate_fn(self):
        if self._translate_fn is not None:
            return self._translate_fn
        from pipeline.translation_llm import SentenceTranslator
        translator = SentenceTranslator.from_config()
        self._engine_name = translator.model
        return translator.translate

    @staticmethod
    def _bible_from_state(state: TimelineProjectState):
        from pipeline.translation_bible import TranslationBible
        return TranslationBible.from_dict(
            getattr(state.ir, "translation_bible", None)
        )

    def _resolve_source_lang(self, state: TimelineProjectState) -> str:
        if state.ir.language:
            return state.ir.language
        for es in state.sorted_events():
            lg = es.asr.get("language", "")
            if lg:
                return lg
        return "en"
