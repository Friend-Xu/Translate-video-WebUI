"""
OpenVoiceCloner 单元测试
"""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestOpenVoiceConfig:
    """OpenVoiceConfig dataclass 测试"""

    def test_import(self):
        from pipeline.tts_openvoice import OpenVoiceConfig
        assert OpenVoiceConfig is not None

    def test_defaults(self):
        from pipeline.tts_openvoice import OpenVoiceConfig
        cfg = OpenVoiceConfig()
        assert cfg.enabled is False
        assert cfg.model_version == "v2"
        assert "Color_audio.WAV" in cfg.color_audio_path

    def test_custom(self):
        from pipeline.tts_openvoice import OpenVoiceConfig
        cfg = OpenVoiceConfig(enabled=True, model_version="v1")
        assert cfg.enabled is True
        assert cfg.model_version == "v1"


class TestNoopOpenVoiceCloner:
    """NoopOpenVoiceCloner 哑实现测试"""

    def test_import(self):
        from pipeline.tts_openvoice import NoopOpenVoiceCloner
        cloner = NoopOpenVoiceCloner()
        result = cloner.clone("/fake/path.wav", "/fake/out")
        assert result is None


class TestExtraVocalCloner:
    """ExtraVocalCloner 逻辑测试"""

    def test_import(self):
        from pipeline.tts_openvoice import ExtraVocalCloner, OpenVoiceConfig
        cloner = ExtraVocalCloner(OpenVoiceConfig())
        assert cloner.config.enabled is False

    def test_prepare_no_voice_path(self):
        """无 voice_path 时 prepare 返回 False"""
        from pipeline.tts_openvoice import ExtraVocalCloner, OpenVoiceConfig
        cloner = ExtraVocalCloner(OpenVoiceConfig())
        result = cloner.prepare(voice_path=None)
        assert result is False

    def test_prepare_voice_not_found(self):
        """voice_path 不存在时返回 False"""
        from pipeline.tts_openvoice import ExtraVocalCloner, OpenVoiceConfig
        cloner = ExtraVocalCloner(OpenVoiceConfig())
        result = cloner.prepare(voice_path="/nonexistent/path.wav")
        assert result is False

    def test_clone_no_color_file(self):
        """音色文件不存在时 clone 会报错"""
        from pipeline.tts_openvoice import ExtraVocalCloner, OpenVoiceConfig
        cfg = OpenVoiceConfig(color_audio_path="/nonexistent/color.wav")
        cloner = ExtraVocalCloner(cfg)
        result = cloner.clone("/fake/tts.wav", "/fake/out")
        assert result is None

    @patch("os.path.isfile", return_value=True)
    def test_clone_fails_gracefully(self, mock_isfile):
        """clone 失败返回 None（模拟 OpenVoice import 失败）"""
        from pipeline.tts_openvoice import ExtraVocalCloner, OpenVoiceConfig
        cfg = OpenVoiceConfig(color_audio_path="/fake/color.wav")
        cloner = ExtraVocalCloner(cfg)
        result = cloner.clone("/fake/tts.wav", "/fake/out")
        assert result is None

    def test_embedding_cache_initially_none(self):
        """ExtraVocalCloner 初始 embedding 缓存为 None"""
        from pipeline.tts_openvoice import ExtraVocalCloner, OpenVoiceConfig
        cloner = ExtraVocalCloner(OpenVoiceConfig())
        assert cloner._embedding is None

    def test_embedding_cache_persists_across_clones(self, temp_dir):
        """多次 clone 共享 embedding 缓存"""
        from pipeline.tts_openvoice import ExtraVocalCloner, OpenVoiceConfig

        color_path = os.path.join(temp_dir, "color.wav")
        with open(color_path, "wb") as f:
            f.write(b"FAKE")

        cfg = OpenVoiceConfig(color_audio_path=color_path)
        cloner = ExtraVocalCloner(cfg)

        # 首次 clone 失败（无 se_extractor），缓存被清空
        result1 = cloner.clone("/fake/a.wav", temp_dir)
        assert result1 is None
        # 失败后缓存被清空
        assert cloner._embedding is None

    def test_prepare_clears_embedding_cache_when_already_prepared(self):
        """已准备的 cloner 再次 prepare() 清空 embedding 缓存"""
        from pipeline.tts_openvoice import ExtraVocalCloner, OpenVoiceConfig
        cloner = ExtraVocalCloner(OpenVoiceConfig())
        cloner._prepared = True  # 模拟已准备
        cloner._embedding = "fake_embedding"  # 模拟已有缓存
        result = cloner.prepare()
        # 已准备时直接返回 True 并清空缓存
        assert result is True
        assert cloner._embedding is None
