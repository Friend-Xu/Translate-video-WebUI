"""
SubtitleOptimizer — 字幕文本拆分与时间段重分配

对过长字幕进行双语同步拆分：
- 检测目标语言的书写系统，找自然断句点
- 按文本长度比例切分源语言
- 按比例重分配段内时间轴
- 纯内存数据转换，不生成文件
"""

from __future__ import annotations

from typing import Optional, Tuple

# Unicode 区块：书写系统判定
_CJK_RANGES = [
    (0x4E00, 0x9FFF), (0x3400, 0x4DBF),  # CJK Unified
    (0x3040, 0x30FF), (0x31F0, 0x31FF),   # Hiragana, Katakana
    (0xAC00, 0xD7AF), (0x1100, 0x11FF),   # Hangul
]
_LATIN_RANGES = [
    (0x0020, 0x024F), (0x1E00, 0x1EFF),   # Latin
    (0x0400, 0x04FF),                       # Cyrillic
]
_ARABIC_RANGES = [
    (0x0600, 0x06FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF),
]

# 断句点：按书写系统分层
_CJK_STOPS = ["。", "！", "？", "…",
              "；",
              "，", "、",
              ]
_LATIN_STOPS = [".", "!", "?", ";", ","]
_ARABIC_STOPS = [".", "!", "?", "؛", "،"]


def _in_ranges(ch: str, ranges: list) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in ranges)


def _detect_script(text: str) -> str:
    """检测文本书写系统: cjk | latin | arabic | mixed"""
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


def _find_breakpoint(text: str, target_ratio: float,
                     stops: list[str], script: str) -> int:
    """在 text 中 target_ratio 附近找最佳断句点。

    Args:
        text: 要断句的文本
        target_ratio: 目标比例 (0.0~1.0)
        stops: 断句点列表，按优先级排序
        script: 书写系统

    Returns:
        切分位置（前半段的字符数）
    """
    target_pos = int(len(text) * target_ratio)
    search_start = max(1, int(len(text) * 0.25))
    search_end = min(len(text) - 1, int(len(text) * 0.75))

    for stop in stops:
        pos = text.find(stop, max(search_start, target_pos - 10), search_end + 1)
        if pos != -1:
            return pos + 1

    # 无标点降级
    if script in ("latin", "arabic"):
        space_pos = text.rfind(" ", 0, target_pos + 30)
        if search_start <= space_pos < search_end:
            return space_pos + 1
        space_pos = text.find(" ", max(search_start, target_pos - 5), search_end + 1)
        if space_pos != -1:
            return space_pos + 1
    elif script == "cjk":
        try:
            import jieba
            words = list(jieba.cut(text))
            cumulative = 0
            for i, w in enumerate(words):
                cumulative += len(w)
                if cumulative >= target_pos and i > 0:
                    slice_pos = sum(len(words[j]) for j in range(i))
                    if search_start <= slice_pos <= search_end:
                        return slice_pos
        except ImportError:
            pass

    return max(1, target_pos)


