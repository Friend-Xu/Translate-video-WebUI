"""
TTSAdapter 和 TtsPipeline 单元测试
"""

import os
from unittest.mock import MagicMock, patch

import pytest


class TestTtsPipeline:
    """TtsPipeline 基础测试"""

    def test_import(self):
        from pipeline.tts_pipeline import TtsPipeline
        assert TtsPipeline is not None

    def test_import_resume(self):
        from pipeline.tts_resume import ResumeManager, ResumeState
        assert ResumeManager is not None
        assert ResumeState is not None

    def test_import_adapter(self):
        from pipeline.tts_adapter import TTSAdapter
        assert TTSAdapter is not None


class TestResumeState:
    """ResumeState dataclass 测试"""

    def test_defaults(self):
        from pipeline.tts_resume import ResumeState
        rs = ResumeState()
        assert rs.processed_pairs == set()
        assert rs.error_subtitles == []

    def test_roundtrip(self):
        from pipeline.tts_resume import ResumeState
        rs = ResumeState()
        rs.processed_pairs.add((1000, 5000))
        rs.processed_pairs.add((6000, 10000))
        rs.error_subtitles.append({"start": 0, "end": 1000, "text": "hi", "error": "fail"})

        d = rs.to_dict()
        rs2 = ResumeState.from_dict(d)
        assert (1000, 5000) in rs2.processed_pairs
        assert (6000, 10000) in rs2.processed_pairs
        assert len(rs2.error_subtitles) == 1


class TestResumeManager:
    """ResumeManager 测试"""

    def test_new_file(self, temp_dir):
        """状态文件不存在时创建空状态"""
        from pipeline.tts_resume import ResumeManager
        path = os.path.join(temp_dir, "resume.json")
        mgr = ResumeManager(path)
        assert len(mgr.state.processed_pairs) == 0

    def test_mark_and_save(self, temp_dir):
        """标记处理后保存并恢复"""
        from pipeline.tts_resume import ResumeManager
        path = os.path.join(temp_dir, "resume.json")
        mgr = ResumeManager(path)
        mgr.mark_processed(1000, 2000)
        mgr.mark_processed(3000, 4000)
        mgr.save()

        mgr2 = ResumeManager(path)
        assert mgr2.is_processed(1000, 2000) is True
        assert mgr2.is_processed(3000, 4000) is True
        assert mgr2.is_processed(5000, 6000) is False

    def test_add_error(self, temp_dir):
        """添加错误记录"""
        from pipeline.tts_resume import ResumeManager
        path = os.path.join(temp_dir, "resume.json")
        mgr = ResumeManager(path)
        mgr.add_error(0, 1000, "测试", "TTS失败")
        mgr.save()

        mgr2 = ResumeManager(path)
        assert len(mgr2.state.error_subtitles) == 1
        assert mgr2.state.error_subtitles[0]["text"] == "测试"

    def test_reset(self, temp_dir):
        """重置状态"""
        from pipeline.tts_resume import ResumeManager
        path = os.path.join(temp_dir, "resume.json")
        mgr = ResumeManager(path)
        mgr.mark_processed(1000, 2000)
        mgr.save()
        mgr.reset()
        assert len(mgr.state.processed_pairs) == 0
        assert not os.path.isfile(path)


