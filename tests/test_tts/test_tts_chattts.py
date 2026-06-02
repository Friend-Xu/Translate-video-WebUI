"""
ChatTTSEngine 单元测试
"""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestChatTTSEngine:
    """ChatTTSEngine 基础测试（全 mock，不加载真实模型）"""

    def test_import(self):
        from pipeline.tts_chattts import ChatTTSEngine
        assert callable(ChatTTSEngine)

    def test_synthesize_creates_file(self, temp_dir):
        """合成成功后生成文件 — 模拟 worker 子进程交互"""
        from pipeline.tts_chattts import ChatTTSEngine

        engine = ChatTTSEngine()
        # Mock 子进程 — 不真正启动 worker，只 mock _send_command 返回成功
        engine._proc = MagicMock()
        engine._proc.poll.return_value = None
        engine._loaded = True

        with patch.object(engine, "_send_command") as mock_send:
            mock_send.return_value = {"status": "ok", "duration_s": 1.0}
            out_path = os.path.join(temp_dir, "test.wav")
            duration = engine.synthesize("你好世界", out_path)
            assert duration == 1.0
            mock_send.assert_called_once()
            req = mock_send.call_args[0][0]
            assert req["action"] == "synthesize"
            assert req["text"] == "你好世界"

    def test_synthesize_returns_correct_duration(self, temp_dir):
        """不同长度的音频返回正确的时长"""
        from pipeline.tts_chattts import ChatTTSEngine

        engine = ChatTTSEngine()
        engine._proc = MagicMock()
        engine._proc.poll.return_value = None
        engine._loaded = True

        with patch.object(engine, "_send_command") as mock_send:
            mock_send.return_value = {"status": "ok", "duration_s": 3.0}
            duration = engine.synthesize("你好", os.path.join(temp_dir, "t.wav"))
            assert duration == pytest.approx(3.0)

    def test_initial_model_not_loaded(self):
        """初始化时模型未加载"""
        from pipeline.tts_chattts import ChatTTSEngine
        engine = ChatTTSEngine()
        assert engine._loaded is False
        assert engine.model_loaded is False

    def test_load_model_called_on_first_synthesize(self, temp_dir):
        """首次 synthesize 会自动 warmup worker"""
        from pipeline.tts_chattts import ChatTTSEngine

        engine = ChatTTSEngine()
        # Mock warmup 行为：第一次 synthesize 时 _proc 为 None，应触发 warmup
        engine._loaded = False

        with patch.object(engine, "warmup") as mock_warmup:
            # warmup 应该设置 _loaded = True 使其继续到 synthesize
            def _fake_warmup():
                engine._loaded = True
                engine._proc = MagicMock()
                engine._proc.poll.return_value = None
            mock_warmup.side_effect = _fake_warmup

            with patch.object(engine, "_send_command") as mock_send:
                mock_send.return_value = {"status": "ok", "duration_s": 1.0}
                engine.synthesize("你好", os.path.join(temp_dir, "t.wav"))
                mock_warmup.assert_called_once()

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
