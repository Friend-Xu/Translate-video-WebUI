"""
测试外挂字幕优化模块。

验证:
1. SRT 解析/输出往返
2. 过短字幕被拉伸到最小可读时长
3. 相邻短字幕被合并
4. 合理字幕原样通过
5. 双语合并
6. 边界情况
"""

import os
import tempfile
import pytest
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from pipeline.external_subtitle_optimizer import (
    parse_srt,
    write_srt,
    optimize_srt,
    optimize_bilingual,
    detect_script,
    _format_time,
    _parse_time,
)


def _make_srt(entries: list[tuple[int, int, str]]) -> str:
    """[(start_ms, end_ms, text), ...] → SRT 字符串"""
    lines = []
    for i, (start, end, text) in enumerate(entries, 1):
        lines.append(str(i))
        lines.append(f"{_format_time(start)} --> {_format_time(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def _write_temp_srt(entries: list[tuple[int, int, str]]) -> str:
    """写入临时 SRT 文件，返回路径。"""
    fd, path = tempfile.mkstemp(suffix=".srt", prefix="test_ext_sub_")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as f:
        f.write(_make_srt(entries))
    return path


# ── SRT 解析/输出 ────────────────────────────────────────────

class TestSrtParse:
    def test_basic_parse(self):
        path = _write_temp_srt([
            (0, 2000, "你好"),
            (2500, 5000, "世界"),
        ])
        entries = parse_srt(path)
        assert len(entries) == 2
        assert entries[0]["start_ms"] == 0
        assert entries[0]["end_ms"] == 2000
        assert entries[0]["text"] == "你好"
        assert entries[1]["text"] == "世界"
        os.remove(path)

    def test_multiline_text(self):
        path = _write_temp_srt([
            (0, 3000, "第一行\n第二行"),
        ])
        entries = parse_srt(path)
        assert len(entries) == 1
        assert entries[0]["text"] == "第一行\n第二行"
        os.remove(path)

    def test_empty_file(self):
        path = _write_temp_srt([])
        entries = parse_srt(path)
        assert entries == []
        os.remove(path)

    def test_roundtrip(self):
        data = [
            (0, 1500, "Hello"),
            (1800, 4000, "World"),
        ]
        fd, out = tempfile.mkstemp(suffix=".srt")
        os.close(fd)
        write_srt([{"start_ms": s, "end_ms": e, "text": t} for s, e, t in data], out)
        entries = parse_srt(out)
        assert len(entries) == 2
        assert entries[0]["start_ms"] == 0
        assert entries[0]["end_ms"] == 1500
        assert entries[1]["start_ms"] == 1800
        os.remove(out)


# ── 脚本检测 ────────────────────────────────────────────────

class TestDetectScript:
    def test_cjk(self):
        assert detect_script("你好世界") == "cjk"
        assert detect_script("こんにちは") == "cjk"

    def test_latin(self):
        assert detect_script("Hello world") == "latin"
        assert detect_script("Bonjour le monde") == "latin"

    def test_mixed_cjk_dominant(self):
        assert detect_script("你好世界 hello") == "cjk"


# ── 核心优化 ────────────────────────────────────────────────

class TestOptimizeSrt:
    def test_short_segment_extended(self):
        """过短字幕应被拉伸到最小可读时长。"""
        path = _write_temp_srt([
            (0, 300, "你好"),  # 仅 0.3s
            (2000, 5000, "第二句文字内容"),
        ])
        fd, out = tempfile.mkstemp(suffix=".srt")
        os.close(fd)

        stats = optimize_srt(path, out, lang="zh")
        assert stats["adjusted"] >= 1

        entries = parse_srt(out)
        dur0 = entries[0]["end_ms"] - entries[0]["start_ms"]
        assert dur0 >= 1500, f"首条时长 {dur0}ms < 1500ms 最小要求"

        os.remove(path)
        os.remove(out)

    def test_already_good_passes_through(self):
        """已有合理时长的字幕原样通过。"""
        path = _write_temp_srt([
            (0, 3000, "这段话的时间已经足够长了"),
            (3500, 7000, "第二句也是合理的时间长度"),
        ])
        fd, out = tempfile.mkstemp(suffix=".srt")
        os.close(fd)

        stats = optimize_srt(path, out, lang="zh")
        assert stats["adjusted"] == 0

        entries = parse_srt(out)
        assert entries[0]["start_ms"] == 0
        assert entries[0]["end_ms"] == 3000

        os.remove(path)
        os.remove(out)

    def test_adjacent_short_merged(self):
        """相邻短字幕间隙小时应被合并。"""
        path = _write_temp_srt([
            (0, 500, "第一句"),
            (600, 1100, "第二句"),     # 间隙仅 100ms
            (3000, 6000, "第三句正常长度"),
        ])
        fd, out = tempfile.mkstemp(suffix=".srt")
        os.close(fd)

        stats = optimize_srt(path, out, lang="zh", max_merge_gap=0.3)
        assert stats["merged"] >= 1

        entries = parse_srt(out)
        assert len(entries) <= 2  # 合并后 ≤ 2 条

        os.remove(path)
        os.remove(out)

    def test_last_segment_free_extension(self):
        """最后一条字幕可自由延伸。"""
        path = _write_temp_srt([
            (0, 2000, "第一句正常"),
            (2500, 2800, "最后一句很短"),
        ])
        fd, out = tempfile.mkstemp(suffix=".srt")
        os.close(fd)

        stats = optimize_srt(path, out, lang="zh")
        entries = parse_srt(out)
        last_dur = entries[-1]["end_ms"] - entries[-1]["start_ms"]
        assert last_dur >= 1500, f"最后一条时长 {last_dur}ms < 1500ms"

        os.remove(path)
        os.remove(out)

    def test_no_overlap_after_optimization(self):
        """优化后不应出现时间重叠。"""
        path = _write_temp_srt([
            (0, 500, "A"),
            (600, 1100, "B"),
            (1200, 1700, "C"),
            (1800, 4000, "D"),
        ])
        fd, out = tempfile.mkstemp(suffix=".srt")
        os.close(fd)

        optimize_srt(path, out, lang="zh")
        entries = parse_srt(out)

        for i in range(len(entries) - 1):
            assert entries[i]["end_ms"] <= entries[i + 1]["start_ms"], (
                f"条目 {i} end={entries[i]['end_ms']} > 条目 {i+1} start={entries[i+1]['start_ms']}"
            )

        os.remove(path)
        os.remove(out)

    def test_reading_speed_long_text(self):
        """长文本按阅读速度获得更多显示时间。"""
        long_text = "这是一段非常长的文字内容包含了大量的字符信息需要更长的阅读时间"
        path = _write_temp_srt([
            (0, 2000, long_text),
            (5000, 8000, "短"),
        ])
        fd, out = tempfile.mkstemp(suffix=".srt")
        os.close(fd)

        optimize_srt(path, out, lang="zh")
        entries = parse_srt(out)
        dur0 = entries[0]["end_ms"] - entries[0]["start_ms"]
        assert dur0 > 2000, f"长文本应被延长，实际 {dur0}ms"

        os.remove(path)
        os.remove(out)

    def test_empty_srt_returns_zero_stats(self):
        path = _write_temp_srt([])
        fd, out = tempfile.mkstemp(suffix=".srt")
        os.close(fd)
        stats = optimize_srt(path, out)
        assert stats == {"total": 0, "adjusted": 0, "merged": 0}
        os.remove(path)
        os.remove(out)


# ── 双语模式 ────────────────────────────────────────────────

class TestOptimizeBilingual:
    def test_basic_bilingual(self):
        target = _write_temp_srt([
            (0, 500, "你好"),
            (2500, 5000, "世界很大"),
        ])
        source = _write_temp_srt([
            (0, 500, "Hello"),
            (2500, 5000, "The world is big"),
        ])
        fd, out = tempfile.mkstemp(suffix=".srt")
        os.close(fd)

        stats = optimize_bilingual(target, source, out, lang="zh")
        assert stats["total"] == 2

        entries = parse_srt(out)
        assert len(entries) >= 1
        dur0 = entries[0]["end_ms"] - entries[0]["start_ms"]
        assert dur0 >= 1500

        os.remove(target)
        os.remove(source)
        os.remove(out)

    def test_mismatched_count_raises(self):
        target = _write_temp_srt([
            (0, 1000, "A"),
            (1500, 3000, "B"),
        ])
        source = _write_temp_srt([
            (0, 1000, "X"),
        ])
        fd, out = tempfile.mkstemp(suffix=".srt")
        os.close(fd)

        with pytest.raises(ValueError, match="条目数不一致"):
            optimize_bilingual(target, source, out)

        os.remove(target)
        os.remove(source)
        os.remove(out)


# ── 时间格式化 ───────────────────────────────────────────────

class TestTimeFormat:
    def test_parse_format_roundtrip(self):
        assert _parse_time("00:00:01,500") == 1500
        assert _format_time(1500) == "00:00:01,500"
        assert _format_time(3661000) == "01:01:01,000"
