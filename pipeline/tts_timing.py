"""
时序对齐器 — TimingAdjuster

从原 `SrtTxtToAudio.compare_audio_time()` 提取，修复 MoviePy 电音问题。

电音根因：MoviePy 内部音频管线 (s16le → float32 → s32le) 引入插值/量化伪影。
修复：所有纯 WAV 写操作绕过 MoviePy，改用 ffmpeg/shutil 直写。
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional, Tuple


@dataclass
class Segment:
    """字幕段信息"""
    start_ms: int          # 字幕开始时间（毫秒）
    end_ms: int            # 字幕结束时间（毫秒）
    text: str              # 字幕文本


@dataclass
class AdjustResult:
    """对齐结果"""
    adjustment_type: str   # "none" | "re_write" | "speed_up" | "speed_up_limited" | "target_reached"
    over_time_path: Optional[str] = None   # 超时音频路径（如果有）
    final_duration: float = 0.0            # 调整后的音频时长
    rate_used: str = "+0%"                # 最终使用的语速


class TimingAdjuster:
    """时序对齐器：将生成的 TTS 音频与字幕时间对齐。

    从原 `SrtTxtToAudio.compare_audio_time()` 原样提取，行为完全一致。
    输入/输出接口做了参数化处理，内部逻辑保持原样。
    """

    def __init__(
        self,
        speed_max: int = 100,
        base_speed: int = 30,
        trail_dir: str = "file/trail",
        audio_codec: str = "pcm_s32le",
        audio_bitrate: str = "192k",
        search_method: str = "linear",
    ):
        """
        Args:
            speed_max: TTS 最大语速（绝对值，如 70 对应 +70%）
            base_speed: TTS 基础语速（绝对值，如 30 对应 +30%）
            trail_dir: 临时文件目录
            audio_codec: 音频编码
            audio_bitrate: 音频比特率
        """
        self.speed_max = speed_max
        self.base_speed = base_speed
        self.trail_dir = trail_dir
        self.audio_codec = audio_codec
        self.audio_bitrate = audio_bitrate
        self.search_method = search_method

    # ── 公共提取方法 ──────────────────────────────────

    def _calc_initial_speed(self, wav_time: float, target_time: float) -> int:
        """计算初始语速值（依据时长比 clamped 到 [base_speed, speed_max]）。

        Args:
            wav_time: 当前音频时长（秒）
            target_time: 目标时长（秒）— sub_next_time 或 sub_time

        Returns:
            初始 speed 值，在 [base_speed, speed_max] 范围内
        """
        speed = int((wav_time / target_time - 1) * 100)
        speed = self.speed_max if speed >= self.speed_max else speed
        speed = self.base_speed if speed <= self.base_speed else speed
        return speed

    def _run_speed_adjust_loop(
        self,
        text: str,
        write_audio_path: str,
        init_speed: int,
        target_time: float,
        tts_synthesize_fn: Callable,
    ) -> Tuple[bool, float, str]:
        """运行语速调整循环。

        逐步提高 TTS 语速，直到音频时长 ≤ 目标时长 或 达到最大语速。

        Args:
            text: 字幕文本
            write_audio_path: 临时音频输出路径
            init_speed: 初始语速值（由 _calc_initial_speed 计算）
            target_time: 目标时长（秒）
            tts_synthesize_fn: TTS 合成函数 (text, path, rate) -> duration_seconds

        Returns:
            (reached_limit, final_wav_time, rate)
            - reached_limit: True 表示达到最大语速仍不够快
            - final_wav_time: 最后一次合成的音频时长
            - rate: 使用的语速字符串，如 "+30%"
        """
        speed = init_speed

        while True:
            rate = f"+{speed}%"
            speed = speed + 1
            wav_time = tts_synthesize_fn(text, write_audio_path, rate)

            if speed >= self.speed_max:
                return True, wav_time, rate

            if wav_time <= target_time:
                return False, wav_time, rate

    # ── 二分 + 线性混合搜索 ──────────────────────────────

    def _run_speed_adjust_binary(
        self,
        text: str,
        write_audio_path: str,
        init_speed: int,
        target_time: float,
        tts_synthesize_fn: Callable,
    ) -> Tuple[bool, float, str]:
        """二分搜索 + 线性微调混合策略。

        基准跳后，在 [init_speed, speed_max] 区间二分搜索最小可 fit rate。
        二分收敛后做 ±1 线性微调处理边界模糊情况。

        EdgeTTS 的 rate 上限 = speed_max，超过无效果（自动 cap）。

        Returns:
            (reached_limit, final_wav_time, rate)
            - reached_limit: True 表示达到最大语速仍不够快
            - final_wav_time: 最后一次合成的音频时长
            - rate: 使用的语速字符串，如 "+63%"
        """
        lo = init_speed
        hi = self.speed_max

        # 先测一次下限，如果能 fit 直接返回
        rate = f"+{lo}%"
        wav_time = tts_synthesize_fn(text, write_audio_path, rate)
        if wav_time <= target_time:
            return False, wav_time, rate

        # 测上限，如果不能 fit 返回极限
        rate = f"+{hi}%"
        wav_time = tts_synthesize_fn(text, write_audio_path, rate)
        if wav_time > target_time:
            return True, wav_time, rate

        # 二分搜索最小可 fit 的 rate
        while lo < hi:
            mid = (lo + hi) // 2
            rate = f"+{mid}%"
            wav_time = tts_synthesize_fn(text, write_audio_path, rate)

            if wav_time <= target_time:
                hi = mid  # 尝试更低 rate
            else:
                lo = mid + 1  # 需要更高 rate

        # 二分收敛后，微调
        rate = f"+{lo}%"
        wav_time = tts_synthesize_fn(text, write_audio_path, rate)

        # 如果 lo 不 fit（Edge TTS 非线性），就近查 3 步，再超就二分
        if wav_time > target_time:
            for back in range(lo + 1, min(lo + 4, self.speed_max + 1)):
                rate = f"+{back}%"
                wav_time = tts_synthesize_fn(text, write_audio_path, rate)
                if wav_time <= target_time:
                    return False, wav_time, rate
            # 未在邻近找到 → 剩余区间二分搜索
            remain_lo = lo + 4
            remain_hi = self.speed_max
            if remain_lo < remain_hi:
                while remain_lo < remain_hi:
                    mid = (remain_lo + remain_hi) // 2
                    rate = f"+{mid}%"
                    wav_time = tts_synthesize_fn(text, write_audio_path, rate)
                    if wav_time <= target_time:
                        remain_hi = mid
                    else:
                        remain_lo = mid + 1
                rate = f"+{remain_lo}%"
                wav_time = tts_synthesize_fn(text, write_audio_path, rate)
                if wav_time <= target_time:
                    return False, wav_time, rate
            return True, wav_time, rate

        # 如果 lo 有余量，尝试再降 1-2%
        if lo > self.base_speed:
            for lower in range(lo - 1, max(lo - 3, self.base_speed - 1), -1):
                if lower < self.base_speed:
                    break
                test_rate = f"+{lower}%"
                test_wav = tts_synthesize_fn(text, write_audio_path, test_rate)
                if test_wav <= target_time:
                    return False, test_wav, test_rate
                break

        return False, wav_time, rate

    # ── 搜索方法调度 ────────────────────────────────────

    def _run_speed_adjust(
        self,
        text: str,
        write_audio_path: str,
        init_speed: int,
        target_time: float,
        tts_synthesize_fn: Callable,
    ) -> Tuple[bool, float, str]:
        """根据 search_method 选择搜索方式。"""
        if self.search_method == "binary":
            return self._run_speed_adjust_binary(
                text, write_audio_path, init_speed, target_time, tts_synthesize_fn,
            )
        return self._run_speed_adjust_loop(
            text, write_audio_path, init_speed, target_time, tts_synthesize_fn,
        )

    # ── 核心对齐逻辑 ──────────────────────────────────

    # ── 音频写入辅助（绕过 MoviePy 电音管线） ──────────

    @staticmethod
    def _ffmpeg_copy_wav(src: str, dst: str) -> None:
        """用 ffmpeg 无损复制 WAV（acodec copy），绕过 MoviePy float32 管线。"""
        try:
            from pipeline.utils import get_ffmpeg_exe
            ffmpeg = get_ffmpeg_exe()
        except Exception:
            ffmpeg = "ffmpeg"
        subprocess.run(
            [ffmpeg, "-y", "-i", src, "-acodec", "copy", dst],
            capture_output=True, check=True,
        )

    @staticmethod
    def _ffprobe_duration(wav_path: str) -> float:
        """用 ffprobe 精确获取 WAV 时长，绕过 MoviePy AudioFileClip。"""
        try:
            from pipeline.utils import get_ffmpeg_exe
            ffprobe = get_ffmpeg_exe().replace("ffmpeg.exe", "ffprobe.exe")
        except Exception:
            ffprobe = "ffprobe"
        r = subprocess.run(
            [ffprobe, "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", wav_path],
            capture_output=True, text=True,
        )
        return float(r.stdout.strip())

    def align(
        self,
        text: str,
        wav_time: float,
        start: int,
        end: int,
        output_audio_path: str,
        subs_next: Optional[Tuple[int, int, str]],
        tts_synthesize_fn: Callable,
    ) -> Tuple[Optional[str], AdjustResult]:
        """将 TTS 音频与字幕时间对齐。

        修复: 所有 WAV 写入用 ffmpeg/shutil 绕过 MoviePy（原 write_audiofile
        走 float32→pcm_s32le 管线会引入电音伪影）。

        Returns:
            (over_audio_path, AdjustResult)
        """

        shutil_path = os.path.join(self.trail_dir, f"shutil_audio_{start}_{end}.wav")
        os.makedirs(self.trail_dir, exist_ok=True)
        shutil.copy(output_audio_path, shutil_path)

        # 用 ffprobe 测时长（绕过 MoviePy）
        tm = (end - start) / 1000

        if wav_time != tm:
            # 生成的音频时长小于字幕时长 → 直接使用
            if wav_time < tm:
                self._ffmpeg_copy_wav(shutil_path, output_audio_path)
                return None, AdjustResult("re_write", final_duration=wav_time)

            # 生成的音频时长大于字幕时长 → 需要调速
            else:
                # ── 分支 A：非最后一条字幕 ────────────────────
                if subs_next is not None:
                    subs_next_start, subs_next_end, subs_next_text = subs_next
                    gap_time = (subs_next_start - end) / 1000
                    sub_next_time = gap_time + tm

                    if sub_next_time != wav_time:
                        write_audio_path = os.path.join(
                            self.trail_dir, f"temp_audio_{start}_{end}.wav"
                        )

                        if sub_next_time > wav_time:
                            # 可以借用下一条时间
                            self._ffmpeg_copy_wav(shutil_path, output_audio_path)
                            return None, AdjustResult("target_reached", final_duration=wav_time)
                        else:
                            # sub_next_time < wav_time：需要加速
                            speed = self._calc_initial_speed(wav_time, sub_next_time)
                            reached_limit, wav_time, rate = self._run_speed_adjust(
                                text, write_audio_path, speed, sub_next_time, tts_synthesize_fn,
                            )

                            if not reached_limit:
                                print(f"{start}_{end}_语速调整完成")
                                self._ffmpeg_copy_wav(write_audio_path, output_audio_path)
                                return None, AdjustResult(
                                    "speed_up", final_duration=wav_time, rate_used=rate
                                )
                            else:
                                print("\033[0;31;40m", "语速达到极限", "\033[0m")
                                over_timr_audio_path = os.path.join(
                                    os.path.dirname(output_audio_path),
                                    f"temp_audio_{start}_{end}_overtime.wav",
                                )
                                self._ffmpeg_copy_wav(write_audio_path, over_timr_audio_path)
                                if os.path.isfile(output_audio_path):
                                    os.remove(output_audio_path)
                                return over_timr_audio_path, AdjustResult(
                                    "speed_up_limited",
                                    over_time_path=over_timr_audio_path,
                                    final_duration=wav_time,
                                    rate_used=rate,
                                )

                    else:
                        print("本条字幕start到下条字幕start的间隔时长等于合成的语音时长")
                        return None, AdjustResult("target_reached", final_duration=wav_time)

                # ── 分支 B：最后一条字幕 ────────────────────
                else:
                    print("---------开始合成最后一条TTS音频---------")
                    sub_time = (end - start) / 1000
                    write_audio_path = os.path.join(
                        self.trail_dir, f"temp_audio_{start}_{end}.wav"
                    )

                    if wav_time > sub_time:
                        speed = self._calc_initial_speed(wav_time, sub_time)
                        reached_limit, wav_time, rate = self._run_speed_adjust(
                            text, write_audio_path, speed, sub_time, tts_synthesize_fn,
                        )

                        if not reached_limit:
                            print("语速调整完成")
                            self._ffmpeg_copy_wav(write_audio_path, output_audio_path)
                            return None, AdjustResult(
                                "speed_up", final_duration=wav_time, rate_used=rate
                            )
                        else:
                            over_timr_audio_path = os.path.join(
                                os.path.dirname(output_audio_path),
                                f"temp_audio_{start}_{end}_overtime.wav",
                            )
                            self._ffmpeg_copy_wav(write_audio_path, over_timr_audio_path)
                            if os.path.isfile(output_audio_path):
                                os.remove(output_audio_path)
                            return over_timr_audio_path, AdjustResult(
                                "speed_up_limited",
                                over_time_path=over_timr_audio_path,
                                final_duration=wav_time,
                                rate_used=rate,
                            )
                    else:
                        return None, AdjustResult("target_reached", final_duration=wav_time)
        else:
            return None, AdjustResult("none", final_duration=wav_time)

        return None, AdjustResult("none", final_duration=wav_time)
