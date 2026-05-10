"""
BaseTTSEngine Protocol 和 EmotionStyle 单元测试
"""

import os

import pytest
from pipeline.tts_engine import (
    EmotionStyle,
    BaseTTSEngine,
    NoopTTSEngine,
    is_tts_engine,
)


class TestEmotionStyle:
    """EmotionStyle 数据类测试"""

    def test_default_values(self):
        """默认构造，所有字段为 None"""
        es = EmotionStyle()
        assert es.style_name is None
        assert es.style_degree is None
        assert es.reference_audio is None
        assert es.reference_text is None
        assert es.role is None

    def test_parameter_mode(self):
        """参数式情感：style_name + style_degree"""
        es = EmotionStyle(style_name="cheerful", style_degree=1.5)
        assert es.style_name == "cheerful"
        assert es.style_degree == 1.5

    def test_reference_mode(self):
        """参考音频式情感：reference_audio"""
        es = EmotionStyle(reference_audio="happy_sample.wav")
        assert es.reference_audio == "happy_sample.wav"

    def test_both_modes(self):
        """两种模式同时传参"""
        es = EmotionStyle(
            style_name="excited",
            style_degree=2.0,
            reference_audio="excited_ref.wav",
            role="narration",
        )
        assert es.style_name == "excited"
        assert es.reference_audio == "excited_ref.wav"
        assert es.role == "narration"


class TestBaseTTSEngineProtocol:
    """BaseTTSEngine Protocol 结构类型检查"""

    def test_noop_engine_implements_protocol(self):
        """NoopTTSEngine 应符合 BaseTTSEngine Protocol"""
        engine = NoopTTSEngine()
        assert is_tts_engine(engine) is True
        assert isinstance(engine, BaseTTSEngine) is True

    def test_noop_engine_supports_emotion(self):
        """NoopTTSEngine 支持情感克隆"""
        engine = NoopTTSEngine()
        assert engine.supports_emotion() is True
        assert "parameter" in engine.emotion_modes()
        assert "reference" in engine.emotion_modes()

    def test_noop_synthesize_creates_file(self, temp_dir):
        """NoopTTSEngine.synthesize 应创建文件并返回固定时长"""
        engine = NoopTTSEngine()
        output_path = os.path.join(temp_dir, "test.wav")

        duration = engine.synthesize("测试", output_path)
        assert os.path.exists(output_path)
        assert duration == 1.0

    def test_noop_get_voices(self):
        """NoopTTSEngine.get_voices 返回空列表"""
        engine = NoopTTSEngine()
        result = engine.get_voices()
        assert result == []


class TestCustomEngineProtocol:
    """测试自定义引擎是否被 Protocol 正确识别"""

    def test_duck_typing_matches(self):
        """形状匹配的对象被视为 BaseTTSEngine"""
        class MyEngine:
            def synthesize(self, text, output_path, rate="+0%", emotion=None):
                return 1.0

            def get_voices(self):
                return []

            def supports_rate(self):
                return True

            def supports_emotion(self):
                return False

            def emotion_modes(self):
                return []

        engine = MyEngine()
        assert is_tts_engine(engine) is True

    def test_duck_typing_mismatch(self):
        """缺少方法的对象不被视为 BaseTTSEngine"""
        class BadEngine:
            pass

        assert is_tts_engine(BadEngine()) is False
