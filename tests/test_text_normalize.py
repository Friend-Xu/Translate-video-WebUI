"""测试 _normalize_text 小数格式归一化。

验证 whisperX 空格 artifact 和全角句点在小数中的处理。
"""
import pytest
from pipeline.tts_chattts import _normalize_text


class TestNormalizeDecimal:
    """小数格式归一化测试"""

    def test_normal_decimal(self):
        """正常小数不被破坏"""
        result = _normalize_text("1.19")
        assert "一点一九" in result

    def test_space_before_dot_artifact(self):
        """whisperX 空格 artifact: "1 .19" """
        result = _normalize_text("1 .19")
        assert "一点一九" in result

    def test_spaces_around_dot(self):
        """多空格: "1 . 19" """
        result = _normalize_text("1 . 19")
        assert "一点一九" in result

    def test_fullwidth_period(self):
        """全角句点: "1．19" """
        result = _normalize_text("1．19")
        assert "一点一九" in result

    def test_three_segment_version(self):
        """三段版本号混空格: "1. 19 .2" """
        result = _normalize_text("1. 19 .2")
        assert "一点一九点二" in result

    def test_three_segment_all_spaces(self):
        """三段全空格: "1 . 19 . 2" """
        result = _normalize_text("1 . 19 . 2")
        assert "一点一九点二" in result

    def test_multiple_decimals(self):
        """一段文本中多个小数"""
        result = _normalize_text("版本1.18和1.19都支持")
        assert "一点一八" in result
        assert "一点一九" in result

    def test_real_world_minecraft(self):
        """真实 Minecraft 场景"""
        result = _normalize_text("适用于1 .19和1 .18 .2")
        assert "一点一九" in result
        assert "一点一八点二" in result

    def test_percentage_unaffected(self):
        """百分数不受影响"""
        result = _normalize_text("50%→100%")
        assert "百分之五十" in result

    def test_integer_unaffected(self):
        """普通整数不受影响"""
        result = _normalize_text("总共10个")
        assert "十个" in result or "十" in result

    def test_no_crash_on_empty(self):
        """空字符串不崩溃"""
        result = _normalize_text("")
        assert result == ""

    def test_no_crash_on_plain_text(self):
        """纯文本不崩溃"""
        result = _normalize_text("今天天气真好")
        assert "今天天气真好" in result
