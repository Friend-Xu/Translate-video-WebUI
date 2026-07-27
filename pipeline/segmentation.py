"""
segmentation — 标点感知词级分段引擎 (数据结构重设计 Phase 4)

单一事实源: 统一自 SRT/Json_Convert_Srt_EN|JP 的 EnglishProcessor /
JapaneseProcessor 的切分决策逻辑, 供新 IR 路径 (core/passes/segmentation_pass.py)
使用。旧 SRT 路径后续委托本模块以消除双实现 (本期不动旧路径)。

算法 — 候选切点 + 约束切分 (与处理器一致):
  在每个词后计算候选切点评分:
      句末标点 (。！？ .?!)  >  强停顿  >  从句标点 (，、； ,;:)  >  弱停顿/连词/介词
  在 [min, target, max] 单元/时长窗内选最优候选切点切分;
  到 max 仍无候选才硬切 (交由调用方决定是否置 review_flag)。

原则:
  词级计时 — 段 start/end 取首末词真实时间戳, 不用字符比例虚构 (禁止兜底)。
  说话人边界是硬切点, 永不跨说话人 (调用方按 speaker-run 喂入)。
  小数/缩写防护 — 拉丁 '.' 仅在非小数非缩写时才算句末。

本模块零 core 依赖 (单向依赖: core → pipeline), 输入输出均为纯 dict。
"""
from __future__ import annotations
from dataclasses import dataclass


# ── 语言配置 ─────────────────────────────────────────────────

@dataclass(frozen=True)
class SegmentationConfig:
    """分段参数 — 按语言区分书写系统与阈值。

    max_units / target_units / min_units 的"单元":
      latin → 词数;  cjk → 字符数 (中文/日文无空格分词)。
    """
    script: str                              # "latin" | "cjk"
    use_space: bool                          # join_words 是否加空格
    sentence_enders: frozenset
    clause_breaks: frozenset
    conjunctions: tuple = ()
    prepositions: tuple = ()
    abbreviations: frozenset = frozenset()
    max_units: int = 50
    target_units: int = 25
    min_units: int = 3
    max_duration: float = 15.0
    pause_strong: float = 0.5
    pause_weak: float = 0.3


EN_CONFIG = SegmentationConfig(
    script="latin", use_space=True,
    sentence_enders=frozenset(".?!"),
    clause_breaks=frozenset(",;:"),
    conjunctions=("and", "but", "or", "so", "yet", "for", "nor"),
    prepositions=("in", "on", "at", "by", "with", "to", "from"),
    abbreviations=frozenset({
        "mr", "mrs", "ms", "dr", "st", "vs", "etc", "e.g", "i.e",
        "u.s", "u.k", "u.s.a", "no", "fig", "approx",
    }),
    max_units=50, target_units=25, min_units=3,
)

JA_CONFIG = SegmentationConfig(
    script="cjk", use_space=False,
    sentence_enders=frozenset("。？！…」』?!"),
    clause_breaks=frozenset("、，；"),
    max_units=35, target_units=18, min_units=4,
)

_CONFIG_BY_LANG = {
    "en": EN_CONFIG,
    "ja": JA_CONFIG,
    # 中文作源语言暂未支持 (用户确认: 源恒为 en/ja, 中文是目标语言继承分段)。
}


def config_for(lang: str) -> SegmentationConfig:
    """按语言代码取分段配置; 未显式支持的非 CJK 语言回落 latin。"""
    base = (lang or "").lower().split("-")[0]
    if base in _CONFIG_BY_LANG:
        return _CONFIG_BY_LANG[base]
    if base in ("zh", "ko", "yue", "cn"):
        # CJK 无空格, 用 JA 的字符单元配置 (标点集兼容)。
        return JA_CONFIG
    return EN_CONFIG


# ── 输出 ─────────────────────────────────────────────────────

@dataclass
class Segment:
    """一个分段结果 — 句级单元, 携带词切片。"""
    words: list[dict]
    speaker: str | None
    start: float
    end: float
    text: str
    flag: str | None = None          # 例如 "no_word_timestamps" / "hard_cut"


# ── 内部: 单元数 / 切点评分 ──────────────────────────────────

def _units(words: list[dict], cfg: SegmentationConfig) -> int:
    if cfg.script == "latin":
        return len(words)
    return sum(len(w.get("word", "")) for w in words)


def _is_sentence_end(word_text: str, next_text: str, cfg: SegmentationConfig) -> bool:
    """拉丁 '.' 需排除小数 (3. + 14 / 3 + .14) 与缩写; CJK 句末标点无歧义。"""
    if not word_text or word_text[-1] not in cfg.sentence_enders:
        return False
    if cfg.script == "latin" and word_text[-1] == ".":
        if next_text and (next_text[0].isdigit() or next_text[0] == "."):
            return False
        base = word_text.rstrip(".?!").lower()
        if base in cfg.abbreviations:
            return False
    return True


