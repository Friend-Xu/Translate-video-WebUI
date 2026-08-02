"""
视频段容器时长契约测试 — TTS 音频长于视频时, 视频轨尾帧定格扩展

Bug 背景 (2026-08-03 修复): TTS 音频长于 (减速钳制后) 视频段时, moviepy
write_videofile 只写视频真实帧, 容器时长却取音频轨 → 段容器时长虚高;
ffmpeg concat 后视频轨总和 < 音频轨总和, 成品容器时长错误 (dubbed 24min vs 源 3min)。
修复: 视频轨用尾帧定格扩展到音频时长, 两轨等长。
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import pytest
import imageio_ffmpeg
from moviepy import AudioFileClip, ColorClip, VideoFileClip

from pipeline.tts_video import VideoSegmenter
from pipeline.video_merger import VideoMerger, MergerConfig


def _ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def _make_wav(path: str, duration: float) -> None:
    subprocess.run(
        [_ffmpeg(), "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration:.3f}",
         "-ar", "44100", "-ac", "1", path],
        capture_output=True, check=True,
    )


def _probe_duration(path: str) -> float:
    r = subprocess.run([_ffmpeg(), "-i", path], capture_output=True, text=True)
    for line in (r.stderr or "").splitlines():
        if "Duration" in line:
            h, m, s = line.strip().split("Duration: ")[-1].split(",")[0].split(":")
            return float(h) * 3600 + float(m) * 60 + float(s)
    raise AssertionError(f"no duration for {path}")


def _probe_video_frames(path: str) -> int:
    r = subprocess.run(
        [_ffmpeg(), "-i", path, "-map", "0:v", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    frames = [l for l in (r.stderr or "").splitlines() if "frame=" in l]
    assert frames, f"no frame stats for {path}"
    return int(frames[-1].split("frame=")[1].split()[0])


def _source_video(tmp_path, duration: float = 10.0):
    """内存合成源视频 (30fps 纯色) — 测试只关心时长/帧数语义"""
    return ColorClip(size=(320, 240), color=(10, 20, 30), duration=duration).with_fps(30)


class TestSegmentContainerDuration:
    """段文件容器时长 = 视频轨时长 (修复核心)"""

    def test_tts_longer_than_video_freezes_tail(self, tmp_path):
        """TTS 音频 (4.5s) > 视频段 (1.5s, 减速钳制 0.6 后 2.5s):
        段容器时长 = 音频时长, 且视频轨帧数覆盖整个时长 (尾帧定格)"""
        wav = str(tmp_path / "tts.wav")
        _make_wav(wav, 4.5)
        video = _source_video(tmp_path)
        clip = video.subclipped(0, 1.5)
        seg = VideoSegmenter(video_output_dir=str(tmp_path / "segs"),
                             caption=False, video_codec="libx264", video_preset="ultrafast")

        # 复刻调用路径 (start/end 决定文件名)
        tts = AudioFileClip(wav)
        seg.slow_down_video_to_file(
            current_video=clip, audio_instrumental=None,
            tts_audio=tts, tts_audio_path=wav,
            start=0, text="x", text_eng="", end=1500,
        )
        tts.close()
        clip.close()
        video.close()

        out = str(tmp_path / "segs" / "TTS_0_1500.mp4")
        assert os.path.isfile(out)
        dur = _probe_duration(out)
        frames = _probe_video_frames(out)
        # 容器时长 = 音频时长 (4.5 - 0.06 reserve)
        assert abs(dur - 4.44) < 0.1, f"container duration {dur}"
        # 视频轨必须覆盖整个容器时长 (尾帧定格), 而非只有 2.5s 真实帧
        assert abs(frames - round(4.44 * 30)) <= 2, f"frames {frames} (video track must cover audio)"

    def test_tts_shorter_than_video_untouched(self, tmp_path):
        """TTS 音频 (2s) < 视频段 (4s): 容器时长 = 视频时长, 不扩展"""
        wav = str(tmp_path / "tts.wav")
        _make_wav(wav, 2.0)
        video = _source_video(tmp_path)
        clip = video.subclipped(0, 4.0)
        seg = VideoSegmenter(video_output_dir=str(tmp_path / "segs"),
                             caption=False, video_codec="libx264", video_preset="ultrafast")
        tts = AudioFileClip(wav)
        seg.slow_down_video_to_file(
            current_video=clip, audio_instrumental=None,
            tts_audio=tts, tts_audio_path=wav,
            start=0, text="x", text_eng="", end=4000,
        )
        tts.close()
        clip.close()
        video.close()

        dur = _probe_duration(str(tmp_path / "segs" / "TTS_0_4000.mp4"))
        assert abs(dur - 4.0) < 0.1, f"container duration {dur}"


class TestMergeContainerDuration:
    """合并后成品容器时长 = 各段时长之和, 视频轨覆盖容器"""

    def test_concat_sum_correct(self, tmp_path):
        seg_dir = tmp_path / "segs"
        seg_dir.mkdir(exist_ok=True)
        video = _source_video(tmp_path, duration=10.0)
        seg = VideoSegmenter(video_output_dir=str(seg_dir),
                             caption=False, video_codec="libx264", video_preset="ultrafast")

        # 段1: 音频长于视频 (扩展段) — 事件 0-1.5s, TTS 4.5s
        wav1 = str(tmp_path / "tts1.wav")
        _make_wav(wav1, 4.5)
        tts1 = AudioFileClip(wav1)
        seg.slow_down_video_to_file(
            current_video=video.subclipped(0, 1.5), audio_instrumental=None,
            tts_audio=tts1, tts_audio_path=wav1,
            start=0, text="x", text_eng="", end=1500,
        )
        tts1.close()

        # 段2: 音频短于视频 (正常段) — 事件 1.5-5.5s, TTS 2s
        wav2 = str(tmp_path / "tts2.wav")
        _make_wav(wav2, 2.0)
        tts2 = AudioFileClip(wav2)
        seg.slow_down_video_to_file(
            current_video=video.subclipped(1.5, 5.5), audio_instrumental=None,
            tts_audio=tts2, tts_audio_path=wav2,
            start=1500, text="x", text_eng="", end=5500,
        )
        tts2.close()
        video.close()

        seg1 = str(seg_dir / "TTS_0_1500.mp4")
        seg2 = str(seg_dir / "TTS_1500_5500.mp4")
        d1, d2 = _probe_duration(seg1), _probe_duration(seg2)
        f1, f2 = _probe_video_frames(seg1), _probe_video_frames(seg2)
        assert abs(d1 - 4.44) < 0.1  # 扩展段: 容器 = 音频
        assert abs(d2 - 4.0) < 0.1   # 正常段: 容器 = 视频

        final = str(tmp_path / "dubbed.mp4")
        result = VideoMerger(MergerConfig(strategy="ffmpeg")).merge(str(seg_dir), final)
        assert result == final

        fd = _probe_duration(final)
        fframes = _probe_video_frames(final)
        # 容器时长 = 段时长之和 (修前: 虚高至音频总和而视频轨不足)
        assert abs(fd - (d1 + d2)) < 0.15, f"final duration {fd}"
        # 视频轨总和覆盖容器时长 (修前: 视频轨少 1.94s, 结尾定格)
        assert abs(fframes - (f1 + f2)) <= 3, f"final frames {fframes} vs {f1 + f2}"
