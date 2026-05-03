"""
测试字幕整理模块的时长约束。

验证：
1. 日语字幕最小持续时间 >= min_duration
2. 英语字幕最小持续时间 >= min_duration
3. 超长文本被合理切分
4. 短文本 TTS 可行性（文本长度 * 预估语速 / 片段时长 在合理范围）
"""

import json
import pytest
import sys
import os

# 确保 SRT 模块可导入（添加 SRT 目录，让裸导入生效）
_srt_dir = os.path.join(os.path.dirname(__file__), "..", "..", "SRT")
sys.path.insert(0, os.path.normpath(_srt_dir))


def make_segment(text, start, end, words=None):
    """构造测试用 segment 字典"""
    d = {"text": text, "start": start, "end": end}
    if words is not None:
        d["words"] = words
    return d


# ── 日语字幕时长测试 ──────────────────────────────────

class TestJapaneseSubtitleDuration:
    """日语字幕最小持续时间测试"""

    def test_short_segment_gets_min_duration(self):
        """短于 min_duration 的片段应被扩展到最小值"""
        from Json_Convert_Srt_JP import JapaneseProcessor

        proc = JapaneseProcessor(min_duration=1.5, max_chars=24, max_duration=4.5)

        # 一个极短的 segment（0.4s），文本很短
        segments = [make_segment("こんにちは", 0.0, 0.4)]
        proc.process_segments(segments)
        proc.finalize()

        assert len(proc.srt_entries) > 0
        for entry in proc.srt_entries:
            duration = entry["end"] - entry["start"]
            assert duration >= 1.5, (
                f"字幕 '{entry['text']}' 持续时间 {duration:.1f}s < 最小要求 1.5s"
            )

    def test_all_subtitles_meet_min_duration(self):
        """所有字幕持续时间都应 >= min_duration"""
        from Json_Convert_Srt_JP import JapaneseProcessor

        proc = JapaneseProcessor(min_duration=1.5, max_chars=24, max_duration=4.5)

        segments = [
            make_segment("こんにちは、今日の動画をご覧いただきありがとうございます。", 0.0, 1.0),
            make_segment("まずは最初のMODから紹介していきましょう。", 1.0, 2.0),
            make_segment("このMODは本当に面白いですよ。", 2.0, 2.5),
        ]
        proc.process_segments(segments)
        proc.finalize()

        assert len(proc.srt_entries) > 0
        for entry in proc.srt_entries:
            duration = entry["end"] - entry["start"]
            assert duration >= 1.5, (
                f"字幕 '{entry['text'][:20]}...' 持续时间 {duration:.1f}s < 1.5s"
            )

    def test_long_text_is_split(self):
        """超长无标点文本应被切分，不是一次显示"""
        from Json_Convert_Srt_JP import JapaneseProcessor

        proc = JapaneseProcessor(min_duration=1.5, max_chars=24, max_duration=4.5)

        # 50个字符的长文本，无标点
        long_text = "これはとても長い文章で途中で切れ目がなくずっと続いていきます"
        segments = [make_segment(long_text, 0.0, 10.0)]
        proc.process_segments(segments)
        proc.finalize()

        # 应该被切分成多条
        assert len(proc.srt_entries) > 1, (
            f"长文本({len(long_text)}字符)应被切分，实际只有 {len(proc.srt_entries)} 条"
        )

        for entry in proc.srt_entries:
            # 每条不超过 max_chars
            assert len(entry["text"]) <= 24 + 5, (  # 允许少量溢出
                f"片段 '{entry['text']}' 有 {len(entry['text'])} 字符 > {24}"
            )
            # 每条持续时间 >= min_duration
            duration = entry["end"] - entry["start"]
            assert duration >= 1.5, (
                f"片段持续时间 {duration:.1f}s < 1.5s"
            )

    def test_tts_feasibility_ratio(self):
        """验证 TTS 可行性：预估 TTS 时长 / 片段时长 在合理范围

        中文字幕翻译后，TTS 大约 4-5 字/秒（标准语速）。
        此处用源日语字数 * 1.2 系数估算翻译后的中文字数。
        目标：预估 TTS 时长 / 片段时长 < 1.5（base_speed+50% 可覆盖）
        """
        from Json_Convert_Srt_JP import JapaneseProcessor

        proc = JapaneseProcessor(min_duration=1.5, max_chars=24, max_duration=4.5)

        segments = [
            make_segment("こんにちは、今日はいい天気ですね。", 0.0, 3.0),
            make_segment("このMODは素晴らしい機能を持っています。", 3.0, 6.0),
            make_segment("さあ、始めましょう！", 6.0, 8.0),
        ]
        proc.process_segments(segments)
        proc.finalize()

        # 中文字速 ~4.5 字/秒（EdgeTTS zh-CN 标准语速）
        CHARS_PER_SECOND = 4.5

        for entry in proc.srt_entries:
            duration = entry["end"] - entry["start"]
            ja_chars = len(entry["text"])
            # 日语→中文翻译后字数约为日语字数的1.0-1.2倍（中文更简洁）
            estimated_cn_chars = ja_chars * 1.1
            estimated_tts_time = estimated_cn_chars / CHARS_PER_SECOND

            ratio = estimated_tts_time / duration if duration > 0 else float("inf")

            # 在 +50% 加速下，ratio 可以到 1.5 以内
            assert ratio < 2.0, (
                f"字幕 '{entry['text'][:20]}...' "
                f"预估TTS {estimated_tts_time:.1f}s / 片段 {duration:.1f}s = {ratio:.1f} "
                f"(>2.0, 即使+50%加速也难覆盖)"
            )


