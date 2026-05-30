"""
VideoMerger 单元测试
"""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestMergerConfig:
    """MergerConfig dataclass 测试"""

    def test_import(self):
        from pipeline.video_merger import MergerConfig
        cfg = MergerConfig()
        assert cfg.strategy == "ffmpeg"
        assert cfg.concat_use_stream_copy is True

    def test_custom(self):
        from pipeline.video_merger import MergerConfig
        cfg = MergerConfig(strategy="moviepy", concat_use_stream_copy=False)
        assert cfg.strategy == "moviepy"
        assert cfg.concat_use_stream_copy is False


class TestVideoMerger:
    """VideoMerger 核心逻辑测试"""

    def test_import(self):
        from pipeline.video_merger import VideoMerger, MergerConfig
        merger = VideoMerger(MergerConfig())
        assert merger is not None

    def test_collect_segments_empty_dir(self, temp_dir):
        """空目录 → 返回空列表"""
        from pipeline.video_merger import VideoMerger, MergerConfig
        merger = VideoMerger(MergerConfig())
        segments = merger._collect_segments(temp_dir)
        assert segments == []

    def test_collect_segments_non_existent_dir(self):
        """不存在的目录 → 返回空列表"""
        from pipeline.video_merger import VideoMerger, MergerConfig
        merger = VideoMerger(MergerConfig())
        segments = merger._collect_segments("/nonexistent_dir_12345")
        assert segments == []

    def test_collect_segments_sorts_by_start(self, temp_dir):
        """视频段文件按开始时间排序"""
        from pipeline.video_merger import VideoMerger, MergerConfig

        # 创建乱序文件
        for start, end in [(5000, 8000), (1000, 4000), (3000, 4999), (0, 999)]:
            path = os.path.join(temp_dir, f"TTS_{start}_{end}.mp4")
            with open(path, "w") as f:
                f.write("dummy")

        merger = VideoMerger(MergerConfig())
        segments = merger._collect_segments(temp_dir)

        # 验证排序: 0, 1000, 3000, 5000
        starts = [int(os.path.basename(s).split("_")[1]) for s in segments]
        assert starts == [0, 1000, 3000, 5000]

    def test_collect_segments_filters_non_tts(self, temp_dir):
        """非 TTS_ 前缀的文件被过滤"""
        from pipeline.video_merger import VideoMerger, MergerConfig

        with open(os.path.join(temp_dir, "TTS_1000_2000.mp4"), "w") as f:
            f.write("dummy")
        with open(os.path.join(temp_dir, "other_3000_4000.mp4"), "w") as f:
            f.write("dummy")
        with open(os.path.join(temp_dir, "readme.txt"), "w") as f:
            f.write("dummy")

        merger = VideoMerger(MergerConfig())
        segments = merger._collect_segments(temp_dir)
        assert len(segments) == 1
        assert "TTS_1000_2000.mp4" in segments[0]

    def test_merge_empty_dir(self, temp_dir):
        """空目录 → 返回 None"""
        from pipeline.video_merger import VideoMerger, MergerConfig
        merger = VideoMerger(MergerConfig())
        result = merger.merge(
            os.path.join(temp_dir, "empty"),
            os.path.join(temp_dir, "out.mp4"),
        )
        assert result is None

    def test_merge_single_segment(self, temp_dir):
        """只有一个段 → 直接复制"""
        from pipeline.video_merger import VideoMerger, MergerConfig

        # 创建一个模拟视频段
        seg_path = os.path.join(temp_dir, "TTS_1000_2000.mp4")
        with open(seg_path, "w") as f:
            f.write("fake_video_data")

        output = os.path.join(temp_dir, "final.mp4")
        merger = VideoMerger(MergerConfig())
        result = merger.merge(temp_dir, output)

        assert result == output
        assert os.path.isfile(output)
        with open(output) as f:
            assert f.read() == "fake_video_data"

    def test_merge_moviepy_not_available(self, temp_dir):
        """moviepy 不可用时 moviepy 策略返回 None"""
        from pipeline.video_merger import VideoMerger, MergerConfig

        for start, end in [(1000, 4000), (5000, 8000)]:
            path = os.path.join(temp_dir, f"TTS_{start}_{end}.mp4")
            with open(path, "w") as f:
                f.write("dummy")

        merger = VideoMerger(MergerConfig(strategy="moviepy"))
        # 没有 moviepy 可用，应该返回 None
        result = merger.merge(temp_dir, os.path.join(temp_dir, "out.mp4"))
        assert result is None

    def test_merge_ffmpeg_not_found(self, temp_dir):
        """ffmpeg 二进制不存在 → 返回 None（非崩溃）"""
        from pipeline.video_merger import VideoMerger, MergerConfig

        for start, end in [(1000, 4000), (5000, 8000)]:
            path = os.path.join(temp_dir, f"TTS_{start}_{end}.mp4")
            with open(path, "w") as f:
                f.write("dummy")

        merger = VideoMerger(MergerConfig(), ffmpeg_exe="ffmpeg_nonexistent_xyz")
        # ffmpeg 二进制不存在时 subprocess.run 抛出 FileNotFoundError
        # VideoMerger 应捕获并返回 None
        result = merger.merge(temp_dir, os.path.join(temp_dir, "out.mp4"))
        assert result is None

    @pytest.mark.xfail(reason="ffmpeg concat needs real mp4 files, not temp placeholders")
    def test_merge_ffmpeg_success(self, temp_dir):
        """模拟 ffmpeg 成功执行"""
        from pipeline.video_merger import VideoMerger, MergerConfig

        for start, end in [(1000, 4000), (5000, 8000)]:
            path = os.path.join(temp_dir, f"TTS_{start}_{end}.mp4")
            with open(path, "w") as f:
                f.write("dummy")

        output = os.path.join(temp_dir, "out.mp4")

        merger = VideoMerger(MergerConfig())

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")

            result = merger.merge(temp_dir, output)

            assert result == output

            # 验证 ffmpeg 命令参数: concat demuxer + stream copy
            call_args = mock_run.call_args[0][0]
            assert "-f" in call_args
            assert "concat" in call_args
            assert "-safe" in call_args
            assert "0" in call_args
            assert "-i" in call_args
            assert "-c" in call_args
            assert "copy" in call_args


class TestMergerTTSConfigIntegration:
    """VideoMerger 与 TTSConfig 集成测试"""

    def test_merge_strategy_validated(self):
        """merge_strategy 合法性校验"""
        from pipeline.tts_config import TTSConfig

        cfg = TTSConfig()
        assert cfg.merge_strategy in ("ffmpeg", "moviepy")

    def test_merge_strategy_invalid(self):
        """非法 merge_strategy 抛 ValueError"""
        from pipeline.tts_config import TTSConfig

        import pytest
        with pytest.raises(ValueError, match="不支持的合并策略"):
            TTSConfig(merge_strategy="invalid")
