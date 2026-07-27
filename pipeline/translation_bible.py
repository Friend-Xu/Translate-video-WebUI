"""
translation_bible — 翻译圣经: 全局上下文文档 schema + prompt 渲染器 (翻译重构)

"局部窗口 + 全局文档"的全局层:
  - 全量转录全文 (预算制, 超长砍中段, 响亮记录)
  - TranslationBible 结构化执行层 (摘要/术语译法/ASR 纠错/实体/说话人档案)

Step 1: 空默认 bible + 语言对规则手册 + 转录渲染。
Step 2: PreprocessTranslationPass 产出真实 bible 并持久化。
Step 3: 说话人档案 + 长视频章节地图。

渲染器硬性契约 (DeepSeek 前缀缓存命中与正确性的前提):
  输出必须确定性 — 相同输入逐字节相同; 无时间戳、无随机序、
  章节顺序固定; 每句变化的内容 (当前 speaker 档案) 只能放最后。

零 core 依赖 (单向依赖: core → pipeline)。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

BIBLE_VERSION = 1

# 转录层 token 预算: 估计值 = 字符数 / 3 (保守, 混合语言)。
# 超长视频用章节地图替代全文 (Step 3); 本期砍中段保头尾。
TRANSCRIPT_TOKEN_BUDGET = 16000

MAX_HOTWORDS = 50
MAX_CORRECTIONS = 30


# ── Bible schema ───────────────────────────────────────────

@dataclass
class TranslationBible:
    """预处理产出的全局执行手册 — 项目级元数据, 持久化进 timeline.json。

    hotwords:    [{src, dst, evidence, count}]     术语 → 规定译法 (不写"保留")
    corrections: [{wrong, correct, evidence}]      ASR 高置信误识修正
    entities:    [{src, dst, gender, role}]        人名/作品名 → 标准译名
    speakers:    {speaker_id: {role, register, notes}}  说话人档案 (Step 3)
    """
    version: int = BIBLE_VERSION
    engine: str = ""
    domain: str = ""
    summary: str = ""
    style_guide: str = ""
    hotwords: list[dict] = field(default_factory=list)
    corrections: list[dict] = field(default_factory=list)
    entities: list[dict] = field(default_factory=list)
    speakers: dict[str, dict] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.summary or self.hotwords or self.corrections
                    or self.entities or self.style_guide)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "engine": self.engine,
            "domain": self.domain,
            "summary": self.summary,
            "style_guide": self.style_guide,
            "hotwords": self.hotwords,
            "corrections": self.corrections,
            "entities": self.entities,
            "speakers": self.speakers,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "TranslationBible":
        if not isinstance(data, dict):
            return cls()
        return cls(
            version=data.get("version", BIBLE_VERSION),
            engine=data.get("engine", ""),
            domain=data.get("domain", ""),
            summary=data.get("summary", ""),
            style_guide=data.get("style_guide", ""),
            hotwords=list(data.get("hotwords") or []),
            corrections=list(data.get("corrections") or []),
            entities=list(data.get("entities") or []),
            speakers=dict(data.get("speakers") or {}),
        )


# ── 语言对规则手册 ──────────────────────────────────────────

_ZH_TARGET_RULES = """# 翻译规则
1) 准确自然。忠实原意, 口语保持口语感; 不擅自增删信息; 避免直译腔。
2) 一句对一句。长句长译, 短句短译; 代词指代必须清晰 — 指代不明时
   回看上方全文与邻居上下文, 不要猜成"它"。
3) 术语一致。下方术语表的规定译法必须严格遵守, 全片统一;
   未收录的专名首次可写「中文(原文)」, 之后保持一致。
4) ASR 纠错。按下方纠错表先修正原文再翻译, 不解释、不标注。
5) 数字与单位。数字不加千分位逗号; 百分数、货币、尺寸保持原单位不换算;
   序号保持格式 (Section 3 -> 第3节)。
6) 标点排版。使用中文标点 (,。!?;:「」()); 省略号用「…」;
   必须使用标点; 禁用破折号, 改用逗号或括号分句。