def _split_text(text: str, script: str) -> list[str]:
    """将超长文本拆为两段。"""
    stops = {
        "cjk": _CJK_STOPS, "latin": _LATIN_STOPS,
        "arabic": _ARABIC_STOPS,
    }.get(script, _CJK_STOPS)
    pos = _find_breakpoint(text, 0.5, stops, script)
    a = text[:pos].strip()
    b = text[pos:].strip()
    if not a:
        a = text[:max(1, len(text)//2)].strip()
    if not b:
        b = text[max(1, len(text)//2):].strip()
    return [a, b]


def _cut_source(source_text: str, target_splits: list[str],
                source_script: str) -> list[str]:
    """按 target 拆分比例同步切分 source。"""
    stops = {
        "cjk": _CJK_STOPS, "latin": _LATIN_STOPS,
        "arabic": _ARABIC_STOPS,
    }.get(source_script, _CJK_STOPS)

    total_len = sum(len(s) for s in target_splits)
    if total_len == 0:
        mid = max(1, len(source_text) // 2)
        return [source_text[:mid], source_text[mid:]]

    results = []
    cumulative_ratio = 0.0
    working = source_text
    for part in target_splits[:-1]:
        cumulative_ratio += len(part) / total_len
        pos = _find_breakpoint(working, cumulative_ratio, stops, source_script)
        if pos <= 0:
            pos = max(1, int(len(working) * cumulative_ratio))
        if pos >= len(working):
            pos = len(working) - 1
        pos = max(1, pos)
        results.append(working[:pos].strip())
        working = working[pos:].strip()
    results.append(working)
    return results


def optimize(
    subs_target: list[tuple[int, int, str]],
    subs_source: list[tuple[int, int, str]],
    capturer,  # CaptionRenderer
    video_width: int,
) -> list[list[tuple[int, int, str, str]]]:
    """优化字幕：检测并拆分过长条目。

    Args:
        subs_target: 目标语言字幕 [(start_ms, end_ms, text), ...]
        subs_source: 源语言字幕 [(start_ms, end_ms, text), ...]
        capturer: CaptionRenderer 实例
        video_width: 视频宽度

    Returns:
        caption_groups[i] = [(rel_start_ms, rel_end_ms, target, source), ...]
    """
    max_width = int(video_width * capturer.caption_width_ratio)
    min_fs = capturer.min_font_size
    max_lines = capturer.max_lines
    max_depth = 3

    # 固定模式下用实际字号检测行数，否则用最小字号（adaptive 模式会自动缩小）
    if capturer.font_size_mode == "fixed":
        desired_fs = capturer._get_font_size(video_width)
        measure_fs = desired_fs if desired_fs > 0 else min_fs
    else:
        measure_fs = min_fs

    result: list[list[tuple[int, int, str, str]]] = []

    for i, (start, end, target_text) in enumerate(subs_target):
        source_text = subs_source[i][2] if i < len(subs_source) else ""
        combined = f"{target_text}\n{source_text}" if source_text else target_text
        duration_ms = end - start
        if duration_ms <= 0:
            result.append([(0, duration_ms, target_text, source_text)])
            continue

        lines_at_measure = capturer._measure_lines(combined, measure_fs, max_width)

        if lines_at_measure <= max_lines:
            result.append([(0, duration_ms, target_text, source_text)])
        else:
            target_script = _detect_script(target_text)
            source_script = _detect_script(source_text) if source_text else target_script
            segments = _split_recursive(
                target_text, source_text, target_script, source_script,
                capturer, measure_fs, max_width, max_lines, max_depth,
            )
            total_chars = sum(len(t) for t, _ in segments)
            if total_chars == 0:
                total_chars = 1
            group = []
            elapsed = 0
            for t_text, s_text in segments:
                ratio = len(t_text) / total_chars
                segment_dur = max(200, int(duration_ms * ratio))
                group.append((elapsed, elapsed + segment_dur, t_text, s_text))
                elapsed += segment_dur
            if group and elapsed < duration_ms:
                last = group[-1]
                group[-1] = (last[0], duration_ms, last[2], last[3])
            result.append(group)

    return result


def _split_recursive(
    target: str, source: str,
    target_script: str, source_script: str,
    capturer, measure_fs: int, max_width: int, max_lines: int,
    depth: int,
    _history: Optional[set] = None,
) -> list[tuple[str, str]]:
    if _history is None:
        _history = set()

    if depth <= 0:
        return [(target, source)]

    combined = f"{target}\n{source}" if source else target
    if capturer._measure_lines(combined, measure_fs, max_width) <= max_lines:
        return [(target, source)]

    # 防止无限递归
    if target in _history:
        return [(target, source)]
    _history.add(target)

    target_parts = _split_text(target, target_script)
    source_parts = _cut_source(source, target_parts, source_script) if source else [""] * len(target_parts)

    result = []
    for tp, sp in zip(target_parts, source_parts):
        result.extend(_split_recursive(
            tp, sp, target_script, source_script,
            capturer, measure_fs, max_width, max_lines, depth - 1, _history,
        ))
    return result