def _overflow_score(word: dict, nxt: dict, cfg: SegmentationConfig) -> int:
    """溢出候选切点评分 (仅无句末标点时的长 run-on 切分用)。

    句末标点不走这里 — 它在 segment_words 中触发立即提交。
    词缺时间戳时间隔按 0 计 (不产生停顿切点)。
    """
    wt = word.get("word", "")
    nt = nxt.get("word", "")
    ws_end = word.get("end")
    nx_start = nxt.get("start")
    gap = (nx_start - ws_end) if (ws_end is not None and nx_start is not None) else 0.0

    if gap >= cfg.pause_strong:
        return 3
    if wt and wt[-1] in cfg.clause_breaks:
        return 2
    if gap >= cfg.pause_weak:
        return 1
    if cfg.script == "latin" and nt.lower().strip(",;:") in (
        cfg.conjunctions + cfg.prepositions
    ):
        return 1
    return 0


def join_words(words: list[dict], cfg: SegmentationConfig) -> str:
    """从词切片派生 text — CJK 无空格, 拉丁单空格。"""
    sep = " " if cfg.use_space else ""
    return sep.join(w.get("word", "") for w in words).strip()


# ── 核心: 词流切分 ───────────────────────────────────────────

def segment_words(words: list[dict], cfg: SegmentationConfig) -> tuple[list[list[dict]], bool]:
    """把同一 speaker 的词流切成句级词组。

    规则 (与处理器一致):
      句末标点 → 立即提交 (够 min_units), 与长度无关。
      无句末的长 run-on 到 max_units/max_duration → 在最优溢出候选
        (停顿>从句>连词/介词) 处切; 无候选才硬切。

    Returns: (词组列表, 是否发生过 max 硬切)。硬切供调用方置 review_flag。
    """
    n = len(words)
    if n == 0:
        return [], False

    groups: list[list[dict]] = []
    hard_cut = False
    cur_start = 0
    best_cut = -1        # 最优溢出候选 (绝对索引, 在该词后切)
    best_score = 0

    for i in range(n):
        wt = words[i].get("word", "")
        nt = words[i + 1].get("word", "") if i + 1 < n else ""
        u = _units(words[cur_start:i + 1], cfg)

        # 句末标点 → 立即提交
        if u >= cfg.min_units and _is_sentence_end(wt, nt, cfg):
            groups.append(words[cur_start:i + 1])
            cur_start = i + 1
            best_cut, best_score = -1, 0
            continue

        # 记录最优溢出候选 (句末以外的切点)
        if i < n - 1:
            score = _overflow_score(words[i], words[i + 1], cfg)
            if score > best_score:
                best_score = score
                best_cut = i

        dur = (words[i].get("end") or 0.0) - (words[cur_start].get("start") or 0.0)
        if u >= cfg.max_units or dur >= cfg.max_duration:
            if cur_start <= best_cut < i:
                groups.append(words[cur_start:best_cut + 1])
                cur_start = best_cut + 1
            else:
                groups.append(words[cur_start:i + 1])
                cur_start = i + 1
                hard_cut = True
            best_cut, best_score = -1, 0

    if cur_start < n:
        groups.append(words[cur_start:])
    return [g for g in groups if g], hard_cut


# ── 入口: event 流 → 句级 Segment ───────────────────────────

def segment_event_stream(events: list[dict], lang: str) -> list[Segment]:
    """把按时间排序的 event 字典流重分段为句级 Segment。

    Args:
        events: [{id, start, end, words: [{word,start,end}], speaker, text}], 按 start 排序。
                无 words 的 event 原样保留并置 flag="no_word_timestamps" (禁止兜底:
                不用字符比例估算切点, 进人工审核)。
        lang: 源语言代码。

    说话人变化是硬边界 — 跨 speaker 的词永不进同一段。
    同 speaker 的连续 event 词流合并后再切分 (允许跨原 event 拼整句 / 切长句)。
    """
    cfg = config_for(lang)
    out: list[Segment] = []

    run_words: list[dict] = []
    run_speaker: str | None = None

    def flush_run() -> None:
        nonlocal run_words, run_speaker
        if not run_words:
            return
        groups, hard = segment_words(run_words, cfg)
        for gi, g in enumerate(groups):
            start = g[0].get("start")
            end = g[-1].get("end")
            if start is None or end is None or end <= start:
                # 词时间戳不可靠, 不虚构: 透出并置 flag 进人工。
                out.append(Segment(g, run_speaker, start or 0.0, end or 0.0,
                                   join_words(g, cfg), flag="unreliable_word_timestamps"))
                continue
            flag = "hard_cut" if (hard and gi == len(groups) - 1) else None
            out.append(Segment(g, run_speaker, start, end, join_words(g, cfg), flag=flag))
        run_words = []

    for ev in events:
        words = [w for w in (ev.get("words") or []) if isinstance(w, dict)]
        speaker = ev.get("speaker")
        if not words:
            flush_run()
            out.append(Segment([], speaker, ev.get("start", 0.0), ev.get("end", 0.0),
                               ev.get("text", ""), flag="no_word_timestamps"))
            continue
        if run_words and speaker != run_speaker:
            flush_run()
        run_speaker = speaker
        run_words.extend(words)
    flush_run()

    out.sort(key=lambda s: s.start)
    return out