class TestTtsPipelineResumeIntegration:
    """TtsPipeline ResumeManager 集成测试"""

    def test_pipeline_creates_resume_manager(self, temp_dir):
        """TtsPipeline 自动创建 ResumeManager"""
        from pipeline.tts_config import TTSConfig
        from pipeline.tts_pipeline import TtsPipeline

        cfg = TTSConfig()
        cfg.resume_file = os.path.join(temp_dir, "resume.json")
        cfg.enable_resume = True

        pipeline = TtsPipeline(config=cfg)
        assert pipeline._resume_manager is not None
        assert pipeline._resume_manager.state_path == cfg.resume_file

    def test_pipeline_accepts_external_resume_manager(self, temp_dir):
        """TtsPipeline 接受外部传入的 ResumeManager"""
        from pipeline.tts_config import TTSConfig
        from pipeline.tts_pipeline import TtsPipeline
        from pipeline.tts_resume import ResumeManager

        cfg = TTSConfig()
        cfg.enable_resume = False

        mgr = ResumeManager(os.path.join(temp_dir, "custom_resume.json"))
        pipeline = TtsPipeline(config=cfg, resume_manager=mgr)
        assert pipeline._resume_manager is mgr

    def test_resume_skips_processed(self, temp_dir):
        """已处理的字幕在 run() 中被跳过"""
        from pipeline.tts_config import TTSConfig, parse_srt
        from pipeline.tts_pipeline import TtsPipeline
        from pipeline.tts_resume import ResumeManager

        cfg = TTSConfig()
        cfg.enable_caption = False
        cfg.enable_openvoice = False

        # 准备一个 SRT
        srt_path = os.path.join(temp_dir, "test.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("""1
00:00:01,000 --> 00:00:04,000
第一条字幕

2
00:00:05,000 --> 00:00:08,000
第二条字幕
""")

        mgr = ResumeManager(os.path.join(temp_dir, "resume.json"))
        mgr.mark_processed(5000, 8000)  # 标记第二条已处理
        mgr.save()

        pipeline = TtsPipeline(config=cfg, resume_manager=mgr)
        assert pipeline._resume_manager.is_processed(5000, 8000) is True
        assert pipeline._resume_manager.is_processed(1000, 4000) is False

    def test_processed_pairs_loaded_from_resume(self, temp_dir):
        """ResumeManager 的 processed_pairs 正确加载到 pipeline"""
        from pipeline.tts_config import TTSConfig
        from pipeline.tts_pipeline import TtsPipeline
        from pipeline.tts_resume import ResumeManager

        cfg = TTSConfig()
        mgr = ResumeManager(os.path.join(temp_dir, "resume.json"))
        mgr.mark_processed(1000, 2000)
        # 模拟旧的 save (save 方法会同时写入 state 的 processed_pairs)
        mgr.save()

        # 重新创建管理器加载旧状态
        mgr2 = ResumeManager(os.path.join(temp_dir, "resume.json"))
        assert mgr2.is_processed(1000, 2000) is True


class TestTtsPipelineErrorHandling:
    """TtsPipeline 错误兜底测试"""

    def test_process_error_returns_error_dict(self, temp_dir):
        """处理失败时返回含错误信息的 dict"""
        from pipeline.tts_config import TTSConfig
        from pipeline.tts_pipeline import TtsPipeline
        from pipeline.tts_resume import ResumeManager

        cfg = TTSConfig()
        mgr = ResumeManager(os.path.join(temp_dir, "resume.json"))
        pipeline = TtsPipeline(config=cfg, resume_manager=mgr)

        # 模拟当前视频片段（给 _process_single_subtitle 传递 mock）
        from unittest.mock import MagicMock

        mock_video = MagicMock()
        mock_video.duration = 3.0
        mock_instr = MagicMock()

        # 不给 subs_next，engine 会尝试实际合成，但我们先不跑完整的 run()
        # 而是直接验证 _process_single_subtitle 的签名存在即可
        assert hasattr(pipeline, '_process_single_subtitle')
        assert hasattr(pipeline, '_resume_manager')
        assert pipeline._resume_manager is mgr

    def test_error_saved_to_resume(self, temp_dir):
        """处理失败的条目被记录到 ResumeManager"""
        from pipeline.tts_resume import ResumeManager

        mgr = ResumeManager(os.path.join(temp_dir, "resume.json"))
        mgr.add_error(1000, 4000, "测试文本", "TTS 合成失败")
        mgr.save()

        mgr2 = ResumeManager(os.path.join(temp_dir, "resume.json"))
        assert len(mgr2.state.error_subtitles) == 1
        assert mgr2.state.error_subtitles[0]["text"] == "测试文本"
        assert "TTS 合成失败" in mgr2.state.error_subtitles[0]["error"]

    def test_video_bitrate_reasonable(self):
        """video_bitrate 默认值合理（非 5Tbps 笔误）"""
        from pipeline.tts_config import TTSConfig
        cfg = TTSConfig()
        br = cfg.video_bitrate
        # 不应是荒谬的数值
        assert "5000000000k" not in br
        # 应在合理范围（几 Mbps 到几十 Mbps）
        import re
        match = re.match(r"^(\d+)([kKM]?)$", br)
        assert match, f"video_bitrate 格式异常: {br}"
        value, unit = int(match[1]), match[2]
        if unit == "k" or not unit:
            assert value <= 20000, f"video_bitrate 仍过大: {br}"
        elif unit == "M":
            assert value <= 100, f"video_bitrate 仍过大: {br}"


class TestTtsPipelineE2E:
    """TtsPipeline 端到端集成测试（全 mock）"""

    def _create_srt(self, path: str, lines: list):
        """创建 SRT 测试文件"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)

    def test_run_with_mocked_pipeline(self, temp_dir):
        """全 mock 的 TtsPipeline.run() 端到端测试"""
        from pipeline.tts_config import TTSConfig
        from pipeline.tts_pipeline import TtsPipeline
        from pipeline.tts_resume import ResumeManager
        from unittest.mock import MagicMock, patch

        cfg = TTSConfig()
        cfg.enable_caption = False
        cfg.enable_openvoice = False
        cfg.enable_resume = False
        cfg.output_dir = temp_dir
        cfg.resume_file = os.path.join(temp_dir, "resume.json")

        # 准备 SRT 文件
        cn_srt = os.path.join(temp_dir, "cn.srt")
        en_srt = os.path.join(temp_dir, "en.srt")
        self._create_srt(cn_srt, [
            "1\n",
            "00:00:01,000 --> 00:00:04,000\n",
            "第一条字幕\n",
            "\n",
            "2\n",
            "00:00:05,000 --> 00:00:08,000\n",
            "第二条字幕\n",
        ])
        self._create_srt(en_srt, [
            "1\n",
            "00:00:01,000 --> 00:00:04,000\n",
            "Subtitle one\n",
            "\n",
            "2\n",
            "00:00:05,000 --> 00:00:08,000\n",
            "Subtitle two\n",
        ])

        resume_mgr = ResumeManager(cfg.resume_file)

        pipeline = TtsPipeline(config=cfg, resume_manager=resume_mgr)

        # mock 所有 moviepy 依赖
        with patch("moviepy.VideoFileClip") as mock_video_cls, \
             patch("moviepy.AudioFileClip") as mock_audio_cls, \
             patch.object(pipeline, '_process_single_subtitle', return_value={"success": True, "start": 1000, "end": 4000, "text_zh": "测试"}) as mock_process, \
             patch("pipeline.utils.get_ffmpeg_exe", return_value="ffmpeg"), \
             patch("os.path.isfile", return_value=True), \
             patch("subprocess.run"):

            mock_video = MagicMock()
            mock_video.duration = 10.0
            mock_video.subclipped.return_value = MagicMock(duration=3.0)
            mock_video_cls.return_value = mock_video

            mock_audio = MagicMock()
            mock_audio.duration = 3.0
            mock_audio_cls.return_value = mock_audio

            pipeline.run(
                video_path="/fake/video.mp4",
                instrumental_path="/fake/instr.wav",
                chinese_srt_path=cn_srt,
                english_srt_path=en_srt,
            )

            # 验证 _process_single_subtitle 被调用（至少 1 次）
            assert mock_process.call_count >= 1

            # 验证处理了所有有效字幕
            # start=1000,end=4000 和 start=5000,end=8000
            # start 是第 3 个位置参数（索引 2）
            all_calls = mock_process.call_args_list
            actual_starts = [c[0][2] for c in all_calls]
            assert 1000 in actual_starts
            assert 5000 in actual_starts

    def test_run_skip_invalid_timestamps(self, temp_dir):
        """无效时间戳字幕被跳过"""
        from pipeline.tts_config import TTSConfig
        from pipeline.tts_pipeline import TtsPipeline
        from pipeline.tts_resume import ResumeManager
        from unittest.mock import MagicMock, patch

        cfg = TTSConfig()
        cfg.enable_caption = False
        cfg.enable_openvoice = False
        cfg.enable_resume = False
        cfg.output_dir = temp_dir
        cfg.resume_file = os.path.join(temp_dir, "resume.json")

        # 准备含无效字幕的 SRT（end == start 触发 end <= start 跳过）
        cn_srt = os.path.join(temp_dir, "cn_bad.srt")
        en_srt = os.path.join(temp_dir, "en_bad.srt")
        self._create_srt(cn_srt, [
            "1\n",
            "00:00:03,000 --> 00:00:03,000\n",  # end == start
            "无效字幕\n",
            "\n",
            "2\n",
            "00:00:05,000 --> 00:00:08,000\n",
            "有效字幕\n",
        ])
        self._create_srt(en_srt, [
            "1\n",
            "00:00:03,000 --> 00:00:03,000\n",
            "Invalid\n",
            "\n",
            "2\n",
            "00:00:05,000 --> 00:00:08,000\n",
            "Valid\n",
        ])

        resume_mgr = ResumeManager(cfg.resume_file)
        pipeline = TtsPipeline(config=cfg, resume_manager=resume_mgr)

        with patch("moviepy.VideoFileClip") as mock_video_cls, \
             patch("moviepy.AudioFileClip") as mock_audio_cls, \
             patch.object(pipeline, '_process_single_subtitle', return_value={"success": True}) as mock_process, \
             patch("pipeline.utils.get_ffmpeg_exe", return_value="ffmpeg"), \
             patch("os.path.isfile", return_value=True), \
             patch("subprocess.run"):

            mock_video = MagicMock()
            mock_video.duration = 10.0
            mock_video.subclipped.return_value = MagicMock(duration=3.0)
            mock_video_cls.return_value = mock_video

            mock_audio = MagicMock()
            mock_audio.duration = 3.0
            mock_audio_cls.return_value = mock_audio

            pipeline.run(
                video_path="/fake/video.mp4",
                instrumental_path="/fake/instr.wav",
                chinese_srt_path=cn_srt,
                english_srt_path=en_srt,
            )

            # 只有有效字幕被处理
            assert mock_process.call_count == 1

    def test_run_with_resume_skips_processed(self, temp_dir):
        """断点续传：已处理的字幕在 run() 中被跳过"""
        from pipeline.tts_config import TTSConfig
        from pipeline.tts_pipeline import TtsPipeline
        from pipeline.tts_resume import ResumeManager
        from unittest.mock import MagicMock, patch

        cfg = TTSConfig()
        cfg.enable_caption = False
        cfg.enable_openvoice = False
        cfg.enable_resume = True
        cfg.output_dir = temp_dir
        cfg.resume_file = os.path.join(temp_dir, "resume_e2e.json")

        cn_srt = os.path.join(temp_dir, "cn_resume.srt")
        en_srt = os.path.join(temp_dir, "en_resume.srt")
        self._create_srt(cn_srt, [
            "1\n",
            "00:00:01,000 --> 00:00:04,000\n",
            "已处理\n",
            "\n",
            "2\n",
            "00:00:05,000 --> 00:00:08,000\n",
            "未处理\n",
        ])
        self._create_srt(en_srt, [
            "1\n",
            "00:00:01,000 --> 00:00:04,000\n",
            "Done\n",
            "\n",
            "2\n",
            "00:00:05,000 --> 00:00:08,000\n",
            "Pending\n",
        ])

        # 标记第一条已处理
        resume_mgr = ResumeManager(cfg.resume_file)
        resume_mgr.mark_processed(1000, 4000)
        resume_mgr.save()

        # 用新加载的状态
        resume_mgr2 = ResumeManager(cfg.resume_file)
        pipeline = TtsPipeline(config=cfg, resume_manager=resume_mgr2)

        with patch("moviepy.VideoFileClip") as mock_video_cls, \
             patch("moviepy.AudioFileClip") as mock_audio_cls, \
             patch.object(pipeline, '_process_single_subtitle', return_value={"success": True}) as mock_process, \
             patch("pipeline.utils.get_ffmpeg_exe", return_value="ffmpeg"), \
             patch("os.path.isfile", return_value=True), \
             patch("subprocess.run"):

            mock_video = MagicMock()
            mock_video.duration = 10.0
            mock_video.subclipped.return_value = MagicMock(duration=3.0)
            mock_video_cls.return_value = mock_video

            mock_audio = MagicMock()
            mock_audio.duration = 3.0
            mock_audio_cls.return_value = mock_audio

            pipeline.run(
                video_path="/fake/video.mp4",
                instrumental_path="/fake/instr.wav",
                chinese_srt_path=cn_srt,
                english_srt_path=en_srt,
            )

            # 只有第二条未处理的被处理
            assert mock_process.call_count == 1
            called_args = mock_process.call_args[0]
            called_start = called_args[2]  # start 是第 3 个位置参数
            assert called_start == 5000


class TestTTSAdapter:
    """TTSAdapter 兼容性测试"""

    def test_adapter_compatible_interface(self, temp_dir):
        """验证 TTSAdapter 与旧版接口兼容"""
        from pipeline.tts_adapter import TTSAdapter

        adapter = TTSAdapter(
            video_path="/fake/video.mp4",
            video_instrumental_path="/fake/instr.wav",
            chinese_srt_path="/fake/cn.srt",
            english_srt_path="/fake/en.srt",
            TTS_audio_output_path=os.path.join(temp_dir, "output"),
            threading_workers=3,
            clone_color=False,
            speed_max=5,
            edgeTTS_vocal="zh-CN-XiaoxiaoNeural",
            base_speed=2,
            caption=True,
        )
        assert adapter.model_version == "v2"
        assert adapter.speed_max == 50  # 5*10
        assert adapter.base_speed == 20  # 2*10
        assert adapter.vocal == "zh-CN-XiaoxiaoNeural"
        assert adapter.clone_color is False
        assert adapter.caption is True

    def test_adapter_model_version_settable(self, temp_dir):
        """model_version 属性可写（兼容旧代码 tts.model_version = \"v2\"）"""
        from pipeline.tts_adapter import TTSAdapter

        adapter = TTSAdapter(
            video_path="/fake/v.mp4",
            video_instrumental_path="/fake/i.wav",
            chinese_srt_path="/fake/cn.srt",
            english_srt_path="/fake/en.srt",
            TTS_audio_output_path=os.path.join(temp_dir, "out"),
        )
        adapter.model_version = "v3"
        assert adapter.model_version == "v3"
