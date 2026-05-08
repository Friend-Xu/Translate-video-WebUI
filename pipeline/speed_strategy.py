"""
速度策略模块 — SpeedStrategy Protocol

提供两种速度控制策略：
- PerSegmentStrategy（逐段精细）：基于原版 compare_audio_time 算法，每段独立调速
- GlobalStrategy（全局统一）：预扫所有 TTS，算全局 rate 后一次生成

两种策略都遵循同一套决策树：
  ① TTS 能自然 fit？ → 视频不动
  ② rate 调整能 fit？ → API rate 重生成 TTS，视频不动
  ③ rate 打满还超 → 极限 rate + 视频调速兜底
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple, Protocol, Dict, Any

from pipeline.logger import get_logger

logger = get_logger(__name__)


# ── 数据模型 ─────────────────────────────────────────


@dataclass
class SubtitleInfo:
    """单条字幕信息"""
    index: int             # 序号
    start_ms: int          # 开始毫秒
    end_ms: int            # 结束毫秒
    text_cn: str           # 中文字幕
    text_en: str           # 英文字幕


@dataclass
class SubResult:
    """单条字幕处理结果"""
    index: int
    start_ms: int
    end_ms: int
    success: bool
    wav_time: float = 0.0
    rate_used: str = "+0%"
    adjustment_type: str = "none"   # none | rate | video_speed | limit_video
    error: Optional[str] = None


@dataclass
class ProcessResult:
    """整轮处理结果"""
    results: List[SubResult]
    total_success: int = 0
    total_error: int = 0
    global_rate_used: Optional[str] = None


# ── Protocol ──────────────────────────────────────────


class SpeedStrategy(Protocol):
    """速度策略协议"""

    def process(
        self,
        subs_cn: List[Tuple[int, int, str]],
        subs_en: List[Tuple[int, int, str]],
        synth_fn: Callable,
        video_clip,
        instrumental_audio,
        video_segmenter,
        resume_manager,
        progress_callback: Optional[Callable] = None,
    ) -> ProcessResult:
        """执行速度策略。

        Args:
            subs_cn: 中文字幕列表 [(start_ms, end_ms, text), ...]
            subs_en: 英文字幕列表
            synth_fn: TTS 合成函数 (text, path, rate) -> duration_s
            video_clip: 原始视频 (VideoFileClip)
            instrumental_audio: 伴奏音频路径
            video_segmenter: VideoSegmenter 实例
            resume_manager: ResumeManager 实例
            progress_callback: 进度回调 pbar(index, total, result)

        Returns:
            ProcessResult
        """
        ...


# ── 上下文 ────────────────────────────────────────────


@dataclass
class StrategyContext:
    """策略运行上下文（注入依赖）"""
    trail_dir: str = "file/trail"
    audio_output_dir: str = "file/EdgeTTS_Audio_file"
    video_output_dir: str = "file/Video_file"
    instrument_dir: str = "file"
    audio_codec: str = "pcm_s32le"
    audio_bitrate: str = "192k"
    video_bitrate: str = "5000000k"
    speed_max: int = 70           # TTS 最大语速 (%)
    base_speed: int = 30          # TTS 基础语速 (%)
    video_speed_min: float = 0.75
    video_speed_max: float = 1.25
    search_method: str = "linear" # "linear" | "binary"


# ── PerSegment 策略（基于原版算法） ───────────────────


class PerSegmentStrategy:
    """逐段精细调速策略。

    对每条字幕独立执行原版 compare_audio_time 决策树：
      初始系数 = int((wav_time/tm-1)*100) → clamp [base_speed, speed_max]
      → loop fit → 成功则视频不动
      → 极限则视频调速兜底
    """

    def __init__(self, ctx: StrategyContext):
        self.ctx = ctx

    def process(
        self,
        subs_cn: List[Tuple[int, int, str]],
        subs_en: List[Tuple[int, int, str]],
        synth_fn: Callable,
        video_clip,
        instrumental_path: str | None,
        video_segmenter,
        resume_manager,
        progress_callback: Optional[Callable] = None,
    ) -> ProcessResult:
        from moviepy import AudioFileClip, VideoFileClip
        from pipeline.tts_timing import TimingAdjuster

        # 延时导入避免循环引用
        timing = TimingAdjuster(
            speed_max=self.ctx.speed_max,
            base_speed=self.ctx.base_speed,
            trail_dir=self.ctx.trail_dir,
            audio_codec=self.ctx.audio_codec,
            audio_bitrate=self.ctx.audio_bitrate,
            search_method=self.ctx.search_method,
        )

        def _extract_segment(seg_start_ms: int, seg_end_ms: int) -> str | None:
            """提取一段独立的伴奏片段。

            instrumental_path 为 None 时返回 None。
            """
            if instrumental_path is None:
                return None
            from pipeline.utils import get_ffmpeg_exe
            import subprocess
            seg_dir = os.path.join(self.ctx.trail_dir, "audio_segments")
            os.makedirs(seg_dir, exist_ok=True)
            seg_path = os.path.join(seg_dir, f"instr_{seg_start_ms}_{seg_end_ms}.wav")
            if not os.path.isfile(seg_path):
                idx = 0
                while os.path.isfile(seg_path):
                    idx += 1
                    seg_path = os.path.join(seg_dir, f"instr_{seg_start_ms}_{seg_end_ms}_{idx}.wav")
                subprocess.run(
                    [get_ffmpeg_exe(), "-y", "-i", instrumental_path,
                     "-ss", str(seg_start_ms / 1000),
                     "-to", str(seg_end_ms / 1000),
                     "-acodec", "pcm_s16le", seg_path],
                    capture_output=True, check=True,
                )
            return seg_path

        results: List[SubResult] = []
        total = len(subs_cn)
        processed = 0
        skipped = 0
        errors = 0

        for i, (start, end, text_cn) in enumerate(subs_cn):
            try:
                # 断点续传
                if resume_manager.is_processed(start, end):
                    skipped += 1
                    if progress_callback:
                        progress_callback(i, total, {"ok": processed, "err": errors, "skip": skipped})
                    continue

                # 无效时间戳检查
                if end <= start or start < 0:
                    skipped += 1
                    if progress_callback:
                        progress_callback(i, total, {"ok": processed, "err": errors, "skip": skipped})
                    continue

                text_en = subs_en[i][2] if i < len(subs_en) else ""
                subs_next = subs_cn[i + 1] if i + 1 < len(subs_cn) else None

                # 裁剪视频段
                if subs_next:
                    seg_end_ms = subs_next[0]  # 用到下条字幕开始
                else:
                    seg_end_ms = end
                current_video = video_clip.subclipped(start / 1000, seg_end_ms / 1000)

                # 伴奏片段
                instr_seg_path = _extract_segment(start, seg_end_ms)
                instrumental_segment = AudioFileClip(instr_seg_path) if instr_seg_path else None

                # 1. 生成 base_speed TTS
                output_audio_path = os.path.join(
                    self.ctx.audio_output_dir, f"audio_{start}_{end}.wav"
                )
                os.makedirs(os.path.dirname(output_audio_path), exist_ok=True)
                wav_time = synth_fn(text_cn, output_audio_path, f"+{self.ctx.base_speed}%")

                # 2. 时间对齐（原版 compare_audio_time 算法）
                over_path, adj_result = timing.align(
                    text=text_cn,
                    wav_time=wav_time,
                    start=start,
                    end=end,
                    output_audio_path=output_audio_path,
                    subs_next=subs_next,
                    tts_synthesize_fn=synth_fn,
                )

                # 3. 加载最终 TTS 音频
                load_path = over_path if over_path else output_audio_path
                tts_audio = AudioFileClip(load_path)

                # 4. 组装视频段
                if over_path:
                    # rate 打满，视频调速兜底
                    video_segmenter.slow_down_video_to_file(
                        current_video, instrumental_segment, tts_audio,
                        load_path, start, text_cn, text_en, seg_end_ms,
                    )
                    adj_type = "limit_video"
                else:
                    # rate 调好或自然 fit，视频不动
                    video_segmenter.current_video_to_file(
                        current_video, instrumental_segment, tts_audio,
                        load_path, start, text_cn,
                        (start, seg_end_ms, text_en), seg_end_ms,
                    )
                    adj_type = "rate" if adj_result.adjustment_type in ("speed_up",) else "none"

                tts_audio.close()
                if instrumental_segment is not None:
                    instrumental_segment.close()
                current_video.close()

                # 标记完成
                resume_manager.mark_processed(start, end)
                resume_manager.save()

                results.append(SubResult(
                    index=i, start_ms=start, end_ms=end,
                    success=True, wav_time=wav_time,
                    rate_used=adj_result.rate_used,
                    adjustment_type=adj_type,
                ))
                processed += 1

            except Exception as e:
                results.append(SubResult(
                    index=i, start_ms=start, end_ms=end,
                    success=False, error=str(e),
                ))
                errors += 1
            finally:
                if progress_callback:
                    progress_callback(i, total, {"ok": processed, "err": errors, "skip": skipped})

        return ProcessResult(
            results=results,
            total_success=processed,
            total_error=errors,
        )


# ── Global 策略（全局统一调速） ───────────────────────


class GlobalStrategy:
    """全局统一调速策略。

    两步走：
      预扫：所有字幕生成 base_speed TTS，记录时长
      算全局 rate = Σwav_time / Σavailable_time
      统一 rate 一次重生成所有 TTS（或 max_rate + 整体视频调速）
    """

    def __init__(self, ctx: StrategyContext):
        self.ctx = ctx

    def process(
        self,
        subs_cn: List[Tuple[int, int, str]],
        subs_en: List[Tuple[int, int, str]],
        synth_fn: Callable,
        video_clip,
        instrumental_path: str | None,
        video_segmenter,
        resume_manager,
        progress_callback: Optional[Callable] = None,
    ) -> ProcessResult:
        from moviepy import AudioFileClip, VideoFileClip
        from pipeline.utils import get_ffmpeg_exe

        total = len(subs_cn)
        results: List[SubResult] = []
        ffmpeg = get_ffmpeg_exe()

        # ── 第一步：预扫 ──────────────────────────────
        pre_scan: List[dict] = []
        total_wav = 0.0
        total_avail_ms = 0

        logger.info("预扫: 测量各段 TTS 时长...")
        for i, (start, end, text_cn) in enumerate(subs_cn):
            text_en = subs_en[i][2] if i < len(subs_en) else ""
            subs_next = subs_cn[i + 1] if i + 1 < len(subs_cn) else None

            if subs_next:
                avail_ms = subs_next[0] - start  # start → next_start
            else:
                avail_ms = end - start

            pre_path = os.path.join(self.ctx.trail_dir, f"pre_audio_{start}_{end}.wav")
            os.makedirs(self.ctx.trail_dir, exist_ok=True)
            wav_time = synth_fn(text_cn, pre_path, f"+{self.ctx.base_speed}%")

            pre_scan.append({
                "start": start, "end": end, "text_cn": text_cn,
                "text_en": text_en, "wav_time": wav_time,
                "avail_ms": avail_ms, "base_path": pre_path,
                "subs_next": subs_next,
            })
            total_wav += wav_time
            total_avail_ms += avail_ms

        # ── 第二步：计算全局 rate ──────────────────────
        total_avail_s = total_avail_ms / 1000.0
        global_ratio = total_wav / total_avail_s if total_avail_s > 0 else 1.0

        # 计算目标 rate
        target_rate = int((global_ratio - 1) * 100)
        target_rate = max(self.ctx.base_speed, min(target_rate, self.ctx.speed_max))
        global_rate_str = f"+{target_rate}%"

        # 检查是否需要视频调速
        needs_video_adjust = target_rate >= self.ctx.speed_max and global_ratio > (self.ctx.speed_max / 100 + 1)

        logger.info(f"ΣTTS={total_wav:.1f}s, Σavail={total_avail_s:.1f}s")
        logger.info(f"全局 ratio={global_ratio:.3f}, rate={global_rate_str}")
        if needs_video_adjust:
            # rate 打满还不够 → 需要视频调速
            remain_factor = total_wav / (total_avail_s * (self.ctx.speed_max / 100 + 1))
            remain_factor = max(self.ctx.video_speed_min,
                                min(remain_factor, self.ctx.video_speed_max))
            logger.warning(f"rate 打满, 视频调速因子={remain_factor:.3f}")

        # ── 第三步：统一生成 TTS ───────────────────────
        processed = 0
        skipped = 0
        errors = 0

        logger.info(f"统一生成 TTS (rate={global_rate_str})...")

        def _extract_segment(seg_start_ms: int, seg_end_ms: int) -> str | None:
            if instrumental_path is None:
                return None
            seg_dir = os.path.join(self.ctx.trail_dir, "audio_segments")
            os.makedirs(seg_dir, exist_ok=True)
            seg_path = os.path.join(seg_dir, f"instr_{seg_start_ms}_{seg_end_ms}.wav")
            if not os.path.isfile(seg_path):
                import subprocess
                subprocess.run(
                    [ffmpeg, "-y", "-i", instrumental_path,
                     "-ss", str(seg_start_ms / 1000),
                     "-to", str(seg_end_ms / 1000),
                     "-acodec", "pcm_s16le", seg_path],
                    capture_output=True, check=True,
                )
            return seg_path

        for i, scan in enumerate(pre_scan):
            try:
                start, end = scan["start"], scan["end"]
                text_cn, text_en = scan["text_cn"], scan["text_en"]
                subs_next = scan["subs_next"]

                if resume_manager.is_processed(start, end):
                    skipped += 1
                    if progress_callback:
                        progress_callback(i, total, {"ok": processed, "err": errors, "skip": skipped})
                    continue

                # 统一 rate 生成 TTS
                output_path = os.path.join(
                    self.ctx.audio_output_dir, f"audio_{start}_{end}.wav"
                )
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                wav_time = synth_fn(text_cn, output_path, global_rate_str)

                # 决定视频段区间
                if subs_next:
                    seg_end = subs_next[0]
                else:
                    seg_end = end

                current_video = video_clip.subclipped(start / 1000, seg_end / 1000)

                instr_path = _extract_segment(start, seg_end)
                instrumental_segment = AudioFileClip(instr_path) if instr_path else None
                tts_audio = AudioFileClip(output_path)

                if needs_video_adjust and wav_time > ((seg_end - start) / 1000) * 1.1:
                    # 仍然超时 → 视频调速兜底
                    video_segmenter.slow_down_video_to_file(
                        current_video, instrumental_segment, tts_audio,
                        output_path, start, text_cn, text_en, seg_end,
                    )
                    adj_type = "limit_video"
                else:
                    video_segmenter.current_video_to_file(
                        current_video, instrumental_segment, tts_audio,
                        output_path, start, text_cn,
                        (start, seg_end, text_en), seg_end,
                    )
                    adj_type = "global_rate"

                tts_audio.close()
                if instrumental_segment is not None:
                    instrumental_segment.close()
                current_video.close()

                resume_manager.mark_processed(start, end)
                resume_manager.save()

                results.append(SubResult(
                    index=i, start_ms=start, end_ms=end,
                    success=True, wav_time=wav_time,
                    rate_used=global_rate_str,
                    adjustment_type=adj_type,
                ))
                processed += 1

            except Exception as e:
                results.append(SubResult(
                    index=i, start_ms=start, end_ms=end,
                    success=False, error=str(e),
                ))
                errors += 1
            finally:
                if progress_callback:
                    progress_callback(i, total, {"ok": processed, "err": errors, "skip": skipped})

        # 清理预扫临时文件
        for scan in pre_scan:
            try:
                os.remove(scan["base_path"])
            except OSError:
                pass

        return ProcessResult(
            results=results,
            total_success=processed,
            total_error=errors,
            global_rate_used=global_rate_str,
        )


# ── 工厂 ──────────────────────────────────────────────


def create_strategy(speed_mode: str, ctx: Optional[StrategyContext] = None) -> SpeedStrategy:
    """根据 speed_mode 创建策略实例。

    Args:
        speed_mode: "per_segment" | "global"
        ctx: StrategyContext，None 则使用默认值

    Returns:
        SpeedStrategy 实例
    """
    if ctx is None:
        ctx = StrategyContext()

    if speed_mode == "global":
        return GlobalStrategy(ctx)
    return PerSegmentStrategy(ctx)
