"""
TimingAdjuster 行为锁定测试。

mock AudioFileClip 避免 ffmpeg 依赖，纯逻辑测试。
"""
import os
from unittest.mock import MagicMock, patch

import pytest


# ── 公共 mock fixture ──────────────────────────────────────

@pytest.fixture
def mock_audio_clip():
    """mock AudioFileClip.duration，避免 ffmpeg 解析"""
    with patch("moviepy.audio.io.AudioFileClip.AudioFileClip") as mock_cls:
        mock_instance = MagicMock()
        # 默认 duration 2.0，可在测试中覆盖
        mock_instance.duration = 2.0
        mock_instance.close = MagicMock()
        mock_instance.write_audiofile = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance, mock_cls


@pytest.fixture
def mock_copy():
    """mock shutil.copy 避免实际文件操作"""
    with patch("shutil.copy") as mc:
        yield mc


@pytest.fixture
def adjuster(temp_dir):
    """标准 TimingAdjuster 实例"""
    from pipeline.tts_timing import TimingAdjuster
    return TimingAdjuster(speed_max=70, base_speed=30, trail_dir=temp_dir)


# ── 基础测试 ─────────────────────────────────────────────

class TestTimingAdjusterSimple:
    """TimingAdjuster 基础功能测试"""

    def test_import(self):
        """模块可导入"""
        from pipeline.tts_timing import TimingAdjuster, Segment, AdjustResult
        assert TimingAdjuster is not None
        assert Segment is not None
        assert AdjustResult is not None

    def test_default_params(self):
        """默认构造参数"""
        from pipeline.tts_timing import TimingAdjuster
        a = TimingAdjuster()
        assert a.speed_max == 100
        assert a.base_speed == 30

    def test_custom_params(self):
        """自定义构造参数"""
        from pipeline.tts_timing import TimingAdjuster
        a = TimingAdjuster(speed_max=50, base_speed=20)
        assert a.speed_max == 50
        assert a.base_speed == 20


# ── 场景测试（mock AudioFileClip） ──────────────────────

