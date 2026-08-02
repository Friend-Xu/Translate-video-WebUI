"""
LLMTranslationPass — 逐句并发 LLM 翻译 (翻译引擎重构 Step 1)

取代旧"标签化整批一次调用"实现 — 旧实现的结构性缺陷:
  单次调用 max_tokens 截断后正则只解析半截, 缺失 event 静默无译文;
  无上下文、无术语约束、无说话人信息 (中英混/语域混乱的根源)。

新实现 (局部窗口 + 全局文档):
  system: 规则手册 + 全量转录(预算制) + TranslationBible + 当前 speaker
          — 跨全部调用字节一致 (DeepSeek 前缀缓存命中)
  user:   ±window 邻居句(跨 speaker) + [待译] 当前句
  调用:   逐句并发 ThreadPoolExecutor, json_object 严格输出, 重试后
          失败置 review flag (禁止兜底, 绝不静默 mock)

这是生产者 pass — 直写 translation slot, 不走 Patch (Patch 仅用户编辑)。
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor

from core.engine.pass_base import TimelinePass
from core.runtime import TimelineProjectState, SynthesisEngine
from pipeline.translation_bible import (
    TranslationBible, render_system_prompt, render_transcript,
)

logger = logging.getLogger(__name__)

_DEFAULT_CONCURRENCY = 8


class LLMTranslationPass(TimelinePass):
    """逐句并发翻译 — 局部邻居窗口 + 全局 bible/全文。"""

    name = "llm_translation"
    depends_on: list[str] = []

    def __init__(
        self,
        translate_fn=None,
        target_lang: str = "zh",
        source_lang: str = "",
        concurrency: int | None = None,
        window: int = 1,
        bible: TranslationBible | None = None,
    ):
        """
        Args:
            translate_fn: 逐句翻译函数 (user_message, system_prompt) -> dst_text。
                None → apply 时从 config/translate.yaml 构建 SentenceTranslator。
            window: 邻居上下文半径 (句数, 跨 speaker)。
            bible: 预处理产出的翻译圣经; None → 空默认 (Step 2 由
                PreprocessTranslationPass 写入项目级元数据后自动读取)。
        """
        self._translate_fn = translate_fn
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.concurrency = concurrency
        self.window = max(0, window)
        self.bible = bible
        self._engine_name = "llm"

    def apply(self, state: TimelineProjectState) -> TimelineProjectState:
        rendered = SynthesisEngine().render_all(state)
        items = [r for r in rendered if r.get("text", "").strip()]
        if not items:
            return state

        source_lang = self._resolve_source_lang(state)
        bible = self.bible or self._bible_from_state(state)
        transcript = render_transcript(items)

        # 每 speaker 一份 system prompt: 共享前缀命中缓存, 档案尾部各异。
        # 仅当 bible 有该 speaker 画像时才加尾部 — 空 bible 时全部调用
        # 字节一致 (缓存全命中)。
        speakers_present = {it.get("speaker") for it in items}
        system_by_speaker: dict = {}
        for spk in speakers_present:
            current = spk if spk in bible.speakers else None
            system_by_speaker[spk] = render_system_prompt(
                bible, source_lang, self.target_lang,
                transcript=transcript, current_speaker=current,
            )

        fn = self._resolve_translate_fn()
        concurrency = self.concurrency or self._concurrency_from_config()

        # 并发只收集结果, 写 state 回主线程 (确定性 + 无线程竞争)
        def _work(idx):
            user = build_user_message(items, idx, self.window)
            system = system_by_speaker[items[idx].get("speaker")]
            return idx, fn(user, system)

        results: dict[int, str] = {}
        failures: dict[int, Exception] = {}
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            futures = {pool.submit(_work, i): i for i in range(len(items))}
            for fut, i in futures.items():
                try:
                    _, dst = fut.result()
                    results[i] = dst
                except Exception as e:  # TranslationError 等 — 逐句降级为 flag
                    failures[i] = e

        translated = 0
        for i, r in enumerate(items):
            es = state.get_event(r["id"])
            if es is None:
                continue
            if i in results:
                es.translation.text = results[i]
                es.translation.engine = self._engine_name
                translated += 1
            else:
                flags = es.review.flags
                if "translation_failed" not in flags:
                    flags.append("translation_failed")
                es.review.needs_human_review = True

        if failures:
            sample = next(iter(failures.values()))
            logger.warning(
                "翻译完成 %d/%d, %d 句失败已置人工审核 (示例: %s)",
                translated, len(items), len(failures), sample,
            )
        else:
            logger.info("翻译完成 %d/%d", translated, len(items))
        return state

    # ── internal ──────────────────────────────────────────

    def _resolve_translate_fn(self):
        if self._translate_fn is not None:
            return self._translate_fn
        from pipeline.translation_llm import SentenceTranslator
        translator = SentenceTranslator.from_config()
        self._engine_name = translator.model
        return translator.translate

    def _resolve_source_lang(self, state: TimelineProjectState) -> str:
        if self.source_lang:
            return self.source_lang
        if state.ir.language:
            return state.ir.language
        for es in state.sorted_events():
            lg = es.asr.language
            if lg:
                return lg
        return "en"

    @staticmethod
    def _bible_from_state(state: TimelineProjectState) -> TranslationBible:
        """读 PreprocessTranslationPass 写入的项目级 bible; 缺失 → 空默认。

        manual 词条不随 bible 落盘 (配置级输入), 渲染前经
        with_manual_glossary 从 config 实时合并 (L0 人工永远赢)。
        """
        from pipeline.translation_bible import with_manual_glossary
        return with_manual_glossary(TranslationBible.from_dict(
            getattr(state.ir, "translation_bible", None)
        ))

    @staticmethod
    def _concurrency_from_config() -> int:
        # P5-A: 前端 translate_concurrency 经 LLM_CONCURRENCY env 注入, 优先于 yaml
        if os.environ.get("LLM_CONCURRENCY"):
            try:
                return max(1, int(os.environ["LLM_CONCURRENCY"]))
            except (ValueError, TypeError):
                pass
        try:
            from pipeline.translation_llm import load_translate_config
            cfg = load_translate_config()
            conc = cfg.get("concurrency", {})
            if isinstance(conc, dict) and conc.get("max_workers"):
                return int(conc["max_workers"])
        except Exception:
            pass
        return _DEFAULT_CONCURRENCY


def build_user_message(items: list[dict], idx: int, window: int = 1) -> str:
    """构造逐句 user 消息 — 纯函数。

    邻居取时间相邻 event (跨 speaker — 指代常在对手台词里),
    只给原文; 当前句用 [待译] 标注。边界少一侧就少一行, 不补占位。
    """
    lines: list[str] = []
    lo = max(0, idx - window)
    hi = min(len(items), idx + window + 1)
    for i in range(lo, hi):
        r = items[i]
        spk = f"[{r['speaker']}] " if r.get("speaker") else ""
        text = r.get("text", "").strip()
        if i == idx:
            lines.append(f"[待译] {spk}{text}")
        else:
            lines.append(f"[上下文·勿译] {spk}{text}")
    return "\n".join(lines)
