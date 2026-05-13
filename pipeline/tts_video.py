"""
视频段处理器 — VideoSegmenter

从原 `SrtTxtToAudio.slow_down_video_to_file()` 和 `current_video_to_file()` 提取。
新增 `speed_tolerance` 两级决策逻辑。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pipeline.utils import safe_replace
from typing import Optional, Tuple, Callable

from pipeline.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SpeedDecision:
    """速度调节决策结果"""
    video_speed_factor: float = 1.0
    """视频速度因子，1.0=不变，>1=加速，<1=减速"""
    tts_rate: str = "+0%"
    """TTS 语速调整"""
    use_video_speed: bool = True
    """是否通过调视频速度（True=调视频，False=调TTS语速）"""


class VideoSegmenter:
    """视频段处理器：裁剪、变速、设置音频、叠加字幕。

    功能:
    - `slow_down_video_to_file()`: 视频变速 + 背景音乐 + TTS 语音
    - `current_video_to_file()`: 视频裁剪 + 背景音乐 + TTS 语音
    - `decide_speed()`: 两级决策（speed_tolerance 参数）
    """

    def __init__(
        self,
        video_output_dir: str = "file/Video_file",
        clone_color: bool = False,
        caption: bool = True,
        voice_cloner_callback: Optional[Callable] = None,
        caption_renderer: Optional[Callable] = None,
        video_bitrate: str = "5M",
        video_codec: str = "libx264",
        video_preset: Optional[str] = "medium",
        audio_codec: str = "aac",
        speed_tolerance: float = 0.15,
        video_speed_min: float = 0.60,
        video_speed_max: float = 2.00,
        bgm_volume: float = 1.0,
    ):
        self.video_output_dir = video_output_dir
        self.clone_color = clone_color
        self.caption = caption
        self.voice_cloner_callback = voice_cloner_callback
        self.caption_renderer = caption_renderer
        self.video_bitrate = video_bitrate
        self.video_codec = video_codec
        self.video_preset = video_preset
        self.audio_codec = audio_codec
        self.speed_tolerance = speed_tolerance
        self.video_speed_min = video_speed_min
        self.video_speed_max = video_speed_max
        self.bgm_volume = bgm_volume

    def decide_speed(self, tts_duration: float, video_duration: float) -> SpeedDecision:
        """两级决策：TTS 时长与视频时长的匹配策略。"""
        if video_duration <= 0 or tts_duration <= 0:
            return SpeedDecision()
        ratio = tts_duration / video_duration
        if abs(ratio - 1.0) <= self.speed_tolerance:
            return SpeedDecision(video_speed_factor=ratio, tts_rate="+0%", use_video_speed=True)
        else:
            return SpeedDecision(video_speed_factor=1.0, tts_rate="+0%", use_video_speed=False)

    def reserve_2_num(self, duration: float) -> float:
        """保留原版的时长修正值，防止 moviepy 音频合并时出现重复音频帧。"""
        return duration - 0.06

    # ── ffmpeg 音频混合（绕过 MoviePy 音频管线，避免电音伪影） ──

    @staticmethod
    def _ffmpeg_mix_audio(
        audio_paths: list[str],
        output_path: str,
        speed_factors: Optional[list[float]] = None,
        output_duration: Optional[float] = None,
        bgm_gain_db: float = 0.0,
    ) -> None:
        """使用 ffmpeg amix 混合多轨音频，可选对每轨独立变速。

        完全绕过 MoviePy CompositeAudioClip，从根源杜绝电音伪影。

        Args:
            audio_paths: 输入音频文件路径列表
            output_path: 混合后输出 WAV 路径
            speed_factors: 每轨的 atempo 变速因子（与 audio_paths 等长），
                           None 表示所有轨不变速
            output_duration: 输出最大时长（秒），None 表示自动取最长轨
            bgm_gain_db: 背景乐轨 (track 0) 的增益 (dB)，0.0=不变
        """
        import subprocess
        import math
        from pipeline.utils import get_ffmpeg_exe
        ffmpeg = get_ffmpeg_exe()

        cmd = [ffmpeg, "-y"]
        for p in audio_paths:
            cmd.extend(["-i", p])

        # 构建 filter_complex: 对每轨变速 → 统一格式 → amix
        filters = []
        n = len(audio_paths)
        for i in range(n):
            chain = []
            # BGM 轨 (track 0) 增益
            if i == 0 and abs(bgm_gain_db) > 0.1:
                chain.append(f"volume={bgm_gain_db:+.1f}dB")
            # 变速（链式 atempo 突破 0.5-2.0 限制）
            sf = 1.0 if speed_factors is None else speed_factors[i]
            if abs(sf - 1.0) > 0.001:
                remaining = sf
                while remaining > 2.0:
                    chain.append("atempo=2.0")
                    remaining /= 2.0
                while remaining < 0.5:
                    chain.append("atempo=0.5")
                    remaining /= 0.5
                chain.append(f"atempo={remaining:.6f}")
            # 统一格式: 44100Hz mono s16
            chain.append("aformat=sample_fmts=s16:sample_rates=44100:channel_layouts=mono")
            filters.append(f"[{i}:a]{','.join(chain)}[a{i}]")

        # amix
        mix_inputs = "".join(f"[a{i}]" for i in range(n))
        filters.append(f"{mix_inputs}amix=inputs={n}:duration=longest:normalize=0[out]")

        filter_str = ";".join(filters)
        cmd.extend(["-filter_complex", filter_str, "-map", "[out]"])
        cmd.extend(["-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1"])
        if output_duration is not None:
            cmd.extend(["-t", f"{output_duration:.6f}"])
        cmd.append(output_path)

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            err = result.stderr.strip()[-500:] if result.stderr else "unknown error"
            raise RuntimeError(f"ffmpeg amix 失败: {err}")

    @staticmethod
    def _ffmpeg_fade_wav(wav_path: str, fade_duration: float = 0.01) -> None:
        """Apply short fade-in/out to a WAV file to prevent clicks at boundaries."""
        import subprocess
        from pipeline.utils import get_ffmpeg_exe
        tmp = wav_path + ".fade.wav"
        sec = f"{fade_duration:.4f}"
        result = subprocess.run(
            [get_ffmpeg_exe(), "-y", "-i", wav_path,
             "-af", f"afade=t=in:d={sec},afade=t=out:st=999999:d={sec}",
             "-acodec", "pcm_s16le", tmp],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            err = result.stderr.strip()[-200:] if result.stderr else "unknown error"
            raise RuntimeError(f"ffmpeg afade 失败: {err}")
        safe_replace(tmp, wav_path)

    def _export_audio_to_wav(self, audio_clip, temp_dir: str = None) -> str:
        """将 AudioFileClip 导出为临时 PCM WAV，返回路径。

        仅当传入 AudioFileClip 且有文件路径时优先直接返回原路径；
        否则用 MoviePy write_audiofile（单轨直出，无 CompositeAudioClip，无电音风险）。
        """
        import tempfile
        # 如果已有文件路径（AudioFileClip.filename），直接复用
        if hasattr(audio_clip, 'filename') and audio_clip.filename and os.path.isfile(audio_clip.filename):
            return audio_clip.filename
        # 否则导出到临时文件
        if temp_dir is None:
            temp_dir = tempfile.gettempdir()
        temp_path = os.path.join(temp_dir, f"_tv_export_{id(audio_clip)}.wav")
        if not os.path.isfile(temp_path):
            audio_clip.write_audiofile(temp_path, codec="pcm_s16le", logger=None)
        return temp_path

    def slow_down_video_to_file(
        self,
        current_video,
        audio_instrumental,
        tts_audio,
        tts_audio_path: str,
        start: int,
        text: str,
        text_eng: str,
        end: int,
        caption_groups: list = None,
    ):
        """视频变速处理。

        1. 视频变速 (MoviePy with_speed_scaled)
        2. ★ 音频混合改为 ffmpeg amix（绕过 MoviePy CompositeAudioClip，根治电音）
        3. 叠加字幕
        4. 写入 MP4
        """
        from moviepy import (
            VideoFileClip,
            AudioFileClip,
            CompositeAudioClip,
        )
        import tempfile

        # ── 视频调速策略 ──────────────────────────────────
        # 不变量: 视频时长 >= TTS 音频时长
        # 情况一/二: TTS 已适配 → 视频不变速 (speed_factor = 1.0)
        # 情况三: TTS 达最大语速仍超视频 → 减速视频 (speed_factor < 1)
        if tts_audio.duration <= current_video.duration:
            speed_factor = 1.0
        else:
            speed_factor = current_video.duration / tts_audio.duration
            if speed_factor < self.video_speed_min:
                speed_factor = self.video_speed_min

        # 视频变速
        slow_down_clip = current_video.with_speed_scaled(speed_factor)

        logger.info(
            f"视频调速: {current_video.duration:.2f}s -> {slow_down_clip.duration:.2f}s (speed_factor={speed_factor:.3f})"
        )
        # 移除原视频音频
        slow_down_clip = slow_down_clip.with_audio(None)

        # ── 音频混合（ffmpeg amix，根治电音） ──
        import math
        tts_dur = self.reserve_2_num(tts_audio.duration)
        mixed_wav = os.path.join(
            tempfile.gettempdir(), f"_tv_mixed_{start}_{end}.wav"
        )
        bgm_gain_db = 20.0 * math.log10(self.bgm_volume) if self.bgm_volume > 0.001 else -70.0

        if audio_instrumental is None:
            # 无背景乐：导出 TTS 音频为 WAV → 淡入淡出 → 加载
            temp_tts = os.path.join(
                tempfile.gettempdir(), f"_tv_tts_{start}_{end}.wav"
            )
            tts_audio.subclipped(0, tts_dur).write_audiofile(
                temp_tts, codec="pcm_s16le", logger=None
            )
            self._ffmpeg_fade_wav(temp_tts)
            mixed_audio = AudioFileClip(temp_tts)
            slow_down_clip = slow_down_clip.with_audio(mixed_audio)
            mixed_wav = temp_tts  # 后续统一清理
        elif self.clone_color and self.voice_cloner_callback:
            try:
                openvoice_output_dir = os.path.join(
                    os.path.dirname(self.video_output_dir), "cloned")
                clone_color_file = self.voice_cloner_callback(tts_audio_path, openvoice_output_dir)
                if clone_color_file is None or not os.path.isfile(clone_color_file):
                    raise RuntimeError("音色克隆返回空结果")
                instr_path = self._export_audio_to_wav(audio_instrumental)
                self._ffmpeg_mix_audio(
                    [instr_path, clone_color_file],
                    mixed_wav,
                    speed_factors=[speed_factor, 1.0],
                    bgm_gain_db=bgm_gain_db,
                )
            except Exception as e:
                logger.warning("音色克隆失败: %s", e)
                error_log = os.path.join(
                    os.path.dirname(self.video_output_dir), "voice_clone_error_log.txt")
                os.makedirs(os.path.dirname(error_log) or ".", exist_ok=True)
                with open(error_log, "a", encoding="utf-8") as f:
                    f.write(f"发生错误: {str(e)}\n")
                # fallback: 背景乐 + TTS 混合（跳过音色克隆）
                instr_path = self._export_audio_to_wav(audio_instrumental)
                self._ffmpeg_mix_audio(
                    [instr_path, tts_audio_path],
                    mixed_wav,
                    speed_factors=[speed_factor, 1.0],
                    output_duration=tts_dur,
                    bgm_gain_db=bgm_gain_db,
                )
        else:
            # ★ 核心修复: ffmpeg amix 替代 CompositeAudioClip
            #   背景乐变速 + TTS 混合，一步到位
            instr_path = self._export_audio_to_wav(audio_instrumental)
            self._ffmpeg_mix_audio(
                [instr_path, tts_audio_path],
                mixed_wav,
                speed_factors=[speed_factor, 1.0],
                output_duration=tts_dur,
                bgm_gain_db=bgm_gain_db,
            )

        # 淡入淡出: 消除段间拼接爆破音
        if os.path.isfile(mixed_wav) and os.path.getsize(mixed_wav) > 0:
            self._ffmpeg_fade_wav(mixed_wav)

        # 加载混合音频
        if os.path.isfile(mixed_wav) and os.path.getsize(mixed_wav) > 0:
            mixed_audio = AudioFileClip(mixed_wav)
            slow_down_clip = slow_down_clip.with_audio(mixed_audio)

        if self.caption and self.caption_renderer:
            if caption_groups and len(caption_groups) > 0:
                from moviepy import CompositeVideoClip
                # 计算字幕时间轴缩放比例，防止字幕超越视频末尾导致黑屏
                total_cap_ms = max(t1 for _, t1, _, _ in caption_groups)
                cap_scale = 1.0
                video_dur_s = slow_down_clip.duration
                if total_cap_ms / 1000.0 > video_dur_s:
                    cap_scale = video_dur_s * 1000.0 / total_cap_ms
                clips = [slow_down_clip]
                for t0, t1, t_text, s_text in caption_groups:
                    dur_sec = (t1 - t0) * cap_scale / 1000.0
                    cap_composite = self.caption_renderer(
                        slow_down_clip, dur_sec, t_text, s_text
                    )
                    # cap_composite = [video, bg, text]; strip video, keep overlays
                    if hasattr(cap_composite, 'clips') and len(cap_composite.clips) > 1:
                        for overlay in cap_composite.clips[1:]:
                            clips.append(overlay.with_start(t0 * cap_scale / 1000.0))
                    else:
                        clips.append(cap_composite.with_start(t0 * cap_scale / 1000.0))
                slow_down_clip = CompositeVideoClip(clips, size=slow_down_clip.size)
            else:
                slow_down_clip = self.caption_renderer(
                    slow_down_clip, tts_audio.duration, text, text_eng
                )

        os.makedirs(self.video_output_dir, exist_ok=True)
        output_path = os.path.join(self.video_output_dir, f"TTS_{start}_{end}.mp4")
        slow_down_clip.write_videofile(
            output_path,
            codec=self.video_codec,
            audio_codec=self.audio_codec,
            bitrate=self.video_bitrate,
            preset=self.video_preset,
            logger=None,
        )

        # 清理：关闭所有中间 clip（防 Windows ffmpeg 句柄泄漏 / 僵尸进程）
        # MoviePy 的 __del__ 在 Windows 上不可靠，必须显式 close。
        # slow_down_clip 在此函数内经过多次 with_* 变换，每次变换
        # 创建新 clip 而旧 clip 成为孤儿；关闭最终 clip 触发级联清理。
        try:
            slow_down_clip.close()
        except Exception:
            pass
        try:
            mixed_audio.close()
        except Exception:
            pass
        if os.path.isfile(mixed_wav):
            try:
                os.remove(mixed_wav)
            except OSError:
                pass

    def current_video_to_file(
        self,
        current_video,
        audio_instrumental,
        tts_audio,
        tts_audio_path: str,
        start: int,
        text: str,
        eng_sub: Tuple[int, int, str],
        end: int,
    ):
        """委托给 slow_down_video_to_file（统一用视频变速对齐）。

        speed_factor 由视频时长/TTS时长自动计算，
        sf=1.0 时等价于不变速，与原版行为一致。
        """
        start_eng, end_eng, text_eng = eng_sub
        self.slow_down_video_to_file(
            current_video, audio_instrumental, tts_audio,
            tts_audio_path, start, text, text_eng, end,
        )

    def handle_begin_end_silence(
        self, video, instrumental_path, subs, total_video_duration, extract_fn=None
    ):
        """处理视频开头和结尾的无人声片段。"""
        from moviepy import AudioFileClip
        import subprocess
        from pipeline.utils import get_ffmpeg_exe
        ffmpeg = get_ffmpeg_exe()
        count = 0

        def _get_audio(seg_start_ms: int, seg_end_ms: int):
            """获取段音频：优先 extract_fn → instrumental_path → 生成静音。"""
            if extract_fn:
                seg_path = extract_fn(seg_start_ms, seg_end_ms)
                if seg_path:
                    return AudioFileClip(seg_path)
            if instrumental_path is not None:
                return AudioFileClip(instrumental_path)
            # 无背景乐：生成段长静音
            import tempfile
            dur_s = (seg_end_ms - seg_start_ms) / 1000.0
            silence_path = os.path.join(
                tempfile.gettempdir(), f"_tv_silence_{seg_start_ms}_{seg_end_ms}.wav"
            )
            subprocess.run([
                ffmpeg, "-y", "-f", "lavfi",
                "-i", f"anullsrc=r=44100:cl=mono",
                "-t", f"{dur_s:.3f}",
                "-acodec", "pcm_s16le", silence_path,
            ], capture_output=True, check=True)
            return AudioFileClip(silence_path)

        first_start, _, _ = subs[0]
        if first_start != 0:
            logger.info("处理视频开头无人声片段")
            cm = video.subclipped(0, first_start / 1000)
            audio = _get_audio(0, first_start)
            cm = cm.with_audio(None).with_audio(audio)
            os.makedirs(self.video_output_dir, exist_ok=True)
            cm.write_videofile(
                os.path.join(self.video_output_dir, f"TTS_0_{first_start}.mp4"),
                codec=self.video_codec,
                audio_codec=self.audio_codec,
                bitrate=self.video_bitrate,
                preset=self.video_preset,
                logger=None,
            )
            audio.close()
            count += 1

        last_start, last_end, _ = subs[-1]
        if last_end != total_video_duration * 1000:
            logger.info("处理视频结尾无人声片段")
            cm = video.subclipped(last_end / 1000, total_video_duration)
            audio = _get_audio(last_end, int(total_video_duration * 1000))
            cm = cm.with_audio(None).with_audio(audio)
            os.makedirs(self.video_output_dir, exist_ok=True)
            cm.write_videofile(
                os.path.join(self.video_output_dir, f"TTS_{last_end}_{int(total_video_duration * 1000)}.mp4"),
                codec=self.video_codec,
                audio_codec=self.audio_codec,
                bitrate=self.video_bitrate,
                preset=self.video_preset,
                logger=None,
            )
            audio.close()
            count += 1

        return count
