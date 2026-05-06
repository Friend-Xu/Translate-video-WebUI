"""
External Subtitle Optimizer — 外挂字幕可读性时间优化

对现有 SRT 字幕做保守调整：
- 过短字幕 → 向后拉伸（避免重叠下一条）
- 间隙足够近 → 合并相邻短字幕
- 根据文本长度和阅读速度计算所需显示时间
- 支持单语和双语输出

保守调整 = 只修短字幕，不动已合理的条目。
"""

from __future__ import annotations

import os
import re
import tempfile
from typing import Optional

# ── 书写系统判定 ────────────────────────────────────────────

_CJK_RANGES = [
    (0x4E00, 0x9FFF), (0x3400, 0x4DBF),
    (0x3040, 0x30FF), (0x31F0, 0x31FF),
    (0xAC00, 0xD7AF), (0x1100, 0x11FF),
]
_LATIN_RANGES = [
    (0x0020, 0x024F), (0x1E00, 0x1EFF),
    (0x0400, 0x04FF),
]
_ARABIC_RANGES = [
    (0x0600, 0x06FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF),
]

# 默认阅读参数
SCRIPT_DEFAULTS = {
    "cjk":    {"min_duration": 1.5, "reading_speed": 4.0},   # 字/秒
    "latin":  {"min_duration": 1.2, "reading_speed": 12.0},  # 字符/秒
    "arabic": {"min_duration": 1.3, "reading_speed": 10.0},  # 字符/秒
}

# 语言 → 脚本快速映射
LANG_SCRIPT_MAP = {
    "ja": "cjk", "zh": "cjk", "ko": "cjk",
    "en": "latin", "fr": "latin", "de": "latin", "es": "latin",
    "ru": "latin", "pt": "latin", "it": "latin",
}


def _in_ranges(ch: str, ranges: list) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in ranges)


def detect_script(text: str) -> str:
    cjk_n = sum(1 for ch in text if _in_ranges(ch, _CJK_RANGES))
    latin_n = sum(1 for ch in text if _in_ranges(ch, _LATIN_RANGES))
    arabic_n = sum(1 for ch in text if _in_ranges(ch, _ARABIC_RANGES))
    total = max(cjk_n + latin_n + arabic_n, 1)
    if cjk_n / total > 0.3:
        return "cjk"
    if arabic_n / total > 0.3:
        return "arabic"
    if latin_n / total > 0:
        return "latin"
    return "cjk"


# ── SRT 解析/输出 ────────────────────────────────────────────

_SRT_TIME_RE = re.compile(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})")


def _parse_time(s: str) -> int:
    """HH:MM:SS,mmm → 毫秒"""
    m = _SRT_TIME_RE.match(s.strip())
    if not m:
        raise ValueError(f"无效 SRT 时间戳: {s}")
    h, mi, sec, ms = map(int, m.groups())
    return (h * 3600 + mi * 60 + sec) * 1000 + ms


def _format_time(ms: int) -> str:
    """毫秒 → HH:MM:SS,mmm"""
    ms = max(ms, 0)
    h = ms // 3600000
    ms %= 3600000
    m = ms // 60000
    ms %= 60000
    s = ms // 1000
    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(path: str) -> list[dict]:
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return entries

    blocks = content.split("\n\n")
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        try:
            int(lines[0].strip())
        except ValueError:
            continue
        timing = lines[1].strip()
        parts = timing.split("-->")
        if len(parts) != 2:
            continue
        start_ms = _parse_time(parts[0])
        end_ms = _parse_time(parts[1])
        text = "\n".join(lines[2:]).strip()
        entries.append({"start_ms": start_ms, "end_ms": end_ms, "text": text})
    return entries


def write_srt(entries: list[dict], path: str) -> None:
    lines = []
    for i, entry in enumerate(entries, 1):
        lines.append(str(i))
        lines.append(f"{_format_time(entry['start_ms'])} --> {_format_time(entry['end_ms'])}")
        lines.append(entry["text"])
        lines.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ── 文本长度计算 ────────────────────────────────────────────

def _text_len(text: str, script: str) -> int:
    """有效文本长度：拉丁保留空格，CJK/Arabic 去除空白。"""
    if script == "latin":
        return len(text.strip())
    return len(re.sub(r"\s+", "", text))


# ── 核心优化 ────────────────────────────────────────────────

