"""
PreprocessTranslationPass — 翻译预处理: 生成"翻译圣经" (翻译重构 Step 2)

每片一次的大上下文 LLM 调用, 通读全量转录, 产出 TranslationBible:
  领域 / 摘要 / 风格指令 / 术语译法表 / ASR 纠错表。

设计要点 (用户定调: 智能前置, 不靠事后弥补):
  - 证据校验门: hotword.src / correction.wrong 必须逐字出现在转录原文,
    幻觉条目确定性丢弃+日志 — LLM 提案经机械校验才成为可信事实。
  - L0 人工词典合并: 人工永远赢, 冲突自动项丢弃+日志, 绝不静默覆盖。
  - 幂等: bible 已存在且非 force → 跳过 (重跑/persist 复用免费)。
  - 禁止兜底: LLM 调用彻底失败 → TranslationError 响亮上抛
    (bible 缺失会让术语失约, 静默继续就是重演中英混事故)。

产物写 state.ir.translation_bible (项目级元数据, 随 timeline.json 持久化),
下游 LLMTranslationPass 经 _bible_from_state 读取。生产者 pass, 不走 Patch。
"""
from __future__ import annotations

import dataclasses
import logging

from core.engine.pass_base import TimelinePass
from core.runtime import TimelineProjectState, SynthesisEngine
from pipeline.translation_bible import (
    PREPROCESS_PROMPT, PREPROCESS_TOKEN_BUDGET,
    SPEAKER_PROFILE_PROMPT, build_speaker_blocks,
    load_manual_glossary, merge_manual_glossary,
    parse_bible_response, parse_speaker_profiles, render_transcript,
)

logger = logging.getLogger(__name__)


class PreprocessTranslationPass(TimelinePass):
    """翻译预处理 — 全片一次, 产出 TranslationBible 写项目级元数据。"""

    name = "preprocess_translation"
    depends_on = ["segmentation"]

    def __init__(
        self,
        preprocess_fn=None,
        profile_fn=None,
        target_lang: str = "zh",
        source_lang: str = "",
        force: bool = False,
        manual_terms: dict | None = None,
        enable_profiles: bool = True,
    ):
        """
        Args:
            preprocess_fn: (user_prompt) -> dict (LLM 原始 JSON)。
                None → apply 时用 SentenceTranslator.call_json。
            profile_fn: 说话人画像调用, 签名同 preprocess_fn; None → 复用前者。
            force: True 时忽略已有 bible 重新生成。
            manual_terms: 注入测试用人工词典; None → 从 config 加载。
            enable_profiles: 是否做说话人画像 (第二发独立调用)。
        """
        self._preprocess_fn = preprocess_fn
        self._profile_fn = profile_fn
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.force = force
        self._manual_terms = manual_terms
        self.enable_profiles = enable_profiles
        self._engine_name = "llm"

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        existing = getattr(state.ir, "translation_bible", None) or {}
        if existing.get("hotwords") or existing.get("summary"):
            if not self.force:
                logger.info("translation_bible 已存在, 跳过预处理 (force 可重生成)")
                return state

        rendered = SynthesisEngine().render_all(state)
        items = [r for r in rendered if r.get("text", "").strip()]
        if not items:
            logger.warning("无文本 event, 预处理跳过")
            return state

        source_lang = self._resolve_source_lang(state)
        full_text = render_transcript(items, budget_tokens=PREPROCESS_TOKEN_BUDGET)

        from pipeline.translation_bible import _lang_name
        prompt = PREPROCESS_PROMPT.format(
            src_language=_lang_name(source_lang),
            dst_language=_lang_name(self.target_lang),
            full_text=full_text,
        )

        fn = self._resolve_fn()
        data = fn(prompt)          # TranslationError 响亮上抛, 不兜底

        bible = parse_bible_response(data, full_text, engine=self._engine_name)
        manual = self._manual_terms
        if manual is None:
            manual = load_manual_glossary()
        bible = merge_manual_glossary(bible, manual)

        # Step 3: 说话人画像 (独立第二发; 失败只降级不拖垮已生成的 bible)
        speakers_in_items = {it.get("speaker") for it in items if it.get("speaker")}
        if speakers_in_items and self.enable_profiles:
            try:
                from pipeline.translation_bible import _lang_name
                pfn = self._profile_fn or fn
                pdata = pfn(SPEAKER_PROFILE_PROMPT.format(
                    domain=bible.domain or "未知",
                    summary=bible.summary or "(无)",
                    dst_language=_lang_name(self.target_lang),
                    speaker_blocks=build_speaker_blocks(items),
                ))
                bible.speakers = parse_speaker_profiles(pdata, speakers_in_items)
            except Exception as e:
                logger.warning("说话人画像失败, 本片降级为无画像继续: %s", e)

        state.ir = dataclasses.replace(
            state.ir, translation_bible=bible.to_dict(),
        )
        logger.info(
            "translation_bible 已生成: domain=%s, hotwords=%d (含人工 %d), "
            "corrections=%d, speakers=%d",
            bible.domain or "?",
            len(bible.hotwords),
            sum(1 for h in bible.hotwords if h.get("origin") == "manual"),
            len(bible.corrections),
            len(bible.speakers),
        )
        return state

    # ── internal ──────────────────────────────────────────

    def _resolve_fn(self):
        if self._preprocess_fn is not None:
            return self._preprocess_fn
        from pipeline.translation_llm import SentenceTranslator
        translator = SentenceTranslator.from_config()
        self._engine_name = translator.model
        return translator.call_json

    def _resolve_source_lang(self, state: TimelineProjectState) -> str:
        if self.source_lang:
            return self.source_lang
        if state.ir.language:
            return state.ir.language
        for es in state.sorted_events():
            lg = es.asr.get("language", "")
            if lg:
                return lg
        return "en"
