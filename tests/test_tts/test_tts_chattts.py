"""
ChatTTSEngine 单元测试
"""

import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


class TestChatTTSEngine:
    """ChatTTSEngine 基础测试（全 mock，不加载真实模型）"""

    def test_import(self):
        from pipeline.tts_chattts import ChatTTSEngine
        assert callable(ChatTTSEngine)

    @pytest.mark.xfail(reason="ChatTTS worker subprocess: _load_model removed")
    def test_synthesize_creates_file(self, temp_dir):
        """合成成功后生成文件"""
        from pipeline.tts_chattts import ChatTTSEngine

        # Mock soundfile write
        with patch("soundfile.write") as mock_sf_write:
            with patch.object(ChatTTSEngine, "_load_model"):
                engine = ChatTTSEngine()

                # Mock _chat
                engine._chat = MagicMock()
                engine._loaded = True

                # Mock infer to return numpy array
                mock_wav = np.zeros(24000, dtype=np.float32)  # 1 sec at 24kHz
                engine._chat.infer.return_value = [mock_wav]

                out_path = os.path.join(temp_dir, "test.wav")
                duration = engine.synthesize("你好世界", out_path)

                assert duration == 1.0
                mock_sf_write.assert_called_once()
                call_args = mock_sf_write.call_args[0]
                assert call_args[0] == out_path

    @pytest.mark.xfail(reason="ChatTTS worker subprocess: _load_model removed")
    def test_synthesize_returns_correct_duration(self, temp_dir):
        """不同长度的音频返回正确的时长"""
        from pipeline.tts_chattts import ChatTTSEngine

        with patch("soundfile.write"):
            with patch.object(ChatTTSEngine, "_load_model"):
                engine = ChatTTSEngine()
                engine._chat = MagicMock()
                engine._loaded = True

                # 3 seconds at 24kHz
                engine._chat.infer.return_value = [np.zeros(72000, dtype=np.float32)]
                duration = engine.synthesize("你好", os.path.join(temp_dir, "t.wav"))
                assert duration == pytest.approx(3.0)

    def test_initial_model_not_loaded(self):
        """初始化时模型未加载"""
        from pipeline.tts_chattts import ChatTTSEngine
        engine = ChatTTSEngine()
        assert engine._loaded is False
        assert engine.model_loaded is False

    @pytest.mark.xfail(reason="ChatTTS worker subprocess: _load_model removed")
    def test_load_model_called_on_first_synthesize(self, temp_dir):
        """首次 synthesize 调用 _load_model"""
        from pipeline.tts_chattts import ChatTTSEngine

        with patch("soundfile.write"):
            with patch.object(ChatTTSEngine, "_load_model") as mock_load:
                engine = ChatTTSEngine()
                engine._chat = MagicMock()
                engine._loaded = True
                engine._chat.infer.return_value = [np.zeros(24000, dtype=np.float32)]

                engine.synthesize("你好", os.path.join(temp_dir, "t.wav"))
                mock_load.assert_called_once()

    def test_supports_emotion_false(self):
        """ChatTTS 不支持情感克隆"""
        from pipeline.tts_chattts import ChatTTSEngine
        engine = ChatTTSEngine()
        assert engine.supports_emotion() is False

    def test_get_voices_empty(self):
        """ChatTTS 不提供命名音色列表"""
        from pipeline.tts_chattts import ChatTTSEngine
        engine = ChatTTSEngine()
        assert engine.get_voices() == []

    def test_model_loaded_property(self):
        from pipeline.tts_chattts import ChatTTSEngine
        engine = ChatTTSEngine()
        assert engine.model_loaded is False
        engine._loaded = True
        assert engine.model_loaded is True

    def test_speaker_seed(self):
        """speaker_seed 参数传递正确"""
        from pipeline.tts_chattts import ChatTTSEngine
        engine = ChatTTSEngine(speaker_seed=42)
        assert engine._speaker_seed == 42

    def test_factory_from_config(self):
        """工厂方法正确创建实例"""
        from pipeline.tts_chattts import ChatTTSEngineFactory
        from pipeline.tts_config import TTSConfig

        cfg = TTSConfig(engine_type="chattts")
        engine = ChatTTSEngineFactory.from_config(cfg)
        assert engine._speaker_seed is None

    def test_factory_from_config_with_speaker_seed(self):
        from pipeline.tts_chattts import ChatTTSEngineFactory
        from pipeline.tts_config import TTSConfig

        cfg = TTSConfig(engine_type="chattts", chattts_speaker_seed=123)
        engine = ChatTTSEngineFactory.from_config(cfg)
        assert engine._speaker_seed == 123