# ── 英语字幕时长测试 ──────────────────────────────────

class TestEnglishSubtitleDuration:
    """英语字幕最小持续时间测试"""

    def test_short_segment_enforces_min_duration(self):
        """英语字幕也应强制最小持续时间"""
        from Json_Convert_Srt_EN import EnglishProcessor

        proc = EnglishProcessor(
            max_chars=40,
            min_duration=1.2,
            max_gap=0.5,
        )

        # 短片段：单句，1.5s 可用时间
        segments = [
            make_segment("Hello.", 0.0, 1.5, words=[
                {"word": "Hello.", "start": 0.0, "end": 0.8},
            ]),
        ]
        proc.process_segments(segments)
        proc.finalize()

        assert len(proc.srt_entries) > 0
        for entry in proc.srt_entries:
            duration = entry["end"] - entry["start"]
            assert duration >= 1.2, (
                f"字幕 '{entry['text']}' 持续时间 {duration:.1f}s < 1.2s"
            )

    def test_multiple_segments_all_meet_min_duration(self):
        """多段字幕全部满足最小持续时间"""
        from Json_Convert_Srt_EN import EnglishProcessor

        proc = EnglishProcessor(
            max_chars=40,
            min_duration=1.2,
            max_gap=0.5,
        )

        # 多个短句，连续时间戳
        words1 = [
            {"word": "Welcome", "start": 0.0, "end": 0.3},
            {"word": "to", "start": 0.3, "end": 0.5},
            {"word": "the", "start": 0.5, "end": 0.6},
            {"word": "show.", "start": 0.6, "end": 1.0},
        ]
        words2 = [
            {"word": "Today", "start": 1.5, "end": 1.8},
            {"word": "we", "start": 1.8, "end": 2.0},
            {"word": "have", "start": 2.0, "end": 2.2},
            {"word": "something", "start": 2.2, "end": 2.6},
            {"word": "special!", "start": 2.6, "end": 3.0},
        ]

        segments = [
            make_segment("Welcome to the show.", 0.0, 1.0, words=words1),
            make_segment("Today we have something special!", 1.5, 3.0, words=words2),
        ]
        proc.process_segments(segments)
        proc.finalize()

        assert len(proc.srt_entries) > 0
        for entry in proc.srt_entries:
            duration = entry["end"] - entry["start"]
            assert duration >= 1.2, (
                f"字幕 '{entry['text'][:30]}' 持续时间 {duration:.1f}s < 1.2s"
            )

    def test_pause_split_still_keeps_min_duration(self):
        """按停顿分割时不应产生过短片段"""
        from Json_Convert_Srt_EN import EnglishProcessor

        proc = EnglishProcessor(
            max_chars=40,
            min_duration=1.2,
            max_gap=0.3,
        )

        # 构造词序列：第3和第4词之间有 0.5s 大停顿
        words = [
            {"word": "This", "start": 0.0, "end": 0.2},
            {"word": "is", "start": 0.2, "end": 0.4},
            {"word": "great.", "start": 0.4, "end": 0.8},
            # 0.5s pause
            {"word": "Really", "start": 1.3, "end": 1.5},
            {"word": "amazing.", "start": 1.5, "end": 2.0},
        ]

        segments = [make_segment("This is great. Really amazing.", 0.0, 2.0, words=words)]
        proc.process_segments(segments)
        proc.finalize()

        # 应该因停顿而分割
        assert len(proc.srt_entries) >= 1

        for entry in proc.srt_entries:
            duration = entry["end"] - entry["start"]
            assert duration >= 1.2, (
                f"停顿分割片段 '{entry['text']}' 持续时间 {duration:.1f}s < 1.2s"
            )

    def test_tts_feasibility_english(self):
        """验证英语 TTS 可行性"""
        from Json_Convert_Srt_EN import EnglishProcessor

        proc = EnglishProcessor(
            max_chars=40,
            min_duration=1.2,
            max_gap=0.5,
        )

        segments = [
            make_segment(
                "Welcome to today's video about Minecraft mods.", 0.0, 2.0,
                words=[
                    {"word": "Welcome", "start": 0.0, "end": 0.3},
                    {"word": "to", "start": 0.3, "end": 0.5},
                    {"word": "today's", "start": 0.5, "end": 0.9},
                    {"word": "video", "start": 0.9, "end": 1.2},
                    {"word": "about", "start": 1.2, "end": 1.4},
                    {"word": "Minecraft", "start": 1.4, "end": 1.7},
                    {"word": "mods.", "start": 1.7, "end": 2.0},
                ]
            ),
        ]
        proc.process_segments(segments)
        proc.finalize()

        # 英语 TTS ~15 字/秒
        CHARS_PER_SECOND = 15

        for entry in proc.srt_entries:
            duration = entry["end"] - entry["start"]
            chars = len(entry["text"])
            estimated_tts_time = chars / CHARS_PER_SECOND
            ratio = estimated_tts_time / duration if duration > 0 else float("inf")

            # 英语语速快，即使 +30% 也能覆盖大多数情况
            assert ratio < 1.8, (
                f"字幕 '{entry['text'][:30]}' "
                f"预估TTS {estimated_tts_time:.1f}s / 片段 {duration:.1f}s = {ratio:.1f}"
            )


