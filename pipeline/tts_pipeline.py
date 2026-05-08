"""
TTS Pipeline — 新旧交替期的主编排器

将 EdgeTTSEngine + TimingAdjuster + VideoSegmenter + CaptionRenderer + OpenVoiceCloner
组装为端到端流水线。

原 `SrtTxtToAudio.EdgeTTS_TXT_To_Audio()` 的入口逻辑分散到 TtsPipeline.run() 中。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
from tqdm import tqdm
import sys
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional, Tuple

from pipeline.tts_config import TTSConfig
from pipeline.tts_edge import EdgeTTSEngine
from pipeline.tts_timing import TimingAdjuster, AdjustResult
from pipeline.tts_video import VideoSegmenter
from pipeline.tts_caption import CaptionRenderer
from pipeline.vc_base import VoiceCloneConfig, NoopVoiceCloner
from pipeline.tts_resume import ResumeManager, ResumeState

from pipeline.tts_engine import BaseTTSEngine
from pipeline.logger import get_logger

logger = get_logger(__name__)


class TtsPipeline:
    """TTS 流水线编排器。

    组装 TTS 引擎 → 时序对齐 → 视频段处理 → 字幕渲染 → 声音克隆
    支持断点续传、单条错误跳过、进度反馈。
    """

    def __init__(
        self,
        config: TTSConfig,
        tts_engine: Optional[BaseTTSEngine] = None,
        timing_adjuster: Optional[TimingAdjuster] = None,
        video_segmenter: Optional[VideoSegmenter] = None,
        caption_renderer: Optional[CaptionRenderer] = None,
        voice_cloner=None,
        resume_manager: Optional[ResumeManager] = None,
    ):
        """
        Args:
            config: TTS 全局配置
            tts_engine: TTS 引擎（默认 EdgeTTSEngine）
            timing_adjuster: 时序对齐器
            video_segmenter: 视频段处理器
            caption_renderer: 字幕渲染器
            openvoice_cloner: OpenVoice 声音克隆器
            resume_manager: 断点续传管理器。为 None 时根据 config.enable_resume 自动创建
        """
        self.config = config

        # ── GPU 编码器自动检测（必须在创建默认组件之前） ──────
        try:
            from pipeline.gpu_detect import apply_best_encoder_to_config
            apply_best_encoder_to_config(self.config)
        except Exception:
            pass  # 检测失败不影响主流程

        self.engine = tts_engine or self._default_engine()
        self.timing = timing_adjuster or self._default_timing()
        self.voice_cloner = voice_cloner or self._default_voice_cloner()
        self.caption = caption_renderer or self._default_caption()
        self.video_seg = video_segmenter or self._default_video()

        # ── 断点续传（基于输出文件存在性） ──────────────
        video_out = os.path.join(config.output_dir, "video")
        if resume_manager is not None:
            self._resume_manager = resume_manager
        else:
            self._resume_manager = ResumeManager(video_output_dir=video_out)
            if not config.enable_resume:
                # 默认全新运行：不跳过已有文件
                self._resume_manager.is_processed = lambda start, end: False

        # 多线程同步锁
        self._lock1 = threading.Lock()
        self._lock2 = threading.Lock()

        # 运行时状态
        self._error_subtitles: list = []
        self._count = 0
        self._subs_last_count = 0
        self._call_back = 0
        self._over_time_audio_list: list = []
        self._subs_list: list = []
        self._queue_list: list = []

        # 线程池
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=config.threading_workers
        )

    # ── 默认组件工厂 ──────────────────────────────────

    def _default_engine(self):
        """根据 config.engine_type 自动创建 TTS 引擎。"""
        if self.config.engine_type == "chattts":
            from pipeline.tts_chattts import ChatTTSEngine
            return ChatTTSEngine(
                speaker_seed=self.config.chattts_speaker_seed,
                model_source=self.config.chattts_model_source,
                model_path=self.config.chattts_model_path,
            )
        return EdgeTTSEngine(
            voice=self.config.voice,
        )

    def _default_timing(self) -> TimingAdjuster:
        return TimingAdjuster(
            speed_max=self.config.max_speed,
            base_speed=self.config.base_speed,
            search_method=self.config.search_method,
            trail_dir=os.path.join(self.config.output_dir, "trail"),
            audio_codec=self.config.audio_codec,
            audio_bitrate=self.config.audio_bitrate,
        )

    def _default_video(self) -> VideoSegmenter:
        voice_clone_enabled = self.config.voice_clone_engine != "none"
        return VideoSegmenter(
            video_output_dir=os.path.join(self.config.output_dir, "video"),
            clone_color=voice_clone_enabled,
            caption=self.config.enable_caption,
            speed_tolerance=self.config.speed_tolerance,
            video_speed_min=self.config.video_speed_min,
            video_speed_max=self.config.video_speed_max,
            openvoice_cloner=self.voice_cloner.clone if hasattr(self.voice_cloner, 'clone') else None,
            caption_renderer=self._render_caption,
            video_bitrate=self.config.video_bitrate,
            video_codec=self.config.video_codec,
            video_preset=self.config.video_preset,
            audio_codec=self.config.audio_codec,
        )

    def _default_caption(self) -> CaptionRenderer:
        return CaptionRenderer(
            font_path=self.config.caption_font,
            font_size=self.config.caption_font_size if self.config.caption_font_size > 0 else None,
            font_color=self.config.caption_font_color or "white",
            stroke_color=self.config.caption_stroke_color or "black",
            stroke_width=self.config.caption_stroke_width if self.config.caption_stroke_width > 0 else 0.5,
            bg_color=self.config.caption_bg_color or "rgba(0,0,0,128)",
            font_size_factor=self.config.caption_font_size_factor,
            caption_width_ratio=self.config.caption_width_ratio,
            max_lines=self.config.caption_max_lines,
            max_font_size=self.config.caption_max_font_size if self.config.caption_max_font_size > 0 else None,
            max_font_size_ratio=self.config.caption_max_font_size_ratio,
            min_font_size=self.config.caption_min_font_size,
            alignment=self.config.caption_alignment or "center",
            position=self.config.caption_position or "bottom",
        )

    def _default_voice_cloner(self):
        """根据 config.voice_clone_engine 创建 VoiceCloner。

        向后兼容：enable_openvoice=False 时，即使 voice_clone_engine 默认为 "openvoice" 也禁用。
        """
        engine = self.config.voice_clone_engine

        if engine == "none":
            return NoopVoiceCloner()

        # 向后兼容：旧 enable_openvoice 标志
        if engine == "openvoice" and not self.config.enable_openvoice:
            return NoopVoiceCloner()

        vc_config = VoiceCloneConfig(
            engine=engine,
            device=self.config.voice_clone_device,
            concurrent_workers=self.config.voice_clone_concurrency,
            vram_limit_mb=self.config.voice_clone_vram_limit_mb,
            color_audio_path="./speakers/Color_audio.WAV",
        )

        if engine == "cosyvoice":
            from pipeline.vc_cosyvoice import CosyVoiceCloner
            return CosyVoiceCloner(vc_config)
        else:
            from pipeline.vc_openvoice import OpenVoiceCloner
            return OpenVoiceCloner(vc_config)

    def _render_caption(self, video, duration: float, text_zh: str, text_eng: str):
        """字幕渲染回调（给 VideoSegmenter 使用）"""
        from moviepy import CompositeVideoClip
        return self.caption.render(video, duration, text_zh, text_eng)

    # ── 条目处理核心逻辑 ──────────────────────────────

    def generate_silence(self, duration: float, output_path: str):
        """生成静音音频（ffmpeg 版本，绕过 MoviePy 音频管线）。"""
        import subprocess
        from pipeline.utils import get_ffmpeg_exe
        ffmpeg = get_ffmpeg_exe()
        subprocess.run([
            ffmpeg, "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=mono",
            "-t", f"{duration:.3f}",
            "-acodec", "pcm_s16le",
            output_path,
        ], capture_output=True, check=True)

    def _process_single_subtitle(
        self,
        text_zh: str,
        text_eng: str,
        start: int,
        end: int,
        current_video,
        instrumental_audio,
        subs_next=None,
        caption_groups: list = None,
    ) -> Optional[dict]:
        """处理单条字幕：TTS → 时序对齐 → 视频段。

        Args:
            text_zh: 中文字幕
            text_eng: 英文字幕
            start: 字幕开始毫秒
            end: 字幕结束毫秒
            current_video: 视频剪辑片段
            instrumental_audio: 背景音乐片段
            subs_next: 下一条字幕 (start_ms, end_ms, text)

        Returns:
            成功返回结果字典，跳过返回 None，失败返回含 error 字段的字典
        """
        key = (start, end)

        output_audio_path = os.path.join(
            self.config.output_dir, "audio", f"audio_{start}_{end}.wav"
        )

        try:
            os.makedirs(os.path.dirname(output_audio_path), exist_ok=True)

            # 1. TTS 合成
            wav_time = self.engine.synthesize(
                text_zh, output_audio_path, f"+{self.config.base_speed}%"
            )
            wav_time_original = wav_time

            # 2. 时序对齐
            over_time_path, adj_result = self.timing.align(
                text=text_zh,
                wav_time=wav_time,
                start=start,
                end=end,
                output_audio_path=output_audio_path,
                subs_next=subs_next,
                tts_synthesize_fn=lambda t, p, r: self.engine.synthesize(t, p, r),
            )

            # 3. TTS 音频加载
            from moviepy import AudioFileClip
            load_path = (
                over_time_path
                if over_time_path and over_time_path != output_audio_path
                else output_audio_path
            )
            if not os.path.isfile(load_path):
                raise FileNotFoundError(f"TTS 音频文件不存在: {load_path}")
            tts_audio = AudioFileClip(load_path)

            # 4. 视频段处理（统一走 slow_down_video_to_file）
            #    根据视频时长/TTS时长自动计算 speed_factor，
            #    sf=1.0 时等价于不变速。
            self.video_seg.slow_down_video_to_file(
                current_video, instrumental_audio, tts_audio,
                load_path, start, text_zh, text_eng, end,
                caption_groups=caption_groups,
            )

            tts_audio.close()

            return {
                "start": start,
                "end": end,
                "text_zh": text_zh,
                "text_eng": text_eng,
                "wav_time": wav_time_original,
                "adjustment": adj_result.adjustment_type,
                "success": True,
            }

        except FileNotFoundError as e:
            # 文件缺失：标记为错误，继续处理后续条目
            error_msg = str(e)
            self._log_subtitle_error(start, end, text_zh, error_msg)
            return {"start": start, "end": end, "text_zh": text_zh, "error": error_msg, "success": False}

        except OSError as e:
            # I/O 错误（磁盘满、权限等）：标记为错误，继续
            error_msg = f"I/O 错误: {e}"
            self._log_subtitle_error(start, end, text_zh, error_msg)
            return {"start": start, "end": end, "text_zh": text_zh, "error": error_msg, "success": False}

        except RuntimeError as e:
            # TTS 引擎错误（重试耗尽等）：标记为错误，继续
            error_msg = f"TTS 引擎错误: {e}"
            self._log_subtitle_error(start, end, text_zh, error_msg)
            return {"start": start, "end": end, "text_zh": text_zh, "error": error_msg, "success": False}

        except Exception as e:
            # 其他意外错误：标记为错误，继续
            error_msg = f"未预期的错误 ({type(e).__name__}): {e}"
            self._log_subtitle_error(start, end, text_zh, error_msg)
            return {"start": start, "end": end, "text_zh": text_zh, "error": error_msg, "success": False}

    def _log_subtitle_error(self, start: int, end: int, text: str, error: str):
        """记录单条字幕的处理错误（线程安全）。"""
        tqdm.write(f"[ERROR] 字幕 [{start}-{end}] 处理失败: {error}")
        with self._lock1:
            self._resume_manager.add_error(start, end, text, error)

    # ── 主入口 ────────────────────────────────────────

    def run(
        self,
        video_path: str,
        instrumental_path: str | None,
        chinese_srt_path: str,
        english_srt_path: str,
    ):
        """执行端到端 TTS 流水线。

        对应原版 `SrtTxtToAudio.EdgeTTS_TXT_To_Audio()`。
        支持断点续传：重新运行时跳过已处理的字幕。
        支持错误兜底：单条失败不影响后续条目。

        Args:
            video_path: 原视频路径
            instrumental_path: 背景音乐 WAV 路径（None 表示无背景乐，仅使用 TTS 音频）
            chinese_srt_path: 中文 SRT 字幕路径
            english_srt_path: 英文 SRT 字幕路径
        """
        from moviepy import VideoFileClip, AudioFileClip

        # 加载 SRT
        from pipeline.tts_config import parse_srt
        from pipeline.utils import get_ffmpeg_exe
        subs_cn = parse_srt(chinese_srt_path)
        subs_en = parse_srt(english_srt_path)

        video = VideoFileClip(video_path)
        total_duration = video.duration
        ffmpeg_exe = get_ffmpeg_exe()

        # 设置 ResumeManager 总字幕数
        self._resume_manager.state.total_subs = len(subs_cn)

        logger.info(f"TTS Pipeline: {len(subs_cn)} 条字幕, 视频总长 {total_duration:.1f}s")

        # ── 字幕渲染优化（可选） ───────────────────────
        caption_groups = None
        if self.config.enable_subtitle_optimization and self.config.enable_caption:
            from pipeline.subtitle_optimizer import optimize
            caption_groups = optimize(subs_cn, subs_en, self.caption, video.w)
            total_sub_captions = sum(len(g) for g in caption_groups)
            if total_sub_captions > len(subs_cn):
                logger.info(f"字幕优化: {len(subs_cn)} → {total_sub_captions} 段 (拆分 {total_sub_captions - len(subs_cn)} 条)")

        # 背景音乐：提取各个视频段对应的独立 WAV 片段
        def _extract_instrumental_segment(seg_start_ms: int, seg_end_ms: int) -> str | None:
            """用 ffmpeg 提取一段独立的背景乐文件。

            instrumental_path 为 None 时返回 None，表示无背景乐可用。
            """
            if instrumental_path is None:
                return None
            seg_dir = os.path.join(self.config.output_dir, "audio_segments")
            os.makedirs(seg_dir, exist_ok=True)
            seg_path = os.path.join(seg_dir, f"instr_{seg_start_ms}_{seg_end_ms}.wav")
            if not os.path.isfile(seg_path):
                import subprocess
                subprocess.run(
                    [ffmpeg_exe, "-y", "-i", instrumental_path,
                     "-ss", str(seg_start_ms / 1000),
                     "-to", str(seg_end_ms / 1000),
                     "-acodec", "pcm_s16le",
                     seg_path],
                    capture_output=True, check=True,
                )
            return seg_path

        # 处理开头/结尾无人声
        self.video_seg.handle_begin_end_silence(
            video, instrumental_path, subs_cn, total_duration, _extract_instrumental_segment
        )

        # ── Global 模式：全局统一调速 ─────────────────
        if self.config.speed_mode == "global":
            from pipeline.speed_strategy import create_strategy, StrategyContext

            def _synth_fn(text: str, path: str, rate: str) -> float:
                return self.engine.synthesize(text, path, rate)

            strategy = create_strategy("global", StrategyContext(
                trail_dir=os.path.join(self.config.output_dir, "trail"),
                audio_output_dir=os.path.join(self.config.output_dir, "audio"),
                video_output_dir=os.path.join(self.config.output_dir, "video"),
                audio_codec=self.config.audio_codec,
                audio_bitrate=self.config.audio_bitrate,
                video_bitrate=self.config.video_bitrate,
                speed_max=self.config.max_speed,
                base_speed=self.config.base_speed,
                video_speed_min=self.config.video_speed_min,
                video_speed_max=self.config.video_speed_max,
                search_method=self.config.search_method,
            ))

            def pbar_fn(idx, total, stats):
                if hasattr(self, "_pbar"):
                    self._pbar.update(1)
                    self._pbar.set_postfix(**stats, refresh=False)

            self._pbar = tqdm(total=len(subs_cn), desc="Global TTS", unit="条", ncols=80)
            result = strategy.process(
                subs_cn, subs_en, _synth_fn,
                video, instrumental_path,
                self.video_seg, self._resume_manager,
                progress_callback=pbar_fn,
            )
            self._pbar.close()
            processed = result.total_success
            skipped = len(subs_cn) - processed - result.total_error
            errors = result.total_error

        # ── PerSegment 模式：并行逐段精细调速 ──
        else:
            total = len(subs_cn)
            skipped = 0
            errors = 0
            processed = 0

            pbar = tqdm(total=total, desc="🎤 TTS 转写", unit="条", ncols=80)

            # Phase 1: 准备所有任务参数（主线程）
            tasks = []
            for i, (start, end, text_cn) in enumerate(subs_cn):
                # 安全检查：跳过无效时间戳
                if end <= start:
                    tqdm.write(f"  [WARN] 跳过无效字幕段 #{i}: start={start}ms >= end={end}ms")
                    skipped += 1
                    pbar.update(1)
                    continue
                if start < 0 or end < 0:
                    tqdm.write(f"  [WARN] 跳过负时间戳字幕段 #{i}")
                    skipped += 1
                    pbar.update(1)
                    continue

                # 断点续传：跳过已处理的
                if self._resume_manager.is_processed(start, end):
                    skipped += 1
                    pbar.update(1)
                    continue

                text_en = subs_en[i][2] if i < len(subs_en) else ""

                # 获取下一条字幕（SRT 已知，无依赖）
                subs_next = subs_cn[i + 1] if i + 1 < len(subs_cn) else None
                subs_next_tuple = (subs_next[0], subs_next[1], subs_next[2]) if subs_next else None

                # 裁剪视频段（独立 VideoFileClip，线程安全）
                # 不能用 video.subclipped() → 共享 reader 多线程冲突
                video_end = subs_next[0] if subs_next else end
                current_video = VideoFileClip(video_path).subclipped(start / 1000, video_end / 1000)

                # 背景乐段同步扩展
                instr_seg_path = _extract_instrumental_segment(start, video_end)
                instrumental_segment = AudioFileClip(instr_seg_path) if instr_seg_path else None

                tasks.append({
                    "text_cn": text_cn,
                    "text_en": text_en,
                    "start": start,
                    "end": end,
                    "current_video": current_video,
                    "instrumental_segment": instrumental_segment,
                    "subs_next": subs_next_tuple,
                    "caption_groups": caption_groups[i] if caption_groups else None,
                })

            # Phase 2: 并行提交到线程池
            if tasks:
                futures = {}
                for task in tasks:
                    future = self._executor.submit(
                        self._process_single_subtitle,
                        task["text_cn"], task["text_en"],
                        task["start"], task["end"],
                        task["current_video"], task["instrumental_segment"],
                        subs_next=task["subs_next"],
                        caption_groups=task["caption_groups"],
                    )
                    futures[future] = task

                # Phase 3: 收集结果并更新进度
                for future in concurrent.futures.as_completed(futures):
                    task = futures[future]
                    start, end = task["start"], task["end"]
                    try:
                        result = future.result()
                        if result and result.get("success"):
                            processed += 1
                        elif result and not result.get("success"):
                            errors += 1
                        else:
                            skipped += 1
                    except Exception as e:
                        errors += 1
                        tqdm.write(f"  [ERROR] 字幕 [{start}-{end}] 线程异常: {e}")
                    finally:
                        # 清理视频/音频资源
                        try:
                            task["current_video"].close()
                        except Exception:
                            pass
                        if task["instrumental_segment"] is not None:
                            try:
                                task["instrumental_segment"].close()
                            except Exception:
                                pass
                        pbar.update(1)
                        pbar.set_postfix(ok=processed, err=errors, skip=skipped, refresh=False)

            pbar.close()
        video.close()

        # 最终报告
        summary = (
            f"TTS Pipeline 完成 | 总计:{total} 成功:{processed} 跳过:{skipped}"
        )
        if errors > 0:
            logger.warning(summary + f" 失败:{errors}")
            for err in self._resume_manager.state.error_subtitles:
                logger.error(f"[{err['start']}-{err['end']}]: {err['error']}")
        else:
            logger.info(summary)

        # 合并视频段
        if self.config.enable_merge:
            self._merge_segments()

    def _merge_segments(self):
        """合并所有视频段为完整视频。"""
        from pipeline.video_merger import VideoMerger, MergerConfig

        merger_config = MergerConfig(
            strategy=self.config.merge_strategy,
            video_encoder=self.config.video_codec,
            audio_encoder=self.config.video_audio_codec,
        )
        merger = VideoMerger(merger_config)

        segment_dir = self.video_seg.video_output_dir
        result = merger.merge(segment_dir, self.config.final_output_path)

        if result:
            logger.info(f"最终视频已保存: {result}")
        else:
            logger.warning(f"视频段合并失败，各段仍保留在 {segment_dir}")