class TestTimingAdjusterScenarios:
    """TimingAdjuster 时序对齐场景测试"""

    def test_audio_equals_subtitle(self, adjuster, mock_audio_clip, mock_copy):
        """wav_time == tm → 不做调整"""
        mock_instance, mock_cls = mock_audio_clip
        mock_instance.duration = 2.0  # 和 tm 一致

        result = adjuster.align(
            text="测试",
            wav_time=2.0,
            start=0,
            end=2000,
            output_audio_path="dummy.wav",
            subs_next=(5000, 8000, "下一个"),
            tts_synthesize_fn=lambda t, p, r: 2.0,
        )

        over_path, adj_result = result
        assert over_path is None
        assert adj_result.adjustment_type == "none"
        assert adj_result.final_duration == 2.0

    def test_wav_time_less_than_subtitle(
        self, adjuster, mock_audio_clip, mock_copy
    ):
        """wav_time < tm → 音频重写（填充空白）"""
        mock_instance, mock_cls = mock_audio_clip
        mock_instance.duration = 1.0  # 无关，用 wav_time

        result = adjuster.align(
            text="测试",
            wav_time=1.0,
            start=0,
            end=3000,  # tm=3.0
            output_audio_path="dummy.wav",
            subs_next=(5000, 8000, "下一个"),
            tts_synthesize_fn=lambda t, p, r: 1.0,
        )

        over_path, adj_result = result
        assert over_path is None
        assert adj_result.adjustment_type == "re_write"

    def test_sub_next_time_greater_wav_time(
        self, adjuster, mock_audio_clip, mock_copy
    ):
        """sub_next_time > wav_time → 音频重写"""
        mock_instance, mock_cls = mock_audio_clip
        mock_instance.duration = 3.0

        # tm=1s, gap=5s, sub_next_time=6s, wav_time=3s → sub_next_time > wav_time
        # 进入 rewrite 分支
        result = adjuster.align(
            text="测试",
            wav_time=3.0,
            start=0,
            end=1000,
            output_audio_path="dummy.wav",
            subs_next=(6000, 9000, "下一个"),
            tts_synthesize_fn=lambda t, p, r: 3.0,
        )

        over_path, adj_result = result
        assert over_path is None
        assert adj_result.adjustment_type == "target_reached"

    def test_sub_next_time_equals_wav_time(
        self, adjuster, mock_audio_clip, mock_copy
    ):
        """sub_next_time == wav_time → target_reached"""
        mock_instance, mock_cls = mock_audio_clip
        mock_instance.duration = 3.0

        # tm=1s, gap=2s, sub_next_time=3s, wav_time=3s → 相等
        result = adjuster.align(
            text="测试",
            wav_time=3.0,
            start=0,
            end=1000,
            output_audio_path="dummy.wav",
            subs_next=(3000, 5000, "下一个"),
            tts_synthesize_fn=lambda t, p, r: 3.0,
        )

        over_path, adj_result = result
        assert over_path is None
        assert adj_result.adjustment_type == "target_reached"

    def test_speed_up_loop_success(
        self, adjuster, mock_audio_clip, mock_copy
    ):
        """音频超长 → 进入提速循环 → speed_up"""
        mock_instance, mock_cls = mock_audio_clip
        mock_instance.duration = 3.0

        call_count = [0]
        def tts_fn(text, path, rate):
            call_count[0] += 1
            durations = {1: 2.5, 2: 2.0}
            return durations.get(call_count[0], 1.5)

        # tm=1s, gap=0s, sub_next_time=1s, wav_time=3s → sub_next_time < wav_time
        # → 进入提速循环
        result = adjuster.align(
            text="测试",
            wav_time=3.0,
            start=0,
            end=1000,
            output_audio_path="dummy.wav",
            subs_next=(1000, 2000, "下一个"),
            tts_synthesize_fn=tts_fn,
        )

        over_path, adj_result = result
        assert adj_result.adjustment_type in ("speed_up", "speed_up_limited")

    def test_last_sub_wav_greater_sub_time(
        self, adjuster, mock_audio_clip, mock_copy
    ):
        """最后一条字幕，wav_time > sub_time → 进入调速"""
        mock_instance, mock_cls = mock_audio_clip
        mock_instance.duration = 3.0

        call_count = [0]
        def tts_fn(text, path, rate):
            call_count[0] += 1
            return {1: 2.5, 2: 2.0}.get(call_count[0], 1.5)

        # sub_time=1s, wav_time=3s → wav_time > sub_time → 调速
        result = adjuster.align(
            text="最后一条",
            wav_time=3.0,
            start=0,
            end=1000,
            output_audio_path="dummy.wav",
            subs_next=None,
            tts_synthesize_fn=tts_fn,
        )

        over_path, adj_result = result
        assert adj_result.adjustment_type in ("speed_up", "speed_up_limited")

    def test_extracted_method_signatures(self, adjuster):
        """验证提取的公共方法存在"""
        assert hasattr(adjuster, '_run_speed_adjust_loop')
        assert hasattr(adjuster, '_calc_initial_speed')

    def test_extracted_loop_behavior(self, adjuster, temp_dir):
        """_run_speed_adjust_loop 的返回值语义正确"""
        reached_limit, final_wav_time, rate = adjuster._run_speed_adjust_loop(
            text="测试",
            write_audio_path=os.path.join(temp_dir, "temp.wav"),
            init_speed=30,
            target_time=2.0,
            tts_synthesize_fn=lambda t, p, r: 1.5,
        )
        # 一次性合成成功（1.5s < 2.0s）
        assert reached_limit is False
        assert final_wav_time == 1.5
        assert rate == "+30%"

    def test_extracted_loop_hits_limit(self, adjuster, temp_dir):
        """_run_speed_adjust_loop 在 speed 达到极限时返回 True"""
        call_count = [0]
        # speed_max=70, 从 speed=69 开始，合成 1 次后 speed=70→极限
        reached_limit, final_wav_time, rate = adjuster._run_speed_adjust_loop(
            text="测试",
            write_audio_path=os.path.join(temp_dir, "temp.wav"),
            init_speed=69,
            target_time=1.0,  # 永远达不到
            tts_synthesize_fn=lambda t, p, r: 5.0,  # 一直比 target 大
        )
        assert reached_limit is True
        assert rate == "+69%"  # 极限时的 rate

    def test_calc_initial_speed(self, adjuster):
        """_calc_initial_speed 正确计算初始 speed"""
        speed = adjuster._calc_initial_speed(3.0, 1.0)  # wav=3s, target=1s → (3/1-1)*100=200 → clamp到70
        assert speed == 70

        speed = adjuster._calc_initial_speed(1.5, 1.0)  # (1.5/1-1)*100=50 → clamp到70
        assert speed == 50

        speed = adjuster._calc_initial_speed(1.1, 1.0)  # (1.1/1-1)*100=10 → clamp到base_speed=30
        assert speed == 30

    def test_last_sub_wav_less_sub_time(
        self, adjuster, mock_audio_clip, mock_copy
    ):
        """最后一条字幕，wav_time < sub_time → target_reached"""
        mock_instance, mock_cls = mock_audio_clip

        result = adjuster.align(
            text="最后一条",
            wav_time=0.5,
            start=0,
            end=1000,
            output_audio_path="dummy.wav",
            subs_next=None,
            tts_synthesize_fn=lambda t, p, r: 0.5,
        )

        over_path, adj_result = result
        # wav_time(0.5) < tm(1.0) → 原版走 re_write
        assert over_path is None
        assert adj_result.adjustment_type == "re_write"