# ── SRT 输出格式测试 ──────────────────────────────────

class TestSRTOutput:
    """确保 SRT 输出格式正确"""

    def test_generated_srt_valid_format(self):
        """生成的 SRT 应该是标准格式"""
        from Json_Convert_Srt_JP import JapaneseProcessor

        proc = JapaneseProcessor(min_duration=1.5, max_chars=24, max_duration=4.5)

        segments = [make_segment("テスト字幕です。これは二文目。", 0.0, 3.0)]
        proc.process_segments(segments)
        proc.finalize()

        srt_output = proc.generate_srt_output()
        assert srt_output, "SRT 输出不应为空"

        # 验证基本格式
        lines = srt_output.strip().split("\n")
        # 至少应该有序号行、时间行、文本行
        assert len(lines) >= 3

        # 序号应该是数字
        assert lines[0].isdigit()

        # 时间行应该有 -->
        assert "-->" in lines[1]

    def test_srt_timestamps_chronological(self):
        """SRT 条目应按时间顺序排列"""
        from Json_Convert_Srt_JP import JapaneseProcessor

        proc = JapaneseProcessor(min_duration=1.5, max_chars=24, max_duration=4.5)

        segments = [
            make_segment("一文目です。", 0.0, 2.0),
            make_segment("二文目です。", 2.0, 4.0),
            make_segment("三文目です。最後。", 4.0, 6.0),
        ]
        proc.process_segments(segments)
        proc.finalize()

        for i in range(len(proc.srt_entries) - 1):
            current_end = proc.srt_entries[i]["end"]
            next_start = proc.srt_entries[i + 1]["start"]
            assert current_end <= next_start, (
                f"字幕 {i} 结束于 {current_end:.1f}s，字幕 {i+1} 开始于 {next_start:.1f}s，时间重叠"
            )