def optimize_srt(
    srt_path: str,
    output_path: str,
    lang: str = "zh",
    min_duration: float | None = None,
    reading_speed: float | None = None,
    max_merge_gap: float = 0.3,
    inter_gap: float = 0.05,
    max_duration: float = 10.0,
) -> dict:
    """保守调整 SRT 字幕时间轴。

    对每条字幕：若当前时长 < max(最小显示, 文本长度/阅读速度)，则优先
    向后拉伸；拉伸空间不足时尝试合并下一条；都不行则尽量延伸。

    Args:
        srt_path: 输入 SRT 文件路径
        output_path: 输出 SRT 文件路径
        lang: 语言代码 (ja/zh/ko/en/...)
        min_duration: 覆盖最小显示时长（秒）
        reading_speed: 覆盖阅读速度（字符/秒）
        max_merge_gap: 合并判定间隙（秒）
        inter_gap: 字幕间呼吸间隔（秒）
        max_duration: 单条最大时长上限（秒）

    Returns:
        {"total": N, "adjusted": N, "merged": N}
    """
    entries = parse_srt(srt_path)
    if not entries:
        return {"total": 0, "adjusted": 0, "merged": 0}

    script = LANG_SCRIPT_MAP.get(
        lang,
        detect_script(entries[0]["text"]),
    )
    defaults = SCRIPT_DEFAULTS[script]
    min_dur_ms = int((min_duration or defaults["min_duration"]) * 1000)
    speed = reading_speed or defaults["reading_speed"]
    merge_gap_ms = int(max_merge_gap * 1000)
    gap_ms = int(inter_gap * 1000)
    max_dur_ms = int(max_duration * 1000)

    stats = {"total": len(entries), "adjusted": 0, "merged": 0}

    optimized: list[dict] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        start, end, text = entry["start_ms"], entry["end_ms"], entry["text"]

        tlen = _text_len(text, script)
        required = max(min_dur_ms, int(tlen / speed * 1000)) if tlen > 0 else min_dur_ms
        current_dur = end - start

        if current_dur >= required:
            optimized.append({"start_ms": start, "end_ms": end, "text": text})
            i += 1
            continue

        # 时长不足
        next_entry = entries[i + 1] if i + 1 < len(entries) else None

        if next_entry is None:
            new_end = min(start + required, start + max_dur_ms)
            optimized.append({"start_ms": start, "end_ms": new_end, "text": text})
            stats["adjusted"] += 1
            i += 1
            continue

        next_start = next_entry["start_ms"]
        can_extend_to = next_start - gap_ms

        if can_extend_to - start >= required:
            optimized.append({"start_ms": start, "end_ms": start + required, "text": text})
            stats["adjusted"] += 1
            i += 1
        elif (next_start - end) <= merge_gap_ms:
            # 尝试合并
            merged_text = text + "\n" + next_entry["text"]
            merged_tlen = _text_len(merged_text, script)

            if merged_tlen <= tlen * 3 + 50:
                merged_end = next_entry["end_ms"]
                merged_required = max(min_dur_ms, int(merged_tlen / speed * 1000))

                after_next = entries[i + 2] if i + 2 < len(entries) else None
                if merged_end - start < merged_required:
                    if after_next:
                        merged_end = min(start + merged_required, after_next["start_ms"] - gap_ms)
                    else:
                        merged_end = min(start + merged_required, start + max_dur_ms)

                optimized.append({"start_ms": start, "end_ms": merged_end, "text": merged_text})
                stats["adjusted"] += 1
                stats["merged"] += 1
                i += 2
            else:
                optimized.append({"start_ms": start, "end_ms": can_extend_to, "text": text})
                stats["adjusted"] += 1
                i += 1
        else:
            new_end = max(can_extend_to, start + min_dur_ms)
            optimized.append({"start_ms": start, "end_ms": new_end, "text": text})
            stats["adjusted"] += 1
            i += 1

    # 后置检查：修复重叠
    for j in range(len(optimized) - 1):
        if optimized[j]["end_ms"] > optimized[j + 1]["start_ms"]:
            optimized[j]["end_ms"] = optimized[j + 1]["start_ms"] - gap_ms
            if optimized[j]["end_ms"] < optimized[j]["start_ms"]:
                optimized[j]["end_ms"] = optimized[j]["start_ms"] + min_dur_ms

    write_srt(optimized, output_path)
    return stats


# ── 双语模式 ────────────────────────────────────────────────

def optimize_bilingual(
    target_srt: str,
    source_srt: str,
    output_path: str,
    lang: str = "zh",
    **kwargs,
) -> dict:
    """优化双语字幕：以译文时间轴为主，合并原文文本后统一优化。

    Args:
        target_srt: 译文 SRT 路径
        source_srt: 原文 SRT 路径
        output_path: 输出路径
        lang: 语言代码
        **kwargs: 透传给 optimize_srt
    """
    target_entries = parse_srt(target_srt)
    source_entries = parse_srt(source_srt)

    if len(target_entries) != len(source_entries):
        raise ValueError(
            f"译文和原文条目数不一致: {len(target_entries)} vs {len(source_entries)}"
        )

    merged_entries = []
    for t, s in zip(target_entries, source_entries):
        merged_entries.append({
            "start_ms": t["start_ms"],
            "end_ms": t["end_ms"],
            "text": s["text"] + "\n" + t["text"],
        })

    tmp = os.path.join(tempfile.gettempdir(), f"_ext_sub_{os.getpid()}.srt")
    write_srt(merged_entries, tmp)

    try:
        stats = optimize_srt(tmp, output_path, lang=lang, **kwargs)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    return stats


# ── 配置加载 ────────────────────────────────────────────────

def load_ext_subtitle_config(config_path: str | None = None) -> dict:
    """加载外挂字幕配置，返回参数字典。"""
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "external_subtitle.yaml",
        )

    if not os.path.exists(config_path):
        return {"mode": "bilingual"}

    import yaml
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return data.get("external_subtitle", {"mode": "bilingual"})
