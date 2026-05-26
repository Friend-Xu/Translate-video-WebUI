"""
音频预处理适配器测试 (Chapter 10 实施验证)

测试 MediaValidatorAdapter, DemucsAdapter, VADBoundaryAdapter。
使用 mock 数据避免 GPU/模型依赖。
"""
import pytest
from core.adapters.media_validator_adapter import (
    MediaValidatorAdapter, AudioDefectContext,
)
from core.adapters.demucs_adapter import DemucsAdapter, DemucsContext
from core.adapters.vad_boundary_adapter import VADBoundaryAdapter, VADBoundaryContext
from core.runtime.patch import OpCode


class TestAudioDefectContext:
    """AudioDefectContext 数据结构验证"""

    def test_defaults(self):
        ctx = AudioDefectContext(video_path="/test/video.mp4")
        assert ctx.video_path == "/test/video.mp4"
        assert ctx.sample_rate == 16000
        assert ctx.channels == 1
        assert ctx.output_audio_path == ""

    def test_full_context(self):
        ctx = AudioDefectContext(
            video_path="/test/video.mp4",
            output_audio_path="/test/output.wav",
            sample_rate=44100, channels=2,
        )
        assert ctx.output_audio_path == "/test/output.wav"
        assert ctx.sample_rate == 44100
        assert ctx.channels == 2


class TestDemucsContext:
    """DemucsContext 数据结构验证"""

    def test_defaults(self):
        ctx = DemucsContext(audio_path="/audio/vocals.wav")
        assert ctx.audio_path == "/audio/vocals.wav"
        assert ctx.model_name == "htdemucs"
        assert ctx.device == "cuda"

    def test_custom_model(self):
        ctx = DemucsContext(
            audio_path="/audio/vocals.wav",
            model_name="htdemucs_ft", device="cpu",
        )
        assert ctx.model_name == "htdemucs_ft"
        assert ctx.device == "cpu"


class TestVADBoundaryContext:
    """VADBoundaryContext 数据结构验证"""

    def test_defaults(self):
        ctx = VADBoundaryContext(audio_path="/audio/speech.wav")
        assert ctx.audio_path == "/audio/speech.wav"
        assert ctx.threshold == 0.25
        assert ctx.min_silence_gap == 0.5
        assert ctx.min_speech_duration == 0.5

    def test_custom_threshold(self):
        ctx = VADBoundaryContext(
            audio_path="/audio/quiet.wav", threshold=0.15,
        )
        assert ctx.threshold == 0.15


class TestVADBoundaryAdapter:
    """VADBoundaryAdapter 测试（不启动真实 VAD）"""

    def test_detect_boundaries_empty_on_error(self):
        """当 VAD 不可用时返回空列表"""
        adapter = VADBoundaryAdapter()
        ctx = VADBoundaryContext(audio_path="/nonexistent/audio.wav")
        patches = adapter.detect_boundaries(ctx)
        assert isinstance(patches, list)
        assert len(patches) == 0

    def test_estimate_confidence_optimal(self):
        """0.5-30s 段置信度最高"""
        assert VADBoundaryAdapter._estimate_confidence(5.0) == 0.90
        assert VADBoundaryAdapter._estimate_confidence(15.0) == 0.90

    def test_estimate_confidence_short(self):
        """<0.3s 段置信度低"""
        assert VADBoundaryAdapter._estimate_confidence(0.1) == 0.60

    def test_estimate_confidence_long(self):
        """>60s 段置信度较低"""
        assert VADBoundaryAdapter._estimate_confidence(90.0) == 0.65

    def test_estimate_confidence_mid(self):
        """0.3-0.5s 和 30-60s 中等"""
        assert VADBoundaryAdapter._estimate_confidence(0.4) == 0.80
        assert VADBoundaryAdapter._estimate_confidence(45.0) == 0.80
