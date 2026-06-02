"""
GPU 编码器自动检测单元测试
"""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestGpuDetect:
    """GPU 编码器检测测试"""

    def test_import(self):
        from pipeline.gpu_detect import detect_best_encoder, detect_gpu_info, apply_best_encoder_to_config
        assert callable(detect_best_encoder)
        assert callable(detect_gpu_info)
        assert callable(apply_best_encoder_to_config)

    @patch("subprocess.run")
    def test_detect_libx264_when_no_hw(self, mock_run):
        """无硬件编码器时返回 libx264"""
        from pipeline.gpu_detect import detect_best_encoder

        # mock ffmpeg -encoders 返回只有 libx264
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Encoders:\n V..... libx264           H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10\n",
        )

        result = detect_best_encoder(ffmpeg_exe="/fake/ffmpeg")
        assert result == "libx264"

    @patch("subprocess.run")
    def test_detect_nvenc_available_returns_libx264(self):
        """有 nvenc 且 NVIDIA GPU 存在 → 返回 libx264 (优先级最高，NVENC 并发限制)"""
        from pipeline.gpu_detect import detect_best_encoder

        def side_effect(cmd, **kwargs):
            if "nvidia-smi" in cmd:
                return MagicMock(returncode=0, stdout="NVIDIA GeForce RTX 4090\n")
            if "-encoders" in cmd:
                return MagicMock(returncode=0, stdout="Encoders:\n V..... h264_nvenc\n V..... libx264\n")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = side_effect

        result = detect_best_encoder(ffmpeg_exe="/fake/ffmpeg")
        assert result == "libx264"

    @patch("subprocess.run")
    def test_detect_nvenc_absent_no_gpu(self, mock_run):
        """nvidia-smi 不可用但 nvenc 在列表中 → 跳过 nvenc，回退到下一个"""
        from pipeline.gpu_detect import detect_best_encoder

        calls = []

        def side_effect(cmd, **kwargs):
            calls.append(cmd[0])
            if cmd[0] == "/fake/ffmpeg":
                return MagicMock(returncode=0, stdout="Encoders:\n V..... h264_nvenc\n V..... libx264\n")
            if cmd[0] == "nvidia-smi":
                raise FileNotFoundError("nvidia-smi not found")
            return MagicMock(returncode=1, stdout="")

        mock_run.side_effect = side_effect

        result = detect_best_encoder(ffmpeg_exe="/fake/ffmpeg")
        # nvenc 存在但 nvidia-smi 失败 → 跳过 → libx264
        assert result == "libx264"

    @patch("subprocess.run")
    def test_ffmpeg_not_found(self, mock_run):
        """ffmpeg 二进制不可用时返回 libx264"""
        from pipeline.gpu_detect import detect_best_encoder

        mock_run.side_effect = FileNotFoundError("ffmpeg not found")

        result = detect_best_encoder(ffmpeg_exe="/nonexistent/ffmpeg")
        assert result == "libx264"

    def test_apply_skips_when_already_hw(self):
        """config.video_codec 已是硬件编码器时不覆盖"""
        from pipeline.gpu_detect import apply_best_encoder_to_config
        from pipeline.tts_config import TTSConfig

        cfg = TTSConfig(video_codec="h264_nvenc")
        original = cfg.video_codec
        apply_best_encoder_to_config(cfg)
        assert cfg.video_codec == original

    @patch("pipeline.gpu_detect.detect_best_encoder")
    def test_apply_overrides_libx264(self, mock_detect):
        """config.video_codec 是 libx264 时自动检测并更新"""
        from pipeline.gpu_detect import apply_best_encoder_to_config
        from pipeline.tts_config import TTSConfig

        mock_detect.return_value = "h264_nvenc"

        cfg = TTSConfig(video_codec="libx264")
        apply_best_encoder_to_config(cfg)
        assert cfg.video_codec == "h264_nvenc"

    def test_detect_gpu_info_no_nvidia(self):
        """nvidia-smi 不存在时返回未检测到"""
        from pipeline.gpu_detect import detect_gpu_info
        with patch("subprocess.run", side_effect=FileNotFoundError("nvidia-smi not found")):
            info = detect_gpu_info()
            assert info["vendor"] is None