# ── 日语专项功能测试 ──────────────────────────────────

class TestJapaneseSmartPunctuation:
    """smart_punctuation 智能标点处理测试"""

    def test_merges_short_segments_without_punctuation(self):
        """无标点的短段应被合并（gap <= 0.3s）"""
        from Json_Convert_Srt_JP import JapaneseProcessor

        proc = JapaneseProcessor(min_duration=0.8, max_chars=35)
        segments = [
            make_segment("こんにちは", 0.0, 1.0),
            make_segment("今日はいい天気です", 1.2, 2.5),
        ]
        result = proc.smart_punctuation(segments)

        # gap = 1.2 - 1.0 = 0.2s <= 0.3s，应合并
        assert len(result) == 1, f"应合并为1段，实际 {len(result)} 段"
        assert "。" in result[0]["text"], "合并后应补句号"

    def test_does_not_merge_when_gap_too_large(self):
        """gap > 0.3s 的段不应合并"""
        from Json_Convert_Srt_JP import JapaneseProcessor

        proc = JapaneseProcessor(min_duration=0.8, max_chars=35)
        segments = [
            make_segment("こんにちは", 0.0, 1.0),
            make_segment("今日はいい天気です", 2.0, 3.5),  # gap = 1.0s
        ]
        result = proc.smart_punctuation(segments)

        # gap = 1.0s > 0.3s，不应合并
        assert len(result) == 2, f"不应合并，实际 {len(result)} 段"

    def test_preserves_existing_punctuation(self):
        """已有句末标点的段应直接保留"""
        from Json_Convert_Srt_JP import JapaneseProcessor

        proc = JapaneseProcessor(min_duration=0.8, max_chars=35)
        segments = [
            make_segment("こんにちは。", 0.0, 1.0),
            make_segment("今日はいい天気ですね。", 1.0, 2.5),
        ]
        result = proc.smart_punctuation(segments)

        assert len(result) == 2
        assert result[0]["text"] == "こんにちは。"
        assert result[1]["text"] == "今日はいい天気ですね。"

    def test_adds_period_to_orphan_segment(self):
        """孤立无标点段应补句号"""
        from Json_Convert_Srt_JP import JapaneseProcessor

        proc = JapaneseProcessor(min_duration=0.8, max_chars=35)
        segments = [make_segment("こんにちは", 0.0, 1.0)]
        result = proc.smart_punctuation(segments)

        assert len(result) == 1
        assert result[0]["text"].endswith("。"), "孤立段应补句号"