class TestBinarySearch:
    """二分搜索行为锁定测试"""

    @pytest.fixture
    def binary_adjuster(self):
        """使用 binary 搜索的调整器"""
        from pipeline.tts_timing import TimingAdjuster
        return TimingAdjuster(
            speed_max=70, base_speed=30,
            trail_dir="test_trail",
            search_method="binary",
        )

    @pytest.fixture
    def mock_audio(self):
        """mock AudioFileClip（和 TestTimingAdjusterScenarios 相同的模式）"""
        with patch("moviepy.audio.io.AudioFileClip.AudioFileClip") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.close = MagicMock()
            mock_instance.write_audiofile = MagicMock()
            mock_cls.return_value = mock_instance
            yield mock_instance, mock_cls

    def test_binary_init(self, binary_adjuster):
        """init 正确设置 search_method"""
        assert binary_adjuster.search_method == "binary"
        assert binary_adjuster.speed_max == 70
        assert binary_adjuster.base_speed == 30

    def test_binary_init_speed_calc(self, binary_adjuster):
        """二分初始系数和线性一致"""
        s = binary_adjuster._calc_initial_speed(3.0, 2.0)
        # (3/2 - 1)*100 = 50, clamp [30, 70]
        assert s == 50

        s = binary_adjuster._calc_initial_speed(5.0, 2.0)
        # (5/2 - 1)*100 = 150, clamp -> 70
        assert s == 70

        s = binary_adjuster._calc_initial_speed(1.0, 2.0)
        # (1/2 - 1)*100 = -50, clamp -> 30
        assert s == 30

    def test_binary_search_min_fit_rate(self, binary_adjuster):
        """二分能找最小的 fit rate，而不是恰好 fit"""
        # 模拟 TTS 时长：+50%->2.0s, +55%->1.8s, +60%->1.4s, +65%->1.0s
        # 目标是 1.5s → 最小 fit rate 应该是 +60%（1.4<=1.5），不是 +65%"
        duration_map = {50: 2.0, 55: 1.8, 60: 1.4, 61: 1.35, 62: 1.3,
                        63: 1.25, 64: 1.2, 65: 1.0, 66: 0.95, 67: 0.9,
                        68: 0.85, 69: 0.8, 70: 0.75}
        calls = []

        def synth_fn(text, path, rate):
            speed = int(rate.strip("+%").strip())
            calls.append(speed)
            return duration_map.get(speed, 2.0)

        reached, final_wav, rate = binary_adjuster._run_speed_adjust_binary(
            "test", "dummy.wav", init_speed=50, target_time=1.5,
            tts_synthesize_fn=synth_fn,
        )

        assert not reached  # 找到 fit
        assert final_wav <= 1.5  # 确实 fit
        # 二分搜索：50→60→65→62→63... 步数远少于线性
        assert len(calls) < 12  # 线性最多 20 次，二分明显更少
        print(f"二分搜索调用次数: {len(calls)}, 最终 rate: {rate}")

    def test_binary_search_hits_limit(self, binary_adjuster):
        """所有 rate 都不够 → 返回 reached_limit"""
        def synth_fn(text, path, rate):
            return 3.0  # 永远大于 target

        reached, final_wav, rate = binary_adjuster._run_speed_adjust_binary(
            "test", "dummy.wav", init_speed=50, target_time=1.0,
            tts_synthesize_fn=synth_fn,
        )
        assert reached
        assert final_wav > 1.0

    def test_binary_already_fits_at_lower_bound(self, binary_adjuster):
        """init_speed 已经 fit → 直接返回，不二分"""
        calls = []

        def synth_fn(text, path, rate):
            speed = int(rate.strip("+%").strip())
            calls.append(speed)
            return 1.0 if speed == 30 else 2.0

        reached, final_wav, rate = binary_adjuster._run_speed_adjust_binary(
            "test", "dummy.wav", init_speed=30, target_time=2.0,
            tts_synthesize_fn=synth_fn,
        )
        assert not reached
        # 只在 lo（30）测了一次就返回
        assert len(calls) == 1

    def test_binary_search_dispatches_correctly(self, binary_adjuster):
        """_run_speed_adjust 根据 search_method 分发到 binary"""
        calls = []

        def synth_fn(text, path, rate):
            calls.append(rate)
            return 1.0

        reached, final_wav, rate = binary_adjuster._run_speed_adjust(
            "test", "dummy.wav", init_speed=30, target_time=2.0,
            tts_synthesize_fn=synth_fn,
        )
        assert not reached
        assert final_wav <= 2.0

    def test_binary_align_sub_has_next(self, binary_adjuster, mock_audio, mock_copy):
        """align() 在 binary 模式下完整走通"""
        mock_instance, mock_cls = mock_audio

        # wav_time(3.0) > tm(2.0), gap=1s → available=3s
        # available(3s) == wav_time(3s) → target_reached
        result = binary_adjuster.align(
            text="hello",
            wav_time=3.0,
            start=0,
            end=2000,
            output_audio_path="dummy.wav",
            subs_next=(3000, 5000, "next"),
            tts_synthesize_fn=lambda t, p, r: 3.0,
        )
        over_path, adj_result = result
        assert over_path is None
        assert adj_result.adjustment_type == "target_reached"

    def test_binary_align_speed_up_success(self, binary_adjuster, mock_audio, mock_copy):
        """align 走 speed_up 分支"""
        mock_instance, mock_cls = mock_audio

        # wav_time(3.0) > tm(2.0), gap=0s → available=2s
        # available(2s) < wav_time(3.0) → 需要加速
        # synth 返回 +50%→1.5s(=fit), +60%→1.0s(=fit) ... 其中 50 刚好 fit 2.0
        calls = []

        def synth_fn(text, path, rate):
            speed = int(rate.strip("+%").strip())
            calls.append(speed)
            # 模拟：rate 越高越快
            return max(1.0, 3.0 - (speed - 30) * 0.05)

        result = binary_adjuster.align(
            text="hello",
            wav_time=3.0,
            start=0,
            end=2000,
            output_audio_path="dummy.wav",
            subs_next=(2000, 5000, "next"),  # gap=0s
            tts_synthesize_fn=synth_fn,
        )
        over_path, adj_result = result
        assert over_path is None
        assert adj_result.adjustment_type == "speed_up"