7) 代码与命令。文件名、函数名、路径、URL、版本号一律保留原样。
8) 表述强度。粗口保留力度, 按语境选词, 不软化。
9) 语气词。极短语气词 (oh, um, あの) 自然处理, 可译可省。"""

_GENERIC_TARGET_RULES = """# Translation rules
1) Faithful and natural. Preserve register; no added or removed facts.
2) One sentence in, one sentence out. Keep pronoun reference clear —
   consult the full transcript and neighbour context above, never guess.
3) Terminology. Follow the glossary below strictly and consistently.
4) ASR corrections. Apply the correction list silently before translating.
5) Numbers and units. Keep original units and formats; no conversion.
6) Punctuation. Use natural target-language punctuation; always punctuate.
7) Code, file names, paths, URLs, versions: keep verbatim.
8) Strong language. Preserve intensity; do not soften.
9) Fillers. Handle short interjections naturally."""


def rulebook_for(source_lang: str, target_lang: str) -> str:
    """语言对规则手册 — zh 目标用中文详规, 其他目标用通用规则。"""
    if (target_lang or "").lower().startswith("zh"):
        return _ZH_TARGET_RULES
    return _GENERIC_TARGET_RULES


# ── 全量转录渲染 (预算制) ──────────────────────────────────

def render_transcript(events: list[dict], budget_tokens: int = TRANSCRIPT_TOKEN_BUDGET) -> str:
    """把 event 流渲染为带标签全文: [evt_001][SPEAKER_00] text。

    超预算时保留头尾各 40%, 中段替换为显式省略标记并记日志 —
    禁止静默截断 (上次 max_tokens=4000 事故的教训)。
    """
    lines = []
    for ev in events:
        spk = ev.get("speaker") or "?"
        lines.append(f"[{ev['id']}][{spk}] {ev.get('text', '').strip()}")
    full = "\n".join(lines)

    est_tokens = len(full) // 3
    if est_tokens <= budget_tokens:
        return full

    # 砍中段: 按行数取头 40% + 尾 40%
    head_n = int(len(lines) * 0.4)
    tail_n = int(len(lines) * 0.4)
    omitted = lines[head_n:len(lines) - tail_n]
    first_omitted = omitted[0].split("]")[0] + "]" if omitted else ""
    last_omitted = omitted[-1].split("]")[0] + "]" if omitted else ""
    logger.warning(
        "转录全文超预算 (估 %d token > %d), 中段 %d 段被省略 (%s..%s)",
        est_tokens, budget_tokens, len(omitted), first_omitted, last_omitted,
    )
    marker = (f"[... 省略 {len(omitted)} 段: {first_omitted}..{last_omitted}, "
              f"完整内容见时间轴 ...]")
    return "\n".join(lines[:head_n] + [marker] + lines[len(lines) - tail_n:])


# ── system prompt 渲染 ─────────────────────────────────────

def render_system_prompt(
    bible: TranslationBible,
    source_lang: str,
    target_lang: str,
    transcript: str = "",
    current_speaker: str | None = None,
) -> str:
    """渲染逐句翻译的 system prompt — 确定性, 相同输入逐字节相同。

    章节顺序固定 (前缀缓存优化: 共享内容在前, 每句变化的在最后):
      [1] 任务与输出格式   [2] 语言对规则手册
      [3] 全量转录         [4] bible (摘要/风格/术语/纠错/实体)
      [5] 说话人名册       [6] 当前句 speaker 档案
    """
    src_name = _lang_name(source_lang)
    dst_name = _lang_name(target_lang)
    parts: list[str] = []

    # [1] 任务 + 输出格式 (含 "json" 字样 — json_object 模式要求)
    parts.append(
        f"你是专业字幕翻译器, 将{src_name}字幕逐句翻译为{dst_name}。\n"
        "user 消息中 [待译] 标注的句子是唯一需要翻译的内容, "
        "其余行仅为上下文, 不要翻译。\n"
        "输出必须是严格的 json 对象: {\"dst\": \"<译文>\"}, "
        "除此之外不输出任何字符。"
    )

    # [2] 规则手册
    parts.append(rulebook_for(source_lang, target_lang))

    # [3] 全量转录
    if transcript.strip():
        parts.append(f"# 本片完整字幕 (供定位与长距离上下文)\n{transcript}")

    # [4] bible
    if bible.summary:
        parts.append(f"# 本片摘要\n{bible.summary}")
    if bible.style_guide:
        parts.append(f"# 本片风格指令\n{bible.style_guide}")
    if bible.hotwords:
        rows = [f"  {h['src']} -> {h['dst']}"
                for h in bible.hotwords[:MAX_HOTWORDS]
                if h.get("src") and h.get("dst")]
        if rows:
            parts.append("# 术语表 (必须严格遵守)\n" + "\n".join(rows))
    if bible.corrections:
        rows = [f"  {c['wrong']} -> {c['correct']}"
                for c in bible.corrections[:MAX_CORRECTIONS]
                if c.get("wrong") and c.get("correct")]
        if rows:
            parts.append("# ASR 纠错 (翻译前先按此修正原文)\n" + "\n".join(rows))
    if bible.entities:
        rows = []
        for e in bible.entities:
            line = f"  {e.get('src', '')} -> {e.get('dst', '')}"
            extras = [x for x in (e.get("role"), e.get("gender")) if x]
            if extras:
                line += f"  ({', '.join(extras)})"
            rows.append(line)
        parts.append("# 实体注册表\n" + "\n".join(rows))

    # [5] 说话人名册
    if bible.speakers:
        rows = []
        for spk_id in sorted(bible.speakers):
            prof = bible.speakers[spk_id]
            bits = [prof.get("role", ""), prof.get("register", ""),
                    prof.get("notes", "")]
            rows.append(f"  {spk_id}: {', '.join(b for b in bits if b)}")
        parts.append("# 说话人名册\n" + "\n".join(rows))

    # [6] 当前句 speaker 档案 — 唯一每句变化的部分, 必须在最后
    if current_speaker and current_speaker in bible.speakers:
        prof = bible.speakers[current_speaker]
        bits = [prof.get("role", ""), prof.get("register", ""),
                prof.get("notes", "")]
        parts.append(
            f"# 当前句说话人: {current_speaker}\n"
            f"其语域与风格: {', '.join(b for b in bits if b)}"
        )
    elif current_speaker:
        parts.append(f"# 当前句说话人: {current_speaker}")

    return "\n\n".join(parts)


_LANG_NAMES = {
    "en": "英文", "ja": "日文", "zh": "中文", "ko": "韩文", "yue": "粤语",
}


def _lang_name(code: str) -> str:
    return _LANG_NAMES.get((code or "").lower().split("-")[0], code or "未知")


# ── 预处理: bible 生成 (Step 2) ─────────────────────────────

# 预处理是全片一次性大上下文调用, 预算比逐句层宽。
PREPROCESS_TOKEN_BUDGET = 40000

PREPROCESS_PROMPT = """你为视频字幕翻译做预处理。通读完整转录文本, 输出严格的 json 对象。
转录原始语言: {src_language}
目标译文语言: {dst_language}

