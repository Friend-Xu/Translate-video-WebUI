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
from pipeline.utils import safe_replace
import sys
import queue
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


_CHATTS_MODEL_SIZE_GB = 2.37
_CHATTS_VRAM_OVERHEAD_GB = 1.0


def calc_chattts_workers(model_size_gb: float = _CHATTS_MODEL_SIZE_GB,
                         overhead_gb: float = _CHATTS_VRAM_OVERHEAD_GB) -> int:
    """根据 GPU 显存计算 ChatTTS 可并行加载的模型副本数。

    每个 worker 加载一份独立模型（~2.37 GB），需要充足显存。
    """
    try:
        import torch
        if torch.cuda.is_available():
            total_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            available = total_gb - overhead_gb
            workers = max(1, int(available / model_size_gb))
            logger.info(f"ChatTTS VRAM: {total_gb:.1f} GB → 最大 {workers} worker(s)")
            return workers
    except Exception:
        pass
    return 1


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

        self.timing = timing_adjuster or self._default_timing()
        self.voice_cloner = voice_cloner or self._default_voice_cloner()
        self.caption = caption_renderer or self._default_caption()
        self.video_seg = video_segmenter or self._default_video()

        # ── 引擎 ────────────────────────────────────────────
        # ChatTTS: PyTorch/CUDA 操作非线程安全，多实例并发推理
        # 已知在 Windows 上导致 STATUS_HEAP_CORRUPTION (0xC0000374)。
        # 使用单引擎 + _CHATTS_LOCK 串行化推理，消除并发 CUDA 访问。
        self._engine_pool: queue.Queue | None = None
        if tts_engine is not None:
            self.engine = tts_engine
            n_workers = config.threading_workers
        elif config.engine_type in ("chattts", "coqui", "cosyvoice"):
            n_workers = 1
            self.engine = self._default_engine()
            self.engine.warmup()
            logger.info("%s 单引擎模式（并发安全）", config.engine_type)
        else:
            self.engine = self._default_engine()
            n_workers = config.threading_workers

        # ── 断点续传 ──────────────────────────────────────
        video_out = os.path.join(config.output_dir, "video")
        if resume_manager is not None:
            self._resume_manager = resume_manager
        else:
            self._resume_manager = ResumeManager(video_output_dir=video_out)
            if not config.enable_resume:
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

        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=n_workers)

    def _borrow_engine(self):
        """从池中借用一个引擎实例（阻塞直到有可用）。"""
        if self._engine_pool is not None:
            return self._engine_pool.get()
        return self.engine

    def _return_engine(self, engine):
        """归还引擎到池中。"""
        if self._engine_pool is not None:
            self._engine_pool.put(engine)

    def cleanup(self):
        """释放所有 GPU 模型和线程池资源。"""
        # 1. 释放引擎池
        if self._engine_pool is not None:
            while True:
                try:
                    engine = self._engine_pool.get_nowait()
                    if hasattr(engine, 'cleanup'):
                        engine.cleanup()
                except queue.Empty:
                    break
            self._engine_pool = None
        if self.engine is not None and hasattr(self.engine, 'cleanup'):
            self.engine.cleanup()
            self.engine = None

        # 2. 释放声音克隆模型
        if self.voice_cloner is not None and hasattr(self.voice_cloner, 'cleanup'):
            try:
                self.voice_cloner.cleanup()
            except Exception:
                pass

        # 3. 关闭线程池
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None

        # 4. 释放 CUDA 缓存
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass
        import gc
        gc.collect()

    def _find_vocals(self, video_path: str) -> str | None:
        """Derive the Demucs vocal WAV path from the video path.

        Tries workspace convention first, then legacy flat convention.
        """
        target = os.path.dirname(video_path)
        name = os.path.splitext(os.path.basename(video_path))[0]
        ws_vocals = os.path.join(target, f"{name}_project", "01_extract", "vocals.wav")
        if os.path.isfile(ws_vocals):
            return ws_vocals
        # Legacy: flat naming in same directory
        legacy = os.path.join(target, f"{name}_(Vocals).wav")
        if os.path.isfile(legacy):
            return legacy
        return None

    def _create_color_audio(self, vocals_path: str, video_path: str) -> str | None:
        """Extract the highest-energy 10s segment from vocals for speaker embedding."""
        import numpy as np
        import soundfile as sf

        target = os.path.dirname(video_path)
        name = os.path.splitext(os.path.basename(video_path))[0]
        color_dir = os.path.join(target, f"{name}_project", "03_tts")
        color_path = os.path.join(color_dir, "Color_audio.WAV")

        if os.path.isfile(color_path):
            return color_path

        try:
            audio, sr = sf.read(vocals_path)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            total_s = len(audio) / sr
            if total_s < 10:
                os.makedirs(color_dir, exist_ok=True)
                sf.write(color_path, audio, sr)
                return color_path

            # Sliding window RMS energy — pick the 10s window with most speech
            window_s = int(10 * sr)
            hop_s = int(1 * sr)
            best_score = -1.0
            best_start = 0
            for i in range(0, len(audio) - window_s, hop_s):
                chunk = audio[i:i + window_s]
                rms = np.sqrt(np.mean(chunk ** 2))
                if rms > best_score:
                    best_score = rms
                    best_start = i

            best_end = min(best_start + window_s, len(audio))
            os.makedirs(color_dir, exist_ok=True)
            sf.write(color_path, audio[best_start:best_end], sr)
            logger.info("Color_audio.WAV 已创建: %.1fs (vocals 最高能量段, RMS=%.4f)", (best_end - best_start) / sr, best_score)
            return color_path
        except Exception as e:
            logger.warning("Color_audio.WAV 提取失败: %s，回退到完整 vocals", e)
            return None

    # ── 默认组件工厂 ──────────────────────────────────

    def _default_engine(self):
        """根据 config.engine_type 自动创建 TTS 引擎。"""
        if self.config.engine_type == "chattts":
            from pipeline.tts_chattts import ChatTTSEngine
            return ChatTTSEngine(
                speaker_seed=self.config.chattts_speaker_seed,
                model_source=self.config.chattts_model_source,
                model_path=self.config.chattts_model_path,
                speaker_pt=self.config.chattts_speaker_pt,
            )
        if self.config.engine_type == "cosyvoice":
            from pipeline.tts_cosyvoice import CosyVoiceTTSEngine
            return CosyVoiceTTSEngine(
                model_version=self.config.cosyvoice_tts_model_version,
                model_path=self.config.cosyvoice_tts_model_path,
                prompt_audio=self.config.cosyvoice_tts_prompt_audio,
                prompt_text=self.config.cosyvoice_tts_prompt_text,
                fp16=self.config.cosyvoice_tts_fp16,
                default_speed=self.config.cosyvoice_tts_speed,
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
        voice_clone_enabled = self.config.voice_clone_active
        return VideoSegmenter(
            video_output_dir=os.path.join(self.config.output_dir, "video"),
            clone_color=voice_clone_enabled,
            caption=self.config.enable_caption,
            speed_tolerance=self.config.speed_tolerance,
            video_speed_min=self.config.video_speed_min,
            video_speed_max=self.config.video_speed_max,
            voice_cloner_callback=self.voice_cloner.clone if hasattr(self.voice_cloner, 'clone') else None,
            caption_renderer=self._render_caption,
            video_bitrate=self.config.video_bitrate,
            video_codec=self.config.video_codec,
            video_preset=self.config.video_preset,
            audio_codec=self.config.audio_codec,
            bgm_volume=self.config.bgm_volume,
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
            font_size_mode=self.config.caption_font_size_mode,
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

        if not self.config.voice_clone_active:
            return NoopVoiceCloner()

        vc_config = VoiceCloneConfig(
            engine=engine,
            device=self.config.voice_clone_device,
            concurrent_workers=self.config.voice_clone_concurrency,
            vram_limit_mb=self.config.voice_clone_vram_limit_mb,
            color_audio_path="./speakers/Color_audio.WAV",
            error_log_path=os.path.join(self.config.output_dir, "voice_clone_error_log.txt"),
            model_dir="./models/CosyVoice2-0.5B" if engine == "cosyvoice" else "./models",
            cosyvoice_mode=self.config.cosyvoice_mode,
            model_version=self.config.cosyvoice_model_version,
            cosyvoice_fp16=self.config.cosyvoice_fp16,
            cosyvoice_docker_url=self.config.cosyvoice_docker_url,
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
        ], capture_output=True, check=True, timeout=30)

    def _process_single_subtitle(
        self,
        text_zh: str,
        text_eng: str,
        start: int,
        end: int,
        video_path: str,
        video_end: int,
        instrumental_path: str | None = None,
        subs_next=None,
        caption_groups: list = None,
    ) -> Optional[dict]:
        """处理单条字幕：TTS → 时序对齐 → 视频段。

        VideoFileClip/AudioFileClip 在 worker 线程内按需创建并释放，
        避免 Phase 1 预创建 137 个 clip 全部驻留内存导致 OOM。

        Args:
            video_path: 原视频路径（在 worker 内按需创建 clip）
            video_end: 视频段截止毫秒
            instrumental_path: 背景音乐 WAV 路径（None 表示无背景乐）
        """
        key = (start, end)

        output_audio_path = os.path.join(
            self.config.output_dir, "audio", f"audio_{start}_{end}.wav"
        )

        current_video = None
        instrumental_audio = None
        try:
            from moviepy import VideoFileClip, AudioFileClip

            current_video = VideoFileClip(video_path).subclipped(start / 1000, video_end / 1000)
            if instrumental_path:
                instrumental_audio = AudioFileClip(instrumental_path)
            os.makedirs(os.path.dirname(output_audio_path), exist_ok=True)

            # 1. TTS 合成（借用引擎，同一字幕段复用同一引擎处理对齐重试）
            engine = self._borrow_engine()
            engine_supports_rate = getattr(engine, 'supports_rate', lambda: True)()
            try:
                wav_time = engine.synthesize(
                    text_zh, output_audio_path, f"+{self.config.base_speed}%"
                )
                wav_time_original = wav_time

                # 2. 时序对齐
                # ChatTTS 不支持语速调节 → 跳过无效的 rate 搜索，
                # 改用 Rubber Band 后处理加速音频，仍超时则视频变速兜底
                if not engine_supports_rate:
                    segment_duration = (end - start) / 1000
                    from pipeline.tts_timing import AdjustResult
                    if wav_time > segment_duration:
                        from pipeline.audio_stretch import stretch_audio, compute_stretch_rate
                        stretch_rate = compute_stretch_rate(wav_time, segment_duration)
                        if stretch_rate is not None and stretch_rate <= 1.5:
                            stretched_path = output_audio_path + ".stretched.wav"
                            try:
                                new_dur = stretch_audio(output_audio_path, stretched_path, stretch_rate)
                                safe_replace(stretched_path, output_audio_path)
                                wav_time = new_dur
                                wav_time_original = wav_time
                                logger.debug(f"RubberBand stretch: rate={stretch_rate:.2f}, "
                                    f"{segment_duration:.2f}s target → {new_dur:.2f}s")
                            except Exception:
                                pass  # stretch failed, use original
                        adj_result = AdjustResult("speed_up_limited",
                            over_time_path=output_audio_path,
                            final_duration=wav_time, rate_used="N/A")
                        over_time_path = output_audio_path
                    else:
                        over_time_path = None
                        adj_result = AdjustResult("re_write", final_duration=wav_time)
                else:
                    over_time_path, adj_result = self.timing.align(
                        text=text_zh,
                        wav_time=wav_time,
                        start=start,
                        end=end,
                    output_audio_path=output_audio_path,
                    subs_next=subs_next,
                    tts_synthesize_fn=lambda t, p, r: engine.synthesize(t, p, r),
                )
            finally:
                self._return_engine(engine)

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
            try:
                # 4. 视频段处理（统一走 slow_down_video_to_file）
                #    根据视频时长/TTS时长自动计算 speed_factor，
                #    sf=1.0 时等价于不变速。
                self.video_seg.slow_down_video_to_file(
                    current_video, instrumental_audio, tts_audio,
                    load_path, start, text_zh, text_eng, end,
                    caption_groups=caption_groups,
                )
            finally:
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

        finally:
            # 释放 worker 线程内创建的 clip 资源
            if current_video is not None:
                try:
                    current_video.close()
                except Exception:
                    pass
            if instrumental_audio is not None:
                try:
                    instrumental_audio.close()
                except Exception:
                    pass

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
        translated_srt_path: str,
        source_srt_path: str,
    ):
        """执行端到端 TTS 流水线。

        对应原版 `SrtTxtToAudio.EdgeTTS_TXT_To_Audio()`。
        支持断点续传：重新运行时跳过已处理的字幕。
        支持错误兜底：单条失败不影响后续条目。

        Args:
            video_path: 原视频路径
            instrumental_path: 背景音乐 WAV 路径（None 表示无背景乐，仅使用 TTS 音频）
            translated_srt_path: 翻译后 SRT 字幕路径（用于 TTS 朗读）
            source_srt_path: 源语言 SRT 字幕路径（用于双语字幕渲染）
        """
        from moviepy import VideoFileClip, AudioFileClip

        # 加载 SRT
        from pipeline.tts_config import parse_srt
        from pipeline.utils import get_ffmpeg_exe
        subs_translated = parse_srt(translated_srt_path)
        subs_src = parse_srt(source_srt_path)

        video = VideoFileClip(video_path)
        total_duration = video.duration
        ffmpeg_exe = get_ffmpeg_exe()

        # 设置 ResumeManager 总字幕数
        self._resume_manager.state.total_subs = len(subs_translated)

        # ── 断点续传: 加载 checkpoint 并初始化进度追踪 ──
        ws_dir = os.path.dirname(os.path.dirname(self.config.output_dir))
        try:
            from pipeline.checkpoint import PipelineCheckpoint
            self._ck = PipelineCheckpoint.load(ws_dir)
        except Exception:
            self._ck = None

        if self._ck is not None:
            self._ck.update_extra("tts", segs_total=len(subs_translated), segs_done=0)
            self._ck.save()

        logger.info(f"TTS Pipeline: {len(subs_translated)} 条字幕, 视频总长 {total_duration:.1f}s")

        # ── 音色克隆准备：提取人声 VAD 片段作为 Color_audio.WAV，然后提取 speaker embedding ──
        if self.config.voice_clone_active:
            vocals = self._find_vocals(video_path)
            if vocals:
                color = self._create_color_audio(vocals, video_path)
                ref = color or vocals
                ok = self.voice_cloner.prepare(ref)
                logger.info("音色克隆: speaker embedding %s (ref=%s)", "OK" if ok else "FAIL", os.path.basename(ref))
            else:
                logger.warning("音色克隆: 找不到 vocals.wav，跳过 prepare()")

        # ── 字幕渲染优化（可选） ───────────────────────
        caption_groups = None
        if self.config.enable_subtitle_optimization and self.config.enable_caption:
            from pipeline.subtitle_optimizer import optimize
            caption_groups = optimize(subs_translated, subs_src, self.caption, video.w)
            total_sub_captions = sum(len(g) for g in caption_groups)
            if total_sub_captions > len(subs_translated):
                logger.info(f"字幕优化: {len(subs_translated)} → {total_sub_captions} 段 (拆分 {total_sub_captions - len(subs_translated)} 条)")

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
                    capture_output=True, check=True, timeout=60,
                )
            return seg_path

        # 处理开头/结尾无人声
        self.video_seg.handle_begin_end_silence(
            video, instrumental_path, subs_translated, total_duration, _extract_instrumental_segment
        )

        # ── Global 模式：全局统一调速 ─────────────────
        if self.config.speed_mode == "global":
            from pipeline.speed_strategy import create_strategy, StrategyContext

            def _synth_fn(text: str, path: str, rate: str) -> float:
                engine = self._borrow_engine()
                try:
                    return engine.synthesize(text, path, rate)
                finally:
                    self._return_engine(engine)

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

            self._pbar = tqdm(total=len(subs_translated), desc="Global TTS", unit="条", ncols=80)
            result = strategy.process(
                subs_translated, subs_src, _synth_fn,
                video, instrumental_path,
                self.video_seg, self._resume_manager,
                progress_callback=pbar_fn,
            )
            self._pbar.close()
            processed = result.total_success
            skipped = len(subs_translated) - processed - result.total_error
            errors = result.total_error

        # ── PerSegment 模式：并行逐段精细调速 ──
        else:
            total = len(subs_translated)
            skipped = 0
            errors = 0
            processed = 0

            pbar = tqdm(total=total, desc="🎤 TTS 转写", unit="条", ncols=80)

            # Phase 1: 准备所有任务参数（主线程，仅轻量计算，不预创建 clip）
            tasks = []
            for i, (start, end, text_cn) in enumerate(subs_translated):
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

                text_en = subs_src[i][2] if i < len(subs_src) else ""

                # 获取下一条字幕（SRT 已知，无依赖）
                subs_next = subs_translated[i + 1] if i + 1 < len(subs_translated) else None
                subs_next_tuple = (subs_next[0], subs_next[1], subs_next[2]) if subs_next else None

                # 计算 video_end（不再预创建 VideoFileClip，由 worker 线程内按需创建）
                video_end = subs_next[0] if subs_next else end

                # 提取背景乐 WAV 片段（仅文件提取，AudioFileClip 由 worker 内创建）
                instr_seg_path = _extract_instrumental_segment(start, video_end)

                tasks.append({
                    "text_cn": text_cn,
                    "text_en": text_en,
                    "start": start,
                    "end": end,
                    "video_end": video_end,
                    "instr_seg_path": instr_seg_path,
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
                        video_path,
                        task["video_end"],
                        instrumental_path=task["instr_seg_path"],
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
                            # 每 10 条释放一次 CUDA 缓存，防碎片化累积导致 OOM
                            if processed % 10 == 0:
                                try:
                                    import torch
                                    torch.cuda.empty_cache()
                                except Exception:
                                    pass
                                import gc
                                gc.collect()
                            if self._ck is not None and processed % 10 == 0:
                                self._ck.update_extra("tts", segs_done=processed)
                                self._ck.save()
                        elif result and not result.get("success"):
                            errors += 1
                        else:
                            skipped += 1
                    except Exception as e:
                        errors += 1
                        tqdm.write(f"  [ERROR] 字幕 [{start}-{end}] 线程异常: {e}")
                    finally:
                        # clip 资源已由 _process_single_subtitle 的 finally 块释放
                        pbar.update(1)
                        pbar.set_postfix(ok=processed, err=errors, skip=skipped, refresh=False)

            # Final checkpoint save
            if self._ck is not None:
                self._ck.update_extra("tts", segs_done=processed)
                self._ck.save()

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