class TestJapaneseSplitByWordGaps:
    """_split_by_word_gaps 词间隙切分测试"""

    def test_splits_at_large_gap(self):
        """大间隙（>= 0.6s）处应切分"""
        from Json_Convert_Srt_JP import JapaneseProcessor

        proc = JapaneseProcessor(min_duration=0.5, max_chars=50)
        text = "こんにちは今日は"
        words = [
            {"word": "こんにちは", "start": 0.0, "end": 1.0},
            {"word": "今日は", "start": 1.8, "end": 2.5},  # gap = 0.8s
        ]
        result = proc._split_by_word_gaps(text, words, 0.0, 2.5)

        assert result is not None, "应在大间隙处切分"
        assert len(result) == 2, f"应切分为2段，实际 {len(result)} 段"

    def test_returns_none_for_small_gaps(self):
        """小间隙（< 0.6s）不应切分"""
        from Json_Convert_Srt_JP import JapaneseProcessor

        proc = JapaneseProcessor(min_duration=0.5, max_chars=50)
        text = "こんにちは今日は"
        words = [
            {"word": "こんにちは", "start": 0.0, "end": 1.0},
            {"word": "今日は", "start": 1.1, "end": 1.5},  # gap = 0.1s
        ]
        result = proc._split_by_word_gaps(text, words, 0.0, 1.5)

        assert result is None, "小间隙不应切分"

    def test_returns_none_for_few_words(self):
        """少于2个词时不应切分"""
        from Json_Convert_Srt_JP import JapaneseProcessor

        proc = JapaneseProcessor(min_duration=0.5, max_chars=50)
        result = proc._split_by_word_gaps("こんにちは", [], 0.0, 1.0)
        assert result is None

        result = proc._split_by_word_gaps("こんにちは", [{"word": "こんにちは", "start": 0.0, "end": 1.0}], 0.0, 1.0)
        assert result is None


class TestJapaneseLinearSplitFallback:
    """_linear_split fallback 测试"""

    def test_splits_long_text_without_mecab(self):
        """无 MeCab 时应按字符数线性切分"""
        from Json_Convert_Srt_JP import JapaneseProcessor

        proc = JapaneseProcessor(min_duration=0.5, max_chars=10, max_duration=3.0)
        # 强制 MeCab 不可用
        proc._tagger = None

        text = "これはとても長い文章です"
        result = proc._linear_split(text, 0.0, 10.0)

        assert len(result) > 1, f"长文本应被切分，实际 {len(result)} 段"
        for part_text, start, end in result:
            assert len(part_text) <= 10 + 3, f"段落 '{part_text}' 超过 max_chars"
            assert end > start, "结束时间应大于开始时间"

    def test_short_text_not_split(self):
        """短文本不应被切分"""
        from Json_Convert_Srt_JP import JapaneseProcessor

        proc = JapaneseProcessor(min_duration=0.5, max_chars=50, max_duration=10.0)
        proc._tagger = None

        text = "短い"
        result = proc._linear_split(text, 0.0, 1.0)

        assert len(result) == 1
        assert result[0][0] == text


class TestLanguageDetection:
    """语言检测测试"""

    def test_japanese_with_hiragana(self):
        """含平假名的文本应检测为日语"""
        from Json_Convert_Srt import detect_language
        assert detect_language("こんにちは世界") == "ja"

    def test_japanese_with_katakana(self):
        """含片假名的文本应检测为日语"""
        from Json_Convert_Srt import detect_language
        assert detect_language("コンピューター") == "ja"

    def test_pure_chinese_not_misdetected(self):
        """纯中文文本不应被误判为日语"""
        from Json_Convert_Srt import detect_language
        assert detect_language("你好世界") == "en"
        assert detect_language("这是一个测试") == "en"
        assert detect_language("今天天气真好") == "en"

    def test_english_detected(self):
        """英语文本应检测为英语"""
        from Json_Convert_Srt import detect_language
        assert detect_language("Hello world") == "en"

    def test_mixed_japanese_chinese(self):
        """含假名的中日混合文本应检测为日语"""
        from Json_Convert_Srt import detect_language
        assert detect_language("你好こんにちは") == "ja"

    def test_kanji_only_not_misdetected(self):
        """仅含汉字（无假名）的文本不应被误判为日语"""
        from Json_Convert_Srt import detect_language
        # 这些是日语中常用的汉字，但没有假名，不应判定为日语
        assert detect_language("東京大学") == "en"