# 输出 json 格式 (严格遵守, 除此之外不输出任何字符)
{{
  "domain": "<视频领域, 如 gaming/tech_review/vlog/lecture/anime/interview>",
  "summary": "<用{dst_language}写的视频摘要, 3-5 句>",
  "style_guide": "<用{dst_language}写的本片翻译风格指令: 正式度/受众/语气策略, 2-4 句>",
  "hotwords": [{{"src": "<原文术语>", "dst": "<推荐译法>"}}],
  "corrections": [{{"wrong": "<转录中明显误识>", "correct": "<正确写法>"}}]
}}

# hotwords 要求
- 收录专有名词、人名、地名、品牌、技术术语、反复出现的核心概念。
- dst 必须给出译法: 有通行译法用通行译法 (如 LEGO -> 乐高);
  无通行译法拟一个自然的中文译名; 仅当该词在目标语言社区从不翻译时
  (如 GPU, API) dst 才与 src 相同。宁译勿留。
- src 必须逐字出现在转录文本中, 不得虚构。

# corrections 要求
- 仅列高置信的拼写或同音误识 (如 java script -> JavaScript)。
- wrong 必须逐字出现在转录文本中。不做模糊的语义改写。

# 转录文本
{full_text}
"""


def parse_bible_response(
    data: dict,
    transcript_text: str,
    engine: str = "",
) -> TranslationBible:
    """把预处理 LLM 输出校验为 TranslationBible — 证据校验门。

    硬规则 (幻觉过滤器, 确定性机械校验替代人眼):
      hotword.src / correction.wrong 必须逐字出现在转录原文 (大小写不敏感),
      否则丢弃并记日志。count 由本函数按原文实际出现次数重算, 不信 LLM。
    """
    bible = TranslationBible(engine=engine)
    if not isinstance(data, dict):
        logger.warning("预处理输出非 dict, 返回空 bible: %r", str(data)[:200])
        return bible

    bible.domain = str(data.get("domain", "") or "").strip()
    bible.summary = str(data.get("summary", "") or "").strip()
    bible.style_guide = str(data.get("style_guide", "") or "").strip()

    folded = transcript_text.casefold()

    for h in data.get("hotwords") or []:
        if not isinstance(h, dict):
            continue
        src = str(h.get("src", "") or "").strip()
        dst = str(h.get("dst", "") or "").strip()
        if not src or not dst:
            continue
        if src.casefold() not in folded:
            logger.warning("hotword 无原文证据, 丢弃: %r -> %r", src, dst)
            continue
        count = folded.count(src.casefold())
        bible.hotwords.append({"src": src, "dst": dst, "count": count})

    for c in data.get("corrections") or []:
        if not isinstance(c, dict):
            continue
        wrong = str(c.get("wrong", "") or "").strip()
        correct = str(c.get("correct", "") or "").strip()
        if not wrong or not correct:
            continue
        if wrong.casefold() not in folded:
            logger.warning("correction 无原文证据, 丢弃: %r -> %r", wrong, correct)
            continue
        bible.corrections.append({"wrong": wrong, "correct": correct})

    logger.info(
        "bible 解析完成: domain=%s, hotwords=%d, corrections=%d",
        bible.domain or "?", len(bible.hotwords), len(bible.corrections),
    )
    return bible


def load_manual_glossary(cfg: dict | None = None, project_root: str = "") -> dict[str, str]:
    """加载 L0 人工领域词典 (config/terms/*.json 的 {terms: {src: dst}})。

    从 translate.yaml 的 terms_dict 节读 dict_dir (默认 config/terms/)
    与 default_dict 列表。移植自 SRT/glossary_injector (旧路径退役后
    此处为唯一事实源); 与旧注入逻辑的差异: 保留单词术语
    (bible 的术语锚点需要 GPU 这类单词), 仅过滤 § 分隔符。
    """
    if cfg is None:
        from pipeline.translation_llm import load_translate_config
        cfg = load_translate_config()
    terms_cfg = cfg.get("terms_dict", {}) if isinstance(cfg, dict) else {}
    if not terms_cfg.get("enabled", True):
        return {}
    names = terms_cfg.get("default_dict", []) or []
    if isinstance(names, str):
        names = [names]
    dict_dir = terms_cfg.get("dict_dir", "config/terms/")
    if project_root and not os.path.isabs(dict_dir):
        dict_dir = os.path.join(project_root, dict_dir)

    merged: dict[str, str] = {}
    for name in names:
        path = os.path.join(dict_dir, name)
        if not os.path.isfile(path):
            logger.warning("人工词典不存在, 跳过: %s", path)
            continue
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        for k, v in (data.get("terms", {}) or {}).items():
            k, v = str(k).strip(), str(v).strip()
            if k and v and "§" not in k and "§" not in v:
                merged[k] = v     # 后加载的词典覆盖同名术语
    return merged


def merge_manual_glossary(bible: TranslationBible, manual_terms: dict[str, str]) -> TranslationBible:
    """L0 人工词典合并 — 人工永远赢: 同 src 的自动热词丢弃并记日志。

    人工词条置于 hotwords 最前 (渲染时优先生效), origin="manual" 溯源。
    """
    if not manual_terms:
        return bible
    manual_folded = {k.casefold(): (k, v) for k, v in manual_terms.items()}
    kept = []
    for h in bible.hotwords:
        if h["src"].casefold() in manual_folded:
            mk, mv = manual_folded[h["src"].casefold()]
            logger.info("自动热词与人工词典冲突, 人工赢: %r (auto=%r, manual=%r)",
                        h["src"], h["dst"], mv)
            continue
        kept.append(h)
    manual_entries = [
        {"src": k, "dst": v, "count": 0, "origin": "manual"}
        for k, v in manual_terms.items()
    ]
    bible.hotwords = manual_entries + kept
    return bible


# ── 说话人画像 (Step 3) ─────────────────────────────────────

# 每个 speaker 喂给画像模型的台词样本上限 (控制 prompt 体量)
PROFILE_SAMPLE_LINES = 25

SPEAKER_PROFILE_PROMPT = """你是字幕翻译项目的说话人分析师。下面是视频按说话人分组的台词样本,
以及全片摘要。请为每个说话人推断翻译所需的人物档案, 输出严格的 json 对象。

视频领域: {domain}
全片摘要: {summary}

# 输出 json 格式 (严格遵守, 除此之外不输出任何字符)
{{
  "speakers": {{
    "<speaker_id>": {{
      "role": "<角色推断, 如 主持人/嘉宾/旁白/受访者>",
      "register": "<语域, 如 随意口语/正式讲解/激动解说>",
      "notes": "<翻译要点: 自称/口癖/性别线索/与其他说话人的关系, 1-2 句>"
    }}
  }}
}}

# 要求
- 只输出输入中出现过的 speaker_id, 不得虚构。
- 所有字段用{dst_language}书写。
- 推断基于台词证据 (自称词/敬语/话题/语气), 不确定就在 notes 里明说。

# 分说话人台词样本
{speaker_blocks}
"""


def build_speaker_blocks(items: list[dict], max_lines: int = PROFILE_SAMPLE_LINES) -> str:
    """按 speaker 聚合台词样本 (时间序), 供画像 prompt 使用。

    与全量转录是两个视角: 转录保对话交错 (理解内容),
    本函数按人聚合 (推断语域/自称/口癖只需要本人的话)。
    """
    by_speaker: dict[str, list[str]] = {}
    order: list[str] = []
    for it in items:
        spk = it.get("speaker") or "UNKNOWN"
        if spk not in by_speaker:
            by_speaker[spk] = []
            order.append(spk)
        by_speaker[spk].append(it.get("text", "").strip())

    blocks = []
    for spk in order:
        lines = by_speaker[spk][:max_lines]
        body = "\n".join(f"  {t}" for t in lines if t)
        blocks.append(f"[{spk}] ({len(by_speaker[spk])} 句, 样本 {len(lines)} 句)\n{body}")
    return "\n\n".join(blocks)


def parse_speaker_profiles(data: dict, valid_speakers: set[str]) -> dict[str, dict]:
    """校验画像输出 — 画像门: speaker_id 必须真实存在, 幻觉 id 丢弃+日志。"""
    out: dict[str, dict] = {}
    speakers = data.get("speakers") if isinstance(data, dict) else None
    if not isinstance(speakers, dict):
        logger.warning("画像输出缺 speakers 对象, 跳过: %r", str(data)[:200])
        return out
    for spk_id, prof in speakers.items():
        if spk_id not in valid_speakers:
            logger.warning("画像含未知 speaker %r, 丢弃", spk_id)
            continue
        if not isinstance(prof, dict):
            continue
        out[spk_id] = {
            "role": str(prof.get("role", "") or "").strip(),
            "register": str(prof.get("register", "") or "").strip(),
            "notes": str(prof.get("notes", "") or "").strip(),
        }
    logger.info("说话人画像完成: %d/%d 人", len(out), len(valid_speakers))
    return out
