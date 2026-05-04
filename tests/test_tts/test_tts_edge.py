"""
EdgeTTSEngine 单元测试

mock edge_tts.Communicate 避免真实网络调用。
测试重试逻辑、错误处理、正常流程。
"""

import os
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


@pytest.fixture
def mock_edge_tts():
    """mock edge_tts.Communicate.save()，写入临时 MP3 帧头避免 ffmpeg 报错"""
    with patch("edge_tts.Communicate") as mock_comm:
        mock_instance = MagicMock()

        async def fake_save(path):
            """写入一个合法的最小 MP3 帧头（ffmpeg 可识别）"""
            with open(path, "wb") as f:
                # MP3 帧同步头 (11bit=1) + MPEG1 Layer3 + 128kbps + 44100Hz + 联合立体声
                f.write(bytes([
                    0xFF, 0xFB, 0x90, 0x00,  # sync + MPEG1 L3 + 128k + 44.1k
                ]))

        mock_instance.save = AsyncMock(wraps=fake_save)
        mock_comm.return_value = mock_instance
        yield mock_comm, mock_instance


@pytest.fixture
def mock_audio_file_clip():
    """mock AudioFileClip.duration 返回固定值"""
    with patch("moviepy.audio.io.AudioFileClip.AudioFileClip") as mock_clip:
        mock_instance = MagicMock()
        mock_instance.duration = 3.5
        mock_instance.close = MagicMock()
        mock_clip.return_value = mock_instance
        yield mock_clip


@pytest.fixture(autouse=True)
def mock_ffmpeg_conversion():
    """mock subprocess.run 避免真实 ffmpeg 调用（测试环境无合法 MP3 文件）"""
    with patch("subprocess.run") as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_run.return_value = mock_result
        yield mock_run


class TestEdgeTTSEngine:
    """EdgeTTSEngine 单元测试"""

    def test_import(self):
        """引擎可导入"""
        from pipeline.tts_edge import EdgeTTSEngine

        engine = EdgeTTSEngine(voice="zh-CN-XiaoxiaoNeural")
        assert engine.voice == "zh-CN-XiaoxiaoNeural"

    def test_synthesize_success(self, mock_edge_tts, mock_audio_file_clip, temp_dir):
        """正常合成应返回音频时长"""
        from pipeline.tts_edge import EdgeTTSEngine

        engine = EdgeTTSEngine(voice="zh-CN-XiaoxiaoNeural")
        output_path = os.path.join(temp_dir, "test.wav")
        duration = engine.synthesize("你好", output_path, rate="+30%")

        assert duration == 3.5
        mock_edge_tts[0].assert_called_once()
        mock_edge_tts[1].save.assert_called_once()

    def test_synthesize_with_emotion_ignored(
        self, mock_edge_tts, mock_audio_file_clip, temp_dir
    ):
        """EdgeTTS 应忽略 emotion 参数"""
        from pipeline.tts_edge import EdgeTTSEngine
        from pipeline.tts_engine import EmotionStyle

        engine = EdgeTTSEngine()
        output_path = os.path.join(temp_dir, "test.wav")
        emotion = EmotionStyle(style_name="cheerful", style_degree=1.5)

        duration = engine.synthesize("测试", output_path, rate="+0%", emotion=emotion)
        assert duration == 3.5

    def test_retry_on_failure(self, temp_dir):
        """重试 3 次后最终抛出 RuntimeError"""
        from pipeline.tts_edge import EdgeTTSEngine

        engine = EdgeTTSEngine(
            voice="zh-CN-XiaoxiaoNeural",
            max_retries=3,
            retry_delay=0.01,
        )
        output_path = os.path.join(temp_dir, "test.wav")

        with patch("edge_tts.Communicate") as mock_comm:
            mock_instance = MagicMock()
            # save 必须是 AsyncMock，因为 _synthesize_async 里 await tts.save()
            mock_instance.save = AsyncMock(side_effect=ConnectionError("网络超时"))
            mock_comm.return_value = mock_instance

            with pytest.raises(RuntimeError, match="最大重试次数"):
                engine.synthesize("测试", output_path)

            assert mock_comm.call_count == 3

    def test_error_log_on_final_failure(self, temp_dir):
        """最终失败时应写入错误日志"""
        from pipeline.tts_edge import EdgeTTSEngine

        log_path = os.path.join(temp_dir, "error_log.txt")
        engine = EdgeTTSEngine(max_retries=1, retry_delay=0.01, error_log_path=log_path)

        with patch("edge_tts.Communicate") as mock_comm:
            mock_instance = MagicMock()
            mock_instance.save = AsyncMock(side_effect=Exception("不通"))
            mock_comm.return_value = mock_instance

            with pytest.raises(RuntimeError):
                engine.synthesize("测试", os.path.join(temp_dir, "test.wav"))

        assert os.path.exists(log_path)
        with open(log_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "测试" in content

    def test_retry_then_succeed(self, temp_dir):
        """前 2 次失败，第 3 次成功"""
        from pipeline.tts_edge import EdgeTTSEngine

        engine = EdgeTTSEngine(max_retries=3, retry_delay=0.01)
        output_path = os.path.join(temp_dir, "test.wav")
        call_count = 0

        class Communicator:
            def __init__(self, **kwargs):
                pass

            async def save(self, path):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise ConnectionError("暂时不通")
                # 写入合法 MP3 帧头
                with open(path, "wb") as f:
                    f.write(bytes([0xFF, 0xFB, 0x90, 0x00]))

        with patch("edge_tts.Communicate", return_value=Communicator()):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock()
                mock_run.return_value.returncode = 0
                with patch("os.path.isfile", return_value=True):
                    with patch("os.remove"):
                        with patch("moviepy.audio.io.AudioFileClip.AudioFileClip") as mock_clip:
                            mock_instance = MagicMock()
                            mock_instance.duration = 2.0
                            mock_instance.close = MagicMock()
                            mock_clip.return_value = mock_instance

                            duration = engine.synthesize("测试", output_path)

        assert duration == 2.0
        assert call_count == 3

    def test_supports_emotion_false(self):
        """EdgeTTSEngine 不支持情感克隆"""
        from pipeline.tts_edge import EdgeTTSEngine

        engine = EdgeTTSEngine()
        assert engine.supports_emotion() is False
        assert engine.emotion_modes() == []

    def test_factory_from_config(self, temp_dir):
        """EdgeTTSEngineFactory 可从 TTSConfig 创建引擎"""
        from pipeline.tts_edge import EdgeTTSEngineFactory
        from pipeline.tts_config import TTSConfig

        config = TTSConfig(
            voice="en-US-JennyNeural",
        )
        engine = EdgeTTSEngineFactory.from_config(config)
        assert engine.voice == "en-US-JennyNeural"
